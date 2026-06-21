from __future__ import annotations

import hashlib
import heapq
import math
import re
from collections import Counter, defaultdict, deque
from pathlib import Path
from typing import Any

from rs_core.common.io import iter_jsonl, read_json
from rs_core.recsys.two_tower_query import apply_user_tower_projection, build_two_tower_query_for_user
from rs_core.recsys.types import MergedCandidate, RecallCandidate
from rs_core.recsys.vector_index import VectorIndex, VectorSearchIndex, load_vector_index_artifact


_SEMANTIC_SEED_CONTEXT_CACHE_LIMIT = 4
_SEMANTIC_SEED_CONTEXT_CACHE: dict[tuple[int, tuple[str, ...], float, int], dict[str, Any]] = {}
_SEMANTIC_TITLE_CATEGORY_CONTEXT_CACHE_LIMIT = 4
_SEMANTIC_TITLE_CATEGORY_CONTEXT_CACHE: dict[tuple[int, tuple[str, ...], int], dict[str, Any]] = {}
_METADATA_NEIGHBOR_INDEX_CACHE_LIMIT = 4
_METADATA_NEIGHBOR_INDEX_CACHE: dict[tuple[int, tuple[str, ...]], dict[str, Any]] = {}
_SWING_SIDECAR_SCHEMA_VERSION = "full_train_swing_sidecar_v1"
_SWING_FORBIDDEN_SOURCE_STATUSES = {"TARGET_SLICE_DIAGNOSTIC", "PARTIAL", "FAILED", "BLOCKED"}
_SWING_FORBIDDEN_TRUE_FLAGS = {
    "agent_allowed",
    "agent_exposure_allowed",
    "agent_tool_allowed",
    "candidate_generation_allowed",
    "final_pool500_ready_claimed",
    "pool1000_allowed",
    "promotion_allowed",
    "ranking_input_replacement_allowed",
    "ranking_replacement_allowed",
    "serving_allowed",
    "serving_candidate_source_allowed",
}
_SWING_FORBIDDEN_INPUT_TOKENS = {
    "/all_window/",
    "/holdout/",
    "/label/",
    "/labels/",
    "/test/",
    "/valid/",
    "all_interactions.jsonl",
    "canonical_interactions.jsonl",
    "canonical_interactions.test.jsonl",
    "canonical_interactions.valid.jsonl",
    "holdout.jsonl",
    "labels.jsonl",
    "user_sequences.jsonl",
    "user_sequences.test.jsonl",
    "user_sequences.valid.jsonl",
}
_SWING_REQUIRED_PARTIAL_INVALIDATION_KEYS = [
    "provenance.clean_manifest_signature.sha256",
    "provenance.train_user_sequences_signature.sha256",
    "parameters",
]
_CO_VISIT_TRANSITION_GRAPH_SOURCE_STATUS = "UNDERFILL_REPAIR_INDEX_READY"
_CO_VISIT_FORBIDDEN_TRUE_FLAGS = {
    "candidate_generation_allowed",
    "final_pool500_ready_claimed",
    "pool1000_allowed",
    "promotion_allowed",
    "ranking_input_replacement_allowed",
    "ranking_replacement_allowed",
    "serving_candidate_source_allowed",
}


def unique_recent_items(items: list[str], max_items_per_user: int) -> list[str]:
    recent = deque(maxlen=max_items_per_user)
    seen: set[str] = set()
    for item_id in reversed(items):
        if item_id in seen:
            continue
        seen.add(item_id)
        recent.appendleft(item_id)
        if len(recent) >= max_items_per_user:
            break
    return list(recent)



def load_popular_candidates(path: str | Path, limit: int | None = None) -> list[RecallCandidate]:
    candidates: list[RecallCandidate] = []
    for row in iter_jsonl(path):
        item_id = row.get("parent_asin", "")
        if not item_id:
            continue
        candidates.append(
            RecallCandidate(
                item_id=item_id,
                source="popular",
                score=float(row.get("pop_score", 0.0) or 0.0),
                category=row.get("category", ""),
                metadata=row,
            )
        )
        if limit and len(candidates) >= limit:
            break
    return candidates


def load_itemcf_by_source(
    path: str | Path,
    source: str,
    allowed_src_items: set[str] | None = None,
) -> dict[str, list[RecallCandidate]]:
    return _load_item_pair_recall(path, source, allowed_src_items)


def load_co_visit_transition_graph_manifest(
    manifest_path: str | Path,
    allowed_src_items: set[str] | None = None,
) -> dict[str, list[RecallCandidate]]:
    manifest_path = Path(manifest_path)
    manifest = read_json(manifest_path)
    _validate_co_visit_transition_graph_manifest(manifest)
    outputs = manifest.get("outputs") if isinstance(manifest.get("outputs"), dict) else {}
    shard_values = _itemcf_manifest_shard_values(manifest, outputs)
    if shard_values:
        shard_count = int(manifest.get("shard_count") or len(shard_values))
        if manifest.get("shard_key") != "src_item_sha256_mod":
            raise ValueError(f"unsupported co_visit_fallback_repair shard_key: {manifest.get('shard_key')!r}")
        selected_shards = shard_values
        if allowed_src_items:
            selected_ids = {stable_itemcf_shard_id(item, shard_count) for item in allowed_src_items}
            selected_shards = [value for shard_id, value in enumerate(shard_values) if shard_id in selected_ids]
        by_source: dict[str, list[RecallCandidate]] = defaultdict(list)
        for shard_value in selected_shards:
            shard_path = _resolve_manifest_path(manifest_path, shard_value)
            for src_item, rows in _load_item_pair_recall(shard_path, "co_visit_fallback_repair", allowed_src_items).items():
                by_source[src_item].extend(rows)
        for rows in by_source.values():
            rows.sort(key=lambda item: (-item.score, item.item_id))
        return by_source
    edges_path = outputs.get("edges_path") or manifest.get("edges_path")
    if not edges_path:
        raise ValueError("co_visit_fallback_repair transition graph requires edges_shards or edges_path")
    return _load_item_pair_recall(_resolve_manifest_path(manifest_path, edges_path), "co_visit_fallback_repair", allowed_src_items)



def load_itemcf_source_manifest(
    manifest_path: str | Path,
    source: str,
    allowed_src_items: set[str] | None = None,
) -> dict[str, list[RecallCandidate]]:
    manifest_path = Path(manifest_path)
    manifest = read_json(manifest_path)
    if manifest.get("source") != source:
        raise ValueError(f"invalid {source} manifest source: {manifest.get('source')!r}")
    if manifest.get("train_only") is not True:
        raise ValueError(f"{source} manifest must be train_only")
    if manifest.get("source_status") not in (None, "DIAGNOSTIC_ONLY"):
        raise ValueError(f"{source} manifest must remain DIAGNOSTIC_ONLY")
    if manifest.get("diagnostic_only") is False:
        raise ValueError(f"{source} manifest must remain DIAGNOSTIC_ONLY")
    if manifest.get("candidate_generation_allowed") is True:
        raise ValueError(f"{source} manifest must not authorize candidate generation")
    if manifest.get("ranking_input_replacement_allowed") is True:
        raise ValueError(f"{source} manifest must not authorize ranking input replacement")
    if manifest.get("promotion_allowed") is True:
        raise ValueError(f"{source} manifest must not authorize promotion")
    if manifest.get("pool1000_allowed") is True:
        raise ValueError(f"{source} manifest must not authorize pool1000")

    outputs = manifest.get("outputs") if isinstance(manifest.get("outputs"), dict) else {}
    shard_values = _itemcf_manifest_shard_values(manifest, outputs)
    if shard_values:
        shard_count = int(manifest.get("shard_count") or len(shard_values))
        shard_key = manifest.get("shard_key")
        if shard_key != "src_item_sha256_mod":
            raise ValueError(f"unsupported {source} shard_key: {shard_key!r}")
        selected_shards = shard_values
        if allowed_src_items:
            selected_ids = {stable_itemcf_shard_id(item, shard_count) for item in allowed_src_items}
            selected_shards = [value for shard_id, value in enumerate(shard_values) if shard_id in selected_ids]
        by_source: dict[str, list[RecallCandidate]] = defaultdict(list)
        for shard_value in selected_shards:
            shard_path = _resolve_manifest_path(manifest_path, shard_value)
            for src_item, rows in _load_item_pair_recall(shard_path, source, allowed_src_items).items():
                by_source[src_item].extend(rows)
        for rows in by_source.values():
            rows.sort(key=lambda item: (-item.score, item.item_id))
        return by_source

    edges_path = outputs.get("edges_path") or manifest.get("edges_path")
    if not edges_path:
        return {}
    return load_itemcf_by_source(_resolve_manifest_path(manifest_path, edges_path), source, allowed_src_items)


def load_item_graph_recall(
    path: str | Path,
    allowed_src_items: set[str] | None = None,
) -> dict[str, list[RecallCandidate]]:
    return _load_item_pair_recall(path, "item_graph", allowed_src_items)


def _validate_co_visit_transition_graph_manifest(manifest: dict[str, Any]) -> None:
    if manifest.get("source") != "co_visit_fallback_repair":
        raise ValueError(f"invalid co_visit_fallback_repair manifest source: {manifest.get('source')!r}")
    if manifest.get("source_status") != _CO_VISIT_TRANSITION_GRAPH_SOURCE_STATUS:
        raise ValueError(f"invalid co_visit_fallback_repair source_status: {manifest.get('source_status')!r}")
    if manifest.get("index_scope") != "FULL_DERIVED_INDEX":
        raise ValueError(f"invalid co_visit_fallback_repair index_scope: {manifest.get('index_scope')!r}")
    if manifest.get("train_only") is not True:
        raise ValueError("co_visit_fallback_repair transition graph must be train_only")
    if manifest.get("candidate_materialization") != "none":
        raise ValueError("co_visit_fallback_repair transition graph must declare candidate_materialization='none'")
    if manifest.get("underfill_repair_allowed") is not True:
        raise ValueError("co_visit_fallback_repair transition graph must allow underfill repair")
    if manifest.get("batch_scoped_evidence_only") is True or manifest.get("status") == "TARGET_SLICE_DIAGNOSTIC":
        raise ValueError("target-slice co_visit_fallback_repair artifact cannot be used as transition graph")
    if manifest.get("candidates_path") is not None:
        raise ValueError("co_visit_fallback_repair transition graph must not expose candidates_path")
    outputs = manifest.get("outputs") if isinstance(manifest.get("outputs"), dict) else {}
    if outputs.get("candidates") is not None or outputs.get("candidates_path") is not None:
        raise ValueError("co_visit_fallback_repair transition graph must not expose candidate outputs")
    for flag in sorted(_CO_VISIT_FORBIDDEN_TRUE_FLAGS):
        if manifest.get(flag) is not False:
            raise ValueError(f"co_visit_fallback_repair transition graph must set {flag}=false")



def load_usercf_recall_sidecar(manifest_path: str | Path) -> dict[str, list[RecallCandidate]]:
    manifest_path = Path(manifest_path)
    manifest = read_json(manifest_path)
    if manifest.get("source") != "usercf_recall":
        raise ValueError(f"invalid usercf_recall manifest source: {manifest.get('source')!r}")
    if manifest.get("index_scope") != "FULL_DERIVED_INDEX":
        raise ValueError(f"invalid usercf_recall index_scope: {manifest.get('index_scope')!r}")
    if manifest.get("train_only") is not True:
        raise ValueError("usercf_recall manifest must be train_only")
    source_status = manifest.get("source_status")
    diagnostic_only = manifest.get("diagnostic_only")
    promoted_statuses = {"READY", "POOL500_RECALL_ONLY_SUPPLEMENTAL_READY"}
    if source_status not in (None, "DIAGNOSTIC_ONLY", *promoted_statuses):
        raise ValueError(f"invalid usercf_recall source_status: {source_status!r}")
    if diagnostic_only is False and source_status not in promoted_statuses:
        raise ValueError("promoted usercf_recall manifest must declare a promoted source_status")
    if diagnostic_only is not False and source_status in promoted_statuses:
        raise ValueError("promoted usercf_recall manifest must set diagnostic_only false; DIAGNOSTIC_ONLY manifests cannot use promoted status")
    if manifest.get("candidate_generation_allowed") is not False:
        raise ValueError("usercf_recall manifest must not authorize candidate generation")
    if manifest.get("ranking_input_replacement_allowed") is not False:
        raise ValueError("usercf_recall manifest must not authorize ranking input replacement")
    if manifest.get("pool1000_allowed") is not False:
        raise ValueError("usercf_recall manifest must not authorize pool1000")
    if manifest.get("promotion_allowed") is not False:
        raise ValueError("usercf_recall manifest must not authorize promotion")
    if manifest.get("final_pool500_ready_claimed") is not False:
        raise ValueError("usercf_recall manifest must not claim final pool500 ready")
    outputs = manifest.get("outputs") if isinstance(manifest.get("outputs"), dict) else {}
    shard_paths = outputs.get("candidate_shards") if isinstance(outputs.get("candidate_shards"), list) else []
    candidate_path = outputs.get("candidates")
    input_paths = shard_paths or ([candidate_path] if candidate_path else [])
    by_user: dict[str, list[RecallCandidate]] = defaultdict(list)
    total_row_count = 0
    for input_path in input_paths:
        resolved_path = _resolve_manifest_path(manifest_path, input_path)
        for line_number, row in enumerate(iter_jsonl(resolved_path), start=1):
            total_row_count += 1
            user_id = str(row.get("user_id") or "")
            if not user_id:
                raise ValueError(f"missing user_id in usercf_recall row {line_number}: {input_path}")
            candidates = row.get("candidates")
            if isinstance(candidates, list):
                for candidate in candidates:
                    _append_usercf_candidate(by_user, user_id, candidate, manifest_path, input_path, line_number)
                continue
            if row.get("item_id") or row.get("parent_asin"):
                _append_usercf_candidate(by_user, user_id, row, manifest_path, input_path, line_number)
                continue
            raise ValueError(f"missing candidates or item_id in usercf_recall row {line_number}: {input_path}")
    if total_row_count == 0:
        raise ValueError(f"empty usercf_recall candidate inputs: {input_paths}")
    for rows in by_user.values():
        rows.sort(key=lambda item: (-item.score, item.item_id))
    return by_user


def _append_usercf_candidate(
    by_user: dict[str, list[RecallCandidate]],
    user_id: str,
    candidate: Any,
    manifest_path: Path,
    source_path: Any,
    line_number: int,
) -> None:
    if not isinstance(candidate, dict):
        raise ValueError(f"invalid usercf_recall candidate in row {line_number}: {source_path}")
    item_id = str(candidate.get("item_id") or candidate.get("parent_asin") or "")
    if not item_id:
        raise ValueError(f"missing item_id in usercf_recall row {line_number}: {source_path}")
    source = str(candidate.get("canonical_source") or candidate.get("source") or "usercf_recall")
    if source != "usercf_recall":
        raise ValueError(f"invalid usercf_recall candidate source in row {line_number}: {source!r}")
    by_user[user_id].append(
        RecallCandidate(
            item_id=item_id,
            source="usercf_recall",
            score=float(candidate.get("score", 0.0) or 0.0),
            metadata={
                "usercf_rank": int(candidate.get("rank", len(by_user[user_id]) + 1)),
                "usercf_manifest_path": str(manifest_path),
            },
        )
    )


def load_swing_recall_sidecar(manifest_path: str | Path) -> dict[str, list[RecallCandidate]]:
    manifest_path = Path(manifest_path)
    manifest = read_json(manifest_path)
    _validate_swing_recall_manifest(manifest)
    edges_path = _validate_swing_required_edges_path(manifest_path, manifest)
    return _load_item_pair_recall(edges_path, "swing_recall")


def _validate_swing_recall_manifest(manifest: dict[str, Any]) -> None:
    strict_contract = _looks_like_strict_swing_contract(manifest)
    if strict_contract and manifest.get("schema_version") != _SWING_SIDECAR_SCHEMA_VERSION:
        raise ValueError(f"invalid swing_recall schema_version: {manifest.get('schema_version')!r}")
    if manifest.get("status") != "PASS":
        raise ValueError(f"invalid swing_recall status: {manifest.get('status')!r}")
    if manifest.get("source") != "swing_recall":
        raise ValueError(f"invalid swing_recall manifest source: {manifest.get('source')!r}")
    if manifest.get("source_status") in _SWING_FORBIDDEN_SOURCE_STATUSES:
        raise ValueError(f"invalid swing_recall source_status: {manifest.get('source_status')!r}")
    if manifest.get("index_scope") != "FULL_DERIVED_INDEX":
        raise ValueError(f"invalid swing_recall index_scope: {manifest.get('index_scope')!r}")
    if manifest.get("train_only") is not True:
        raise ValueError("swing_recall manifest must be train_only")
    for flag in sorted(_SWING_FORBIDDEN_TRUE_FLAGS):
        if manifest.get(flag) is True:
            raise ValueError(f"swing_recall manifest must not authorize {flag}")
    if not strict_contract:
        return
    if manifest.get("lifecycle_stage") != "builder_complete":
        raise ValueError(f"invalid swing_recall lifecycle_stage: {manifest.get('lifecycle_stage')!r}")
    input_contract = manifest.get("input_contract")
    if not isinstance(input_contract, dict):
        raise ValueError("swing_recall manifest missing input_contract")
    if input_contract.get("allowed_inputs") != ["clean_manifest.train_user_sequences_path"]:
        raise ValueError("swing_recall manifest must use clean_manifest.train_user_sequences_path only")
    train_path = str(input_contract.get("train_user_sequences_path") or manifest.get("train_user_sequences_path") or "")
    declared_inputs = [str(item) for item in _as_manifest_list(input_contract.get("declared_inputs")) if item]
    actual_input_values = [
        manifest.get("clean_manifest_path"),
        manifest.get("train_user_sequences_path"),
        input_contract.get("clean_manifest_path"),
        input_contract.get("train_user_sequences_path"),
        *declared_inputs,
    ]
    for value in actual_input_values:
        if _is_forbidden_swing_manifest_value(value):
            raise ValueError(f"forbidden swing_recall manifest value: {value!r}")
    if not train_path or Path(train_path).name != "user_sequences.train.jsonl":
        raise ValueError(f"swing_recall manifest must declare user_sequences.train.jsonl, got: {train_path!r}")
    if declared_inputs != [train_path]:
        raise ValueError(f"swing_recall manifest declared_inputs must match train path: {declared_inputs!r}")
    provenance = manifest.get("provenance") if isinstance(manifest.get("provenance"), dict) else {}
    train_signature = provenance.get("train_user_sequences_signature") if isinstance(provenance.get("train_user_sequences_signature"), dict) else {}
    clean_signature = provenance.get("clean_manifest_signature") if isinstance(provenance.get("clean_manifest_signature"), dict) else {}
    if not train_signature.get("sha256") or not clean_signature.get("sha256"):
        raise ValueError("swing_recall manifest missing train-only provenance signatures")
    if manifest.get("partial_invalidation_keys") != _SWING_REQUIRED_PARTIAL_INVALIDATION_KEYS:
        raise ValueError("swing_recall manifest missing partial invalidation contract")


def _validate_swing_required_edges_path(manifest_path: Path, manifest: dict[str, Any]) -> Path:
    strict_contract = _looks_like_strict_swing_contract(manifest)
    artifacts = manifest.get("required_artifacts") if isinstance(manifest.get("required_artifacts"), dict) else {}
    edges_value = artifacts.get("swing_recall_edges") or (None if strict_contract else manifest.get("edges_path"))
    if not edges_value:
        raise ValueError("swing_recall manifest missing required_artifacts.swing_recall_edges")
    if strict_contract and Path(str(edges_value)).name != "swing_recall_edges.jsonl":
        raise ValueError(f"invalid swing_recall edges artifact path: {edges_value!r}")
    if strict_contract and _is_forbidden_swing_artifact_path(edges_value):
        raise ValueError(f"forbidden swing_recall edges artifact path: {edges_value!r}")
    resolved = _resolve_manifest_path(manifest_path, edges_value).resolve()
    if strict_contract:
        try:
            resolved.relative_to(manifest_path.parent.resolve())
        except ValueError as exc:
            raise ValueError(f"swing_recall edges artifact path must stay under manifest directory: {edges_value!r}") from exc
    return resolved


def _looks_like_strict_swing_contract(manifest: dict[str, Any]) -> bool:
    return bool(
        manifest.get("schema_version") == _SWING_SIDECAR_SCHEMA_VERSION
        or manifest.get("input_contract")
        or manifest.get("lifecycle_stage")
        or manifest.get("provenance")
        or manifest.get("partial_invalidation_keys")
    )


def _is_forbidden_swing_manifest_value(value: Any) -> bool:
    normalized = str(value).replace("\\", "/").lower()
    return any(token in normalized for token in _SWING_FORBIDDEN_INPUT_TOKENS)


def _is_forbidden_swing_artifact_path(value: Any) -> bool:
    normalized = str(value).replace("\\", "/").lower()
    parts = [part for part in normalized.split("/") if part]
    forbidden_parts = {"all_window", "holdout", "label", "labels", "test", "valid"}
    return normalized.startswith("/") or ":" in normalized or ".." in parts or bool(set(parts) & forbidden_parts) or _is_forbidden_swing_manifest_value(value)


def _as_manifest_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, dict):
        return list(value.values())
    if isinstance(value, (list, tuple, set)):
        return list(value)
    return [value]


def load_graph_walk_seed_recall(
    path: str | Path,
    allowed_src_items: set[str] | None = None,
    manifest_path: str | Path | None = None,
) -> dict[str, list[RecallCandidate]]:
    if manifest_path is None:
        raise ValueError("graph_walk_seed manifest_path is required")
    _validate_graph_walk_seed_manifest(manifest_path, path)
    return _load_item_pair_recall(path, "graph_walk_seed", allowed_src_items, expected_algorithm="deepwalk")


def load_two_tower_seed_recall(
    path: str | Path,
    allowed_src_items: set[str] | None = None,
    manifest_path: str | Path | None = None,
) -> dict[str, list[RecallCandidate]]:
    if manifest_path is not None:
        _validate_two_tower_seed_manifest(manifest_path)
    by_source: dict[str, list[RecallCandidate]] = defaultdict(list)
    for line_number, row in enumerate(iter_jsonl(path), start=1):
        src_item = row.get("item_id")
        if not isinstance(src_item, str) or not src_item:
            raise ValueError(f"missing item_id in two_tower_seed sidecar row {line_number}")
        include_row = allowed_src_items is None or src_item in allowed_src_items
        neighbors = row.get("neighbors")
        if not isinstance(neighbors, list):
            raise ValueError(f"missing neighbors in two_tower_seed sidecar row {line_number}")
        seen_neighbors: set[str] = set()
        for neighbor_index, neighbor in enumerate(neighbors, start=1):
            if not isinstance(neighbor, dict):
                raise ValueError(f"invalid neighbor in two_tower_seed sidecar row {line_number}")
            dst_item = neighbor.get("item_id")
            if not isinstance(dst_item, str) or not dst_item:
                raise ValueError(f"missing neighbor item_id in two_tower_seed sidecar row {line_number}")
            if dst_item == src_item:
                raise ValueError(f"self neighbor in two_tower_seed sidecar row {line_number}: {src_item}")
            if dst_item in seen_neighbors:
                raise ValueError(f"duplicate neighbor item_id in two_tower_seed sidecar row {line_number}: {dst_item}")
            seen_neighbors.add(dst_item)
            rank = neighbor.get("rank", neighbor_index)
            try:
                score = float(neighbor.get("score", 0.0) or 0.0)
                rank_int = int(rank)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"invalid neighbor score or rank in two_tower_seed sidecar row {line_number}") from exc
            metadata = {
                "two_tower_seed_src_item": src_item,
                "two_tower_seed_neighbor_rank": rank_int,
                "two_tower_seed_neighbor_score": score,
            }
            if include_row:
                by_source[src_item].append(
                    RecallCandidate(
                        item_id=dst_item,
                        source="two_tower_seed",
                        score=score,
                        metadata=metadata,
                    )
                )
    for rows in by_source.values():
        rows.sort(key=lambda item: (-item.score, item.item_id))
    return by_source


def _validate_two_tower_seed_manifest(path: str | Path) -> None:
    manifest = read_json(path)
    expected = {
        "phase": "1.18",
        "source": "two_tower_seed",
        "schema_version": "two_tower_seed_neighbors_v1",
    }
    for key, value in expected.items():
        if manifest.get(key) != value:
            raise ValueError(f"invalid two_tower_seed manifest {key}: {manifest.get(key)!r}")


def _validate_graph_walk_seed_manifest(manifest_path: str | Path, sidecar_path: str | Path) -> None:
    sidecar_path = Path(sidecar_path)
    if not sidecar_path.exists():
        raise FileNotFoundError(str(sidecar_path))
    manifest = read_json(manifest_path)
    expected = {
        "phase": "1.19",
        "source": "graph_walk_seed",
        "schema_version": "graph_walk_seed_pairs_v1",
        "algorithm": "deepwalk",
    }
    for key, value in expected.items():
        if manifest.get(key) != value:
            raise ValueError(f"invalid graph_walk_seed manifest {key}: {manifest.get(key)!r}")
    expected_hash = manifest.get("sidecar_hash")
    if not isinstance(expected_hash, str) or not expected_hash:
        raise ValueError("invalid graph_walk_seed manifest sidecar_hash: missing")
    actual_hash = _sha256_file(Path(sidecar_path))
    if actual_hash != expected_hash:
        raise ValueError("invalid graph_walk_seed manifest sidecar_hash: mismatch")



def _resolve_manifest_path(manifest_path: Path, value: Any) -> Path:
    raw_value = str(value)
    path = Path(raw_value)
    if path.is_absolute() or path.exists():
        return path
    normalized_value = raw_value.replace("\\", "/")
    manifest_dir_name = manifest_path.parent.name
    marker = f"/{manifest_dir_name}/"
    if marker in normalized_value:
        candidate = manifest_path.parent / normalized_value.split(marker, 1)[1]
        if candidate.exists():
            return candidate
    return manifest_path.parent / path


def _manifest_output(manifest: dict[str, Any], key: str) -> Any:
    outputs = manifest.get("outputs") if isinstance(manifest.get("outputs"), dict) else {}
    return outputs.get(key)


def _itemcf_manifest_shard_values(manifest: dict[str, Any], outputs: dict[str, Any]) -> list[Any]:
    shard_values = outputs.get("edges_shards") if isinstance(outputs.get("edges_shards"), list) else manifest.get("edges_shards")
    if isinstance(shard_values, list) and shard_values:
        return shard_values
    shard_stats = outputs.get("edge_shard_stats") if isinstance(outputs.get("edge_shard_stats"), list) else manifest.get("edge_shard_stats")
    if not isinstance(shard_stats, list):
        return []
    values = []
    for shard in shard_stats:
        if isinstance(shard, dict) and shard.get("path"):
            values.append(shard["path"])
    return values


def stable_itemcf_shard_id(src_item: str, shard_count: int) -> int:
    if shard_count <= 0:
        raise ValueError("shard_count must be positive")
    digest = hashlib.sha256(src_item.encode("utf-8")).hexdigest()[:16]
    return int(digest, 16) % shard_count


def _load_item_pair_recall(
    path: str | Path,
    source: str,
    allowed_src_items: set[str] | None = None,
    expected_algorithm: str | None = None,
) -> dict[str, list[RecallCandidate]]:
    by_source: dict[str, list[RecallCandidate]] = defaultdict(list)
    for line_number, row in enumerate(iter_jsonl(path), start=1):
        row_source = row.get("source")
        if row_source is not None and row_source != source:
            raise ValueError(f"invalid {source} sidecar source in row {line_number}: {row_source!r}")
        if expected_algorithm is not None and row.get("algorithm") != expected_algorithm:
            raise ValueError(f"invalid {source} sidecar algorithm in row {line_number}: {row.get('algorithm')!r}")
        src_item = row.get("src_item", "")
        if allowed_src_items is not None and src_item not in allowed_src_items:
            continue
        dst_item = row.get("dst_item", "")
        if not src_item or not dst_item:
            continue
        by_source[src_item].append(
            RecallCandidate(
                item_id=dst_item,
                source=source,
                score=float(row.get("score", 0.0) or 0.0),
                metadata=row,
            )
        )
    for rows in by_source.values():
        rows.sort(key=lambda item: (-item.score, item.item_id))
    return by_source


def load_category_candidates(path: str | Path) -> dict[str, list[RecallCandidate]]:
    by_bucket: dict[str, list[RecallCandidate]] = {}
    for row in iter_jsonl(path):
        bucket = row.get("bucket", "")
        by_bucket[bucket] = [
            RecallCandidate(
                item_id=item.get("parent_asin", ""),
                source="category",
                score=float(item.get("score", 0.0) or 0.0),
                metadata=item,
            )
            for item in row.get("top_items", [])
            if item.get("parent_asin")
        ]
    return by_bucket


def load_category_profile_index(path: str | Path, target_user_ids: set[str] | None = None) -> dict[str, list[dict[str, Any]]]:
    profiles: dict[str, list[dict[str, Any]]] = {}
    remaining = set(target_user_ids or [])
    for row in iter_jsonl(path):
        user_id = str(row.get("user_id") or "")
        if not user_id:
            continue
        if target_user_ids is not None and user_id not in remaining:
            continue
        buckets = row.get("top_profile_buckets") or []
        if not isinstance(buckets, list):
            buckets = []
        profiles[user_id] = [dict(bucket) for bucket in buckets if isinstance(bucket, dict) and bucket.get("bucket")]
        if target_user_ids is not None:
            remaining.discard(user_id)
            if not remaining:
                break
    return profiles


def load_category_index_source_manifest(
    manifest_path: str | Path,
    target_user_ids: set[str] | None = None,
) -> tuple[dict[str, list[RecallCandidate]], dict[str, list[dict[str, Any]]]]:
    manifest_path = Path(manifest_path)
    manifest = read_json(manifest_path)
    if manifest.get("source") != "category":
        raise ValueError(f"invalid category manifest source: {manifest.get('source')!r}")
    if manifest.get("train_only") is not True:
        raise ValueError("category manifest must be train_only")
    if manifest.get("candidate_materialization") != "none":
        raise ValueError("category index manifest must declare candidate_materialization='none'")
    if manifest.get("candidates_path") is not None:
        raise ValueError("category index manifest must not require candidates_path")
    category_top_path = _resolve_manifest_path(manifest_path, manifest.get("category_top_items_index_path") or _manifest_output(manifest, "category_top_items_index"))
    profile_path = _resolve_manifest_path(manifest_path, manifest.get("user_category_profile_path") or _manifest_output(manifest, "user_category_profile"))
    return load_category_candidates(category_top_path), load_category_profile_index(profile_path, target_user_ids)


def load_semantic_index(path: str | Path, token_fields: list[str] | None = None) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for row in iter_jsonl(path):
        item_id = row.get("parent_asin", "")
        if not item_id:
            continue
        metadata = dict(row)
        metadata["semantic_tokens"] = _semantic_tokens(row, token_fields)
        index[item_id] = metadata
    return index


def load_two_tower_index(path: str | Path, token_fields: list[str] | None = None) -> dict[str, dict[str, Any]] | VectorIndex:
    if _looks_like_vector_artifact(path):
        return load_vector_index_artifact(path)

    index: dict[str, dict[str, Any]] = {}
    for row in iter_jsonl(path):
        item_id = row.get("parent_asin", "")
        if not item_id:
            continue
        metadata = dict(row)
        if "embedding" in row:
            metadata.setdefault("two_tower_source_name", "two_tower")
        metadata["two_tower_tokens"] = _semantic_tokens(row, token_fields)
        index[item_id] = metadata
    if index and all("embedding" in row for row in index.values()):
        return load_vector_index_artifact(path)
    return index


def semantic_candidates_for_user(
    user_sequence: dict[str, Any],
    semantic_index: dict[str, dict[str, Any]],
    config: dict,
) -> list[RecallCandidate]:
    if not config.get("semantic_enabled") or not semantic_index:
        return []
    if config.get("semantic_score_mode") == "idf_seed_aware":
        return _semantic_seed_aware_candidates_for_user(user_sequence, semantic_index, config)

    seen_items = set(user_sequence.get("recent_item_sequence", []))
    seed_items = list(dict.fromkeys(reversed(user_sequence.get("recent_positive_item_sequence", [])[-10:])))
    seed_tokens: set[str] = set()
    seed_categories: set[str] = set()
    for item_id in seed_items:
        record = semantic_index.get(item_id)
        if not record:
            continue
        seed_tokens.update(record.get("semantic_tokens", set()))
        seed_categories.update(_semantic_categories(record))
    if not seed_tokens and not seed_categories:
        return []

    limit = int(config.get("semantic_per_user", 20))
    min_overlap = int(config.get("semantic_min_overlap", 2))
    rows: list[RecallCandidate] = []
    for item_id, record in semantic_index.items():
        if item_id in seen_items:
            continue
        candidate_tokens = record.get("semantic_tokens", set())
        overlap = len(seed_tokens & candidate_tokens)
        if overlap < min_overlap:
            continue
        category_overlap = len(seed_categories & _semantic_categories(record))
        score = _semantic_score(overlap, seed_tokens, candidate_tokens, category_overlap, config)
        rows.append(
            RecallCandidate(
                item_id=item_id,
                source="semantic",
                score=score,
                category=str(record.get("main_category") or record.get("category", "")),
                metadata={k: v for k, v in record.items() if k != "semantic_tokens"},
            )
        )
    rows.sort(key=lambda item: (-item.score, item.item_id))
    return rows[:limit]


def semantic_title_category_expansion_candidates_for_user(
    user_sequence: dict[str, Any],
    semantic_index: dict[str, dict[str, Any]],
    config: dict,
) -> list[RecallCandidate]:
    source_config = config.get("semantic_title_category_expansion", {})
    if not isinstance(source_config, dict) or not source_config.get("enabled") or not semantic_index:
        return []

    seen_items = set(user_sequence.get("recent_item_sequence", []))
    seed_window = int(source_config.get("seed_window", 20))
    per_seed = int(source_config.get("per_seed", 10))
    limit = int(source_config.get("per_user", 20))
    min_title_overlap = int(source_config.get("min_title_overlap", 1))
    category_weight = float(source_config.get("category_weight", 2.0))
    weak_category_boost = float(source_config.get("weak_category_boost", 0.5))
    weak_categories = {str(item).lower() for item in source_config.get("weak_categories", [])}
    token_fields = [str(field) for field in source_config.get("text_fields", ["title_clean", "main_category", "categories_flat"])]
    max_bucket_candidates = int(source_config.get("max_bucket_candidates", config.get("semantic_max_bucket_candidates", 5000)))

    seed_items = _recent_unique_seeds(user_sequence.get("recent_positive_item_sequence", []), seed_window)
    context = _semantic_title_category_context(semantic_index, token_fields)
    item_tokens = context["item_tokens"]
    item_categories = context["item_categories"]
    inverted_index = context["inverted_index"]

    by_item: dict[str, RecallCandidate] = {}
    for seed_rank, seed_item in enumerate(seed_items):
        seed_tokens = item_tokens.get(seed_item, set())
        seed_categories = item_categories.get(seed_item, set())
        if not seed_tokens and not seed_categories:
            continue
        overlap_counts: Counter[str] = Counter()
        for token in seed_tokens:
            overlap_counts.update(inverted_index.get(token, set()))
        if max_bucket_candidates > 0 and len(overlap_counts) > max_bucket_candidates:
            overlap_counts = Counter(dict(overlap_counts.most_common(max_bucket_candidates)))
        scored: list[tuple[float, str, int, int, str]] = []
        for item_id, overlap in overlap_counts.items():
            if item_id in seen_items or item_id == seed_item or overlap < min_title_overlap:
                continue
            category_overlap = len(seed_categories & item_categories.get(item_id, set()))
            if not category_overlap and source_config.get("require_category_overlap", True):
                continue
            candidate_categories = item_categories.get(item_id, set())
            boost = weak_category_boost if candidate_categories & weak_categories else 0.0
            reason = "weak_category_boost" if boost else "category_path" if category_overlap else "title_sim"
            score = float(overlap) + float(category_overlap) * category_weight + boost
            scored.append((round(score, 6), item_id, overlap, category_overlap, reason))
        for score, item_id, overlap, category_overlap, reason in heapq.nsmallest(per_seed, scored, key=lambda item: (-item[0], item[1])):
            record = semantic_index[item_id]
            candidate = RecallCandidate(
                item_id=item_id,
                source="semantic_title_category_expansion",
                score=score,
                category=str(record.get("main_category") or record.get("category", "")),
                metadata={k: v for k, v in record.items() if k != "semantic_tokens"} | {
                    "reason": reason,
                    "seed_item_id": seed_item,
                    "source_score": score,
                    "source_rank": seed_rank,
                    "title_token_overlap": overlap,
                    "category_overlap": category_overlap,
                },
            )
            current = by_item.get(candidate.item_id)
            if current is None or candidate.score > current.score:
                by_item[candidate.item_id] = candidate

    rows = list(by_item.values())
    rows.sort(key=lambda item: (-item.score, item.item_id))
    return rows[:limit]


def two_tower_candidates_for_user(
    user_sequence: dict[str, Any],
    two_tower_index: dict[str, dict[str, Any]] | VectorSearchIndex,
    config: dict,
) -> list[RecallCandidate]:
    if not config.get("two_tower_enabled") or not two_tower_index:
        return []
    if isinstance(two_tower_index, VectorSearchIndex):
        return _two_tower_vector_candidates_for_user(user_sequence, two_tower_index, config)

    seen_items = set(user_sequence.get("recent_item_sequence", []))
    seed_window = int(config.get("two_tower_seed_window", 10))
    limit = int(config.get("two_tower_per_user", 20))
    min_overlap = int(config.get("two_tower_min_overlap", 1))
    recency_decay = float(config.get("two_tower_recency_decay", 0.85))
    token_fields = config.get("two_tower_text_fields")
    if token_fields is not None:
        token_fields = [str(field) for field in token_fields]

    seed_items = _recent_unique_seeds(user_sequence.get("recent_positive_item_sequence", []), seed_window)
    token_df = _two_tower_token_df(two_tower_index, token_fields)
    idf = {
        token: math.log((1.0 + len(two_tower_index)) / (1.0 + df)) + 1.0
        for token, df in token_df.items()
    }

    seed_vectors: list[tuple[str, int, dict[str, float], float]] = []
    for seed_rank, seed_item in enumerate(seed_items):
        seed_record = two_tower_index.get(seed_item)
        if not seed_record:
            continue
        vector = _two_tower_vector(_record_two_tower_tokens(seed_record, token_fields), idf)
        norm = _vector_norm(vector)
        if norm:
            seed_vectors.append((seed_item, seed_rank, vector, norm))
    if not seed_vectors:
        return []

    by_item: dict[str, RecallCandidate] = {}
    for item_id, record in two_tower_index.items():
        if item_id in seen_items:
            continue
        candidate_tokens = _record_two_tower_tokens(record, token_fields)
        candidate_vector = _two_tower_vector(candidate_tokens, idf)
        candidate_norm = _vector_norm(candidate_vector)
        if not candidate_norm:
            continue
        best_score = 0.0
        best_seed = ""
        best_seed_rank = 0
        best_overlap = 0
        for seed_item, seed_rank, seed_vector, seed_norm in seed_vectors:
            overlap = len(seed_vector.keys() & candidate_vector.keys())
            if overlap < min_overlap:
                continue
            score = _cosine_score(seed_vector, seed_norm, candidate_vector, candidate_norm) * (recency_decay**seed_rank)
            if score > best_score:
                best_score = score
                best_seed = seed_item
                best_seed_rank = seed_rank
                best_overlap = overlap
        if best_score <= 0.0:
            continue
        by_item[item_id] = RecallCandidate(
            item_id=item_id,
            source="two_tower",
            score=round(best_score, 6),
            category=str(record.get("main_category") or record.get("category", "")),
            metadata={k: v for k, v in record.items() if k != "two_tower_tokens"}
            | {"two_tower_seed_item": best_seed, "two_tower_seed_rank": best_seed_rank, "two_tower_overlap": best_overlap},
        )

    rows = list(by_item.values())
    rows.sort(key=lambda item: (-item.score, item.item_id))
    return rows[:limit]


def _two_tower_vector_candidates_for_user(
    user_sequence: dict[str, Any],
    two_tower_index: VectorSearchIndex,
    config: dict,
) -> list[RecallCandidate]:
    limit = int(config.get("two_tower_per_user", 20))
    seed_window = int(config.get("two_tower_seed_window", 10))
    recency_decay = float(config.get("two_tower_recency_decay", 0.85))
    query = build_two_tower_query_for_user(
        user_sequence,
        two_tower_index,
        seed_window=seed_window,
        recency_decay=recency_decay,
        artifact_user_embedding_first=bool(config.get("two_tower_artifact_user_embedding_first", True)),
        project_seed_average=bool(config.get("two_tower_project_seed_average", True)),
    )
    if not query.has_query:
        return []
    rows = []
    for result in two_tower_index.search(query.query_vector, limit=limit, excluded_items=query.excluded_items):
        metadata = dict(result.metadata)
        metadata.update(two_tower_index.model_metadata)
        metadata.setdefault("two_tower_source_name", two_tower_index.source_name)
        metadata.setdefault("two_tower_score_mode", "vector_dot")
        metadata.setdefault("two_tower_query_source", query.query_source)
        metadata.setdefault("two_tower_seed_item_count", query.seed_item_count)
        metadata.setdefault("two_tower_seed_vector_count", query.seed_vector_count)
        rows.append(
            RecallCandidate(
                item_id=result.item_id,
                source="two_tower",
                score=result.score,
                category=str(metadata.get("main_category") or metadata.get("category", "")),
                metadata=metadata,
            )
        )
    return rows


def _apply_user_tower_projection(query_vector: list[float], index: VectorSearchIndex) -> list[float]:
    return apply_user_tower_projection(query_vector, index)


def merge_for_user(
    user_sequence: dict[str, Any],
    popular: list[RecallCandidate],
    itemcf_weak: dict[str, list[RecallCandidate]],
    itemcf_strong: dict[str, list[RecallCandidate]],
    category_top: dict[str, list[RecallCandidate]],
    item_category: dict[str, str],
    config: dict,
    semantic_index: dict[str, dict[str, Any]] | None = None,
    two_tower_index: dict[str, dict[str, Any]] | VectorIndex | None = None,
    item_graph: dict[str, list[RecallCandidate]] | None = None,
    two_tower_seed: dict[str, list[RecallCandidate]] | None = None,
    graph_walk_seed: dict[str, list[RecallCandidate]] | None = None,
    usercf_recall: dict[str, list[RecallCandidate]] | None = None,
    swing_recall: dict[str, list[RecallCandidate]] | None = None,
    two_tower_recall: dict[str, list[RecallCandidate]] | None = None,
    pregenerated_recall: dict[str, list[RecallCandidate]] | None = None,
) -> tuple[list[MergedCandidate], bool]:
    seen_items = set(user_sequence.get("recent_item_sequence", []))
    user_id = str(user_sequence.get("user_id", ""))
    raw: list[RecallCandidate] = []
    raw.extend(
        _itemcf_candidates_for_user(
            user_sequence,
            itemcf_weak,
            sequence_key="recent_positive_item_sequence",
            source="itemcf_weak",
            config=config,
            window_key="itemcf_recent_positive_window",
            per_seed_key="itemcf_weak_per_seed",
        )
    )
    raw.extend(
        _itemcf_candidates_for_user(
            user_sequence,
            itemcf_strong,
            sequence_key="recent_strong_positive_item_sequence",
            source="itemcf_strong",
            config=config,
            window_key="itemcf_recent_strong_window",
            per_seed_key="itemcf_strong_per_seed",
        )
    )

    raw.extend(_category_candidates_for_user(user_sequence, category_top, item_category, config))
    raw.extend(category_long_tail_candidates_for_user(user_sequence, item_category, popular, config))
    raw.extend(semantic_title_category_expansion_candidates_for_user(user_sequence, semantic_index or {}, config))
    raw.extend(semantic_candidates_for_user(user_sequence, semantic_index or {}, config))
    raw.extend(metadata_neighbor_candidates_for_user(user_sequence, semantic_index or {}, config))
    raw.extend((pregenerated_recall or {}).get(user_id, []))
    raw.extend((two_tower_recall or {}).get(user_id, []))
    if not two_tower_recall:
        raw.extend(two_tower_candidates_for_user(user_sequence, two_tower_index or {}, config))
    raw.extend(item_graph_candidates_for_user(user_sequence, item_graph or {}, config))
    raw.extend(two_tower_seed_candidates_for_user(user_sequence, two_tower_seed or {}, config))
    raw.extend(graph_walk_seed_candidates_for_user(user_sequence, graph_walk_seed or {}, config))
    raw.extend(swing_candidates_for_user(user_sequence, swing_recall or {}, config))
    raw.extend(usercf_candidates_for_user(user_sequence, usercf_recall or {}, config))

    fallback_used = not raw
    popular_fallback = _popular_candidates_for_pool(popular, raw, config)
    raw.extend(popular_fallback)
    merged = merge_candidates(raw, seen_items=seen_items)
    if not merged and popular_fallback:
        recovered = merge_candidates(_recovery_popular_candidates(popular_fallback), seen_items=set())
        merged = _limit_candidate_pool(recovered, _recovery_pool_size(config), config)
        fallback_used = True
    has_non_popular_candidate = any(
        source != "popular" for candidate in merged for source in candidate.sources
    )
    fallback_used = fallback_used or not has_non_popular_candidate
    return _limit_candidate_pool(merged, int(config.get("candidate_pool_size", 50)), config), fallback_used


def _recovery_popular_candidates(candidates: list[RecallCandidate]) -> list[RecallCandidate]:
    return [
        RecallCandidate(
            item_id=candidate.item_id,
            source=candidate.source,
            score=candidate.score,
            category=candidate.category,
            metadata=dict(candidate.metadata) | {
                "_internal_fallback_reason": "empty_pool_seen_filtered_popular_recovery",
                "_internal_fallback_source": "popular",
            },
        )
        for candidate in candidates
    ]


def _recovery_pool_size(config: dict) -> int:
    return min(
        int(config.get("candidate_pool_size", 50)),
        int(config.get("popular_fallback_count", 50)),
        int(config.get("top_k", config.get("candidate_pool_size", 50))),
    )


def merge_candidates(candidates: list[RecallCandidate], seen_items: set[str] | None = None) -> list[MergedCandidate]:
    seen_items = seen_items or set()
    merged: dict[str, MergedCandidate] = {}
    for candidate in candidates:
        if not candidate.item_id or candidate.item_id in seen_items:
            continue
        current = merged.get(candidate.item_id)
        if current is None:
            current = MergedCandidate(
                item_id=candidate.item_id,
                sources=[],
                source_scores={},
                category=candidate.category or str(candidate.metadata.get("category", "")),
                metadata=dict(candidate.metadata),
            )
            merged[candidate.item_id] = current
        if candidate.source not in current.sources:
            current.sources.append(candidate.source)
        current.source_scores[candidate.source] = max(
            float(current.source_scores.get(candidate.source, 0.0)), candidate.score
        )
        if not current.category:
            current.category = candidate.category or str(candidate.metadata.get("category", ""))
        current.metadata.update({k: v for k, v in candidate.metadata.items() if k not in current.metadata})
    rows = list(merged.values())
    rows.sort(key=lambda item: (-sum(item.source_scores.values()), item.item_id))
    return rows


def _limit_candidate_pool(candidates: list[MergedCandidate], pool_size: int, config: dict) -> list[MergedCandidate]:
    if config.get("candidate_pool_strategy") == "balanced_source_budget":
        return _balanced_source_budget_pool(candidates, pool_size, config)

    minimums = config.get("candidate_source_minimums", {})
    maximums = {str(k): int(v) for k, v in config.get("candidate_source_maximums", {}).items()}
    if not minimums and not maximums:
        return candidates[:pool_size]
    selected: dict[str, MergedCandidate] = {}
    group_counts: Counter[str] = Counter()
    tracked_groups = dict.fromkeys(maximums.keys(), 0)
    for group, minimum in minimums.items():
        sources = _candidate_group_sources(group)
        eligible = [candidate for candidate in candidates if any(source in candidate.sources for source in sources)]
        for candidate in eligible:
            if group_counts[group] >= int(minimum):
                break
            if _would_exceed_maximum(candidate, group_counts, maximums):
                continue
            selected[candidate.item_id] = candidate
            _increment_group_counts(group_counts, candidate, tracked_groups)
    for candidate in candidates:
        if len(selected) >= pool_size:
            break
        if candidate.item_id in selected or _would_exceed_maximum(candidate, group_counts, maximums):
            continue
        selected[candidate.item_id] = candidate
        _increment_group_counts(group_counts, candidate, tracked_groups)
    rows = list(selected.values())[:pool_size]
    rows.sort(key=lambda item: (-sum(item.source_scores.values()), item.item_id))
    return rows


def _balanced_source_budget_pool(candidates: list[MergedCandidate], pool_size: int, config: dict) -> list[MergedCandidate]:
    minimums = {str(k): int(v) for k, v in config.get("candidate_source_minimums", {}).items()}
    maximums = {str(k): int(v) for k, v in config.get("candidate_source_maximums", {}).items()}
    fill_order = [str(item) for item in config.get("candidate_fill_order", [])]
    if not fill_order:
        fill_order = list(dict.fromkeys([*minimums.keys(), *maximums.keys(), "itemcf", "semantic", "category", "popular"]))
    tracked_groups = dict.fromkeys([*minimums.keys(), *maximums.keys()], 0)

    ranked = sorted(candidates, key=lambda item: _candidate_sort_key(item, config))
    selected: dict[str, MergedCandidate] = {}
    group_counts: Counter[str] = Counter()

    for group, minimum in minimums.items():
        for candidate in ranked:
            if len(selected) >= pool_size or group_counts[group] >= minimum:
                break
            if candidate.item_id in selected or not _candidate_in_group(candidate, group):
                continue
            if _would_exceed_maximum(candidate, group_counts, maximums):
                continue
            selected[candidate.item_id] = candidate
            _increment_group_counts(group_counts, candidate, tracked_groups)

    while len(selected) < pool_size:
        added = False
        for group in fill_order:
            for candidate in ranked:
                if len(selected) >= pool_size:
                    break
                if candidate.item_id in selected or not _candidate_in_group(candidate, group):
                    continue
                if _would_exceed_maximum(candidate, group_counts, maximums):
                    continue
                selected[candidate.item_id] = candidate
                _increment_group_counts(group_counts, candidate, tracked_groups)
                added = True
                break
        if not added:
            break

    for candidate in ranked:
        if len(selected) >= pool_size:
            break
        if candidate.item_id in selected or _would_exceed_maximum(candidate, group_counts, maximums):
            continue
        selected[candidate.item_id] = candidate
        _increment_group_counts(group_counts, candidate, tracked_groups)

    rows = list(selected.values())[:pool_size]
    rows.sort(key=lambda item: _candidate_sort_key(item, config))
    return rows


def _candidate_group_sources(group: str) -> set[str]:
    if group == "itemcf":
        return {"itemcf_weak", "itemcf_strong"}
    return {group}


def co_visit_transition_candidates_for_user(
    user_sequence: dict[str, Any],
    transition_graph: dict[str, list[RecallCandidate]],
    config: dict,
    *,
    exclude_items: set[str] | None = None,
) -> list[RecallCandidate]:
    if not transition_graph:
        return []
    seed_window = int(config.get("co_visit_seed_window", config.get("co_visit_underfill_seed_window", 30)))
    per_seed = int(config.get("co_visit_per_seed", config.get("co_visit_underfill_per_seed", 50)))
    limit = int(config.get("co_visit_per_user", config.get("co_visit_underfill_per_user", 100)))
    seed_values = user_sequence.get("recent_positive_item_sequence", []) or user_sequence.get("recent_item_sequence", [])
    seeds = _recent_unique_seeds(seed_values, seed_window)
    seen_items = {str(item_id) for item_id in user_sequence.get("recent_item_sequence", []) if item_id}
    if exclude_items:
        seen_items.update(exclude_items)
    by_item: dict[str, RecallCandidate] = {}
    for seed_rank, seed in enumerate(seeds, start=1):
        recency_weight = 1.0 / math.sqrt(seed_rank)
        for source_rank, candidate in enumerate(transition_graph.get(seed, [])[:per_seed], start=1):
            if candidate.item_id in seen_items:
                continue
            score = float(candidate.score) * recency_weight
            metadata = dict(candidate.metadata)
            metadata.update({
                "reason": "train_interaction_sequence_transition",
                "seed_item_id": seed,
                "source_rank": source_rank,
                "sequence_transition_seed_rank": seed_rank,
                "sequence_transition_recency_weighted_score": score,
                "sequence_transition_index_mode": "train_only_full_item_transition_graph",
            })
            row = RecallCandidate(
                item_id=candidate.item_id,
                source="co_visit_fallback_repair",
                score=score,
                category=candidate.category or str(metadata.get("category") or metadata.get("main_category") or ""),
                metadata=metadata,
            )
            current = by_item.get(row.item_id)
            if current is None or row.score > current.score:
                by_item[row.item_id] = row
    rows = list(by_item.values())
    rows.sort(key=lambda item: (-item.score, item.item_id))
    return rows[:limit]



def item_graph_candidates_for_user(
    user_sequence: dict[str, Any],
    item_graph: dict[str, list[RecallCandidate]],
    config: dict,
) -> list[RecallCandidate]:
    if not config.get("item_graph_enabled") or not item_graph:
        return []
    positive_seeds = _recent_unique_seeds(
        user_sequence.get("recent_positive_item_sequence", []),
        int(config.get("item_graph_recent_positive_window", config.get("item_graph_seed_window", 10))),
    )
    strong_seeds = _recent_unique_seeds(
        user_sequence.get("recent_strong_positive_item_sequence", []),
        int(config.get("item_graph_recent_strong_window", config.get("item_graph_seed_window", 10))),
    )
    seeds = list(dict.fromkeys([*strong_seeds, *positive_seeds]))
    seen_items = set(user_sequence.get("recent_item_sequence", []))
    per_seed = int(config.get("item_graph_per_seed", 20))
    rows: list[RecallCandidate] = []
    for seed_rank, seed in enumerate(seeds):
        for candidate in item_graph.get(seed, [])[:per_seed]:
            if candidate.item_id in seen_items:
                continue
            metadata = dict(candidate.metadata)
            metadata.update({"item_graph_seed_item": seed, "item_graph_seed_rank": seed_rank, "item_graph_score": candidate.score})
            rows.append(
                RecallCandidate(
                    item_id=candidate.item_id,
                    source="item_graph",
                    score=candidate.score,
                    category=candidate.category,
                    metadata=metadata,
                )
            )
    limit = int(config.get("item_graph_per_user", len(rows) or per_seed * max(1, len(seeds))))
    rows.sort(key=lambda item: (-item.score, item.item_id))
    return rows[:limit]


def two_tower_seed_candidates_for_user(
    user_sequence: dict[str, Any],
    two_tower_seed: dict[str, list[RecallCandidate]],
    config: dict,
) -> list[RecallCandidate]:
    if not config.get("two_tower_seed_enabled") or not two_tower_seed:
        return []
    positive_seeds = _recent_unique_seeds(
        user_sequence.get("recent_positive_item_sequence", []),
        int(config.get("two_tower_seed_recent_positive_window", config.get("two_tower_seed_window", 10))),
    )
    strong_seeds = _recent_unique_seeds(
        user_sequence.get("recent_strong_positive_item_sequence", []),
        int(config.get("two_tower_seed_recent_strong_window", config.get("two_tower_seed_window", 10))),
    )
    seeds = list(dict.fromkeys([*strong_seeds, *positive_seeds]))
    seen_items = set(user_sequence.get("recent_item_sequence", []))
    per_seed = int(config.get("two_tower_seed_per_seed", 20))
    limit = int(config.get("two_tower_seed_per_user", per_seed * max(1, len(seeds))))
    recency_decay = float(config.get("two_tower_seed_recency_decay", 1.0))
    score_floor = float(config.get("two_tower_seed_score_floor", 0.0))
    by_item: dict[str, RecallCandidate] = {}
    for seed_rank, seed in enumerate(seeds):
        decay = recency_decay**seed_rank
        for candidate in two_tower_seed.get(seed, [])[:per_seed]:
            if candidate.item_id in seen_items:
                continue
            score = candidate.score * decay
            if score < score_floor:
                continue
            metadata = dict(candidate.metadata)
            metadata.update({
                "two_tower_seed_item": seed,
                "two_tower_seed_rank": seed_rank,
                "two_tower_seed_score": candidate.score,
                "two_tower_seed_decayed_score": round(score, 6),
            })
            row = RecallCandidate(
                item_id=candidate.item_id,
                source="two_tower_seed",
                score=round(score, 6),
                category=candidate.category,
                metadata=metadata,
            )
            current = by_item.get(row.item_id)
            if current is None or row.score > current.score:
                by_item[row.item_id] = row
    rows = list(by_item.values())
    rows.sort(key=lambda item: (-item.score, item.item_id))
    return rows[:limit]


def usercf_candidates_for_user(
    user_sequence: dict[str, Any],
    usercf_recall: dict[str, list[RecallCandidate]],
    config: dict,
) -> list[RecallCandidate]:
    if not config.get("usercf_enabled") or not usercf_recall:
        return []
    user_id = str(user_sequence.get("user_id") or "")
    seen_items = set(user_sequence.get("recent_item_sequence", []))
    limit = int(config.get("usercf_per_user", len(usercf_recall.get(user_id, []))))
    rows = [candidate for candidate in usercf_recall.get(user_id, []) if candidate.item_id not in seen_items]
    rows.sort(key=lambda item: (-item.score, item.item_id))
    return rows[:limit]


def swing_candidates_for_user(
    user_sequence: dict[str, Any],
    swing_recall: dict[str, list[RecallCandidate]],
    config: dict,
) -> list[RecallCandidate]:
    if not config.get("swing_enabled") or not swing_recall:
        return []
    positive_seeds = _recent_unique_seeds(
        user_sequence.get("recent_positive_item_sequence", []),
        int(config.get("swing_recent_positive_window", config.get("swing_seed_window", 10))),
    )
    strong_seeds = _recent_unique_seeds(
        user_sequence.get("recent_strong_positive_item_sequence", []),
        int(config.get("swing_recent_strong_window", config.get("swing_seed_window", 10))),
    )
    seeds = list(dict.fromkeys([*strong_seeds, *positive_seeds]))
    seen_items = set(user_sequence.get("recent_item_sequence", []))
    per_seed = int(config.get("swing_per_seed", 20))
    limit = int(config.get("swing_per_user", per_seed * max(1, len(seeds))))
    by_item: dict[str, RecallCandidate] = {}
    for seed_rank, seed in enumerate(seeds):
        for candidate in swing_recall.get(seed, [])[:per_seed]:
            if candidate.item_id in seen_items:
                continue
            metadata = dict(candidate.metadata)
            metadata.update({"swing_seed_item": seed, "swing_seed_rank": seed_rank, "swing_score": candidate.score})
            row = RecallCandidate(
                item_id=candidate.item_id,
                source="swing_recall",
                score=candidate.score,
                category=candidate.category,
                metadata=metadata,
            )
            current = by_item.get(row.item_id)
            if current is None or row.score > current.score:
                by_item[row.item_id] = row
    rows = list(by_item.values())
    rows.sort(key=lambda item: (-item.score, item.item_id))
    return rows[:limit]


def graph_walk_seed_candidates_for_user(
    user_sequence: dict[str, Any],
    graph_walk_seed: dict[str, list[RecallCandidate]],
    config: dict,
) -> list[RecallCandidate]:
    if not config.get("graph_walk_seed_enabled") or not graph_walk_seed:
        return []
    positive_seeds = _recent_unique_seeds(
        user_sequence.get("recent_positive_item_sequence", []),
        int(config.get("graph_walk_seed_recent_positive_window", config.get("graph_walk_seed_window", 10))),
    )
    strong_seeds = _recent_unique_seeds(
        user_sequence.get("recent_strong_positive_item_sequence", []),
        int(config.get("graph_walk_seed_recent_strong_window", config.get("graph_walk_seed_window", 10))),
    )
    seeds = list(dict.fromkeys([*strong_seeds, *positive_seeds]))
    seen_items = set(user_sequence.get("recent_item_sequence", []))
    per_seed = int(config.get("graph_walk_seed_per_seed", 20))
    limit = int(config.get("graph_walk_seed_per_user", per_seed * max(1, len(seeds))))
    recency_decay = float(config.get("graph_walk_seed_recency_decay", 1.0))
    score_floor = float(config.get("graph_walk_seed_score_floor", 0.0))
    by_item: dict[str, RecallCandidate] = {}
    for seed_rank, seed in enumerate(seeds):
        decay = recency_decay**seed_rank
        for candidate in graph_walk_seed.get(seed, [])[:per_seed]:
            if candidate.source != "graph_walk_seed":
                raise ValueError(f"invalid graph_walk_seed candidate source: {candidate.source!r}")
            if candidate.item_id in seen_items:
                continue
            score = candidate.score * decay
            if score < score_floor:
                continue
            metadata = dict(candidate.metadata)
            metadata.update({
                "graph_walk_seed_item": seed,
                "graph_walk_seed_rank": seed_rank,
                "graph_walk_seed_score": candidate.score,
                "graph_walk_seed_decayed_score": round(score, 6),
            })
            row = RecallCandidate(
                item_id=candidate.item_id,
                source="graph_walk_seed",
                score=round(score, 6),
                category=candidate.category,
                metadata=metadata,
            )
            current = by_item.get(row.item_id)
            if current is None or row.score > current.score:
                by_item[row.item_id] = row
    rows = list(by_item.values())
    rows.sort(key=lambda item: (-item.score, item.item_id))
    return rows[:limit]



def _itemcf_candidates_for_user(
    user_sequence: dict[str, Any],
    itemcf: dict[str, list[RecallCandidate]],
    sequence_key: str,
    source: str,
    config: dict,
    window_key: str,
    per_seed_key: str,
) -> list[RecallCandidate]:
    window = int(config.get(window_key, 10))
    per_seed = int(config.get(per_seed_key, config.get("itemcf_per_seed", 20)))
    seeds = _recent_unique_seeds(user_sequence.get(sequence_key, []), window)
    return _extend_itemcf_from_seeds(
        seeds,
        itemcf,
        source=source,
        per_seed=per_seed,
        decay_enabled=bool(config.get("itemcf_seed_decay_enabled", False)),
        decay_base=float(config.get("itemcf_seed_decay_base", 0.85)),
    )


def _recent_unique_seeds(items: list[str], window: int) -> list[str]:
    return list(dict.fromkeys(reversed(items[-window:])))


def _extend_itemcf_from_seeds(
    seeds: list[str],
    itemcf: dict[str, list[RecallCandidate]],
    source: str,
    per_seed: int,
    decay_enabled: bool,
    decay_base: float,
) -> list[RecallCandidate]:
    rows: list[RecallCandidate] = []
    for seed_rank, seed in enumerate(seeds):
        decay = decay_base**seed_rank if decay_enabled else 1.0
        for candidate in itemcf.get(seed, [])[:per_seed]:
            if decay == 1.0 and candidate.source == source:
                rows.append(candidate)
                continue
            metadata = dict(candidate.metadata)
            metadata.setdefault("seed_item", seed)
            rows.append(
                RecallCandidate(
                    item_id=candidate.item_id,
                    source=source,
                    score=candidate.score * decay,
                    category=candidate.category,
                    metadata=metadata,
                )
            )
    return rows


def _category_candidates_for_user(
    user_sequence: dict[str, Any],
    category_top: dict[str, list[RecallCandidate]],
    item_category: dict[str, str],
    config: dict,
) -> list[RecallCandidate]:
    use_new_budget = any(
        key in config
        for key in ("category_recent_positive_window", "category_per_bucket", "category_max_total_per_user")
    )
    if not use_new_budget:
        rows: list[RecallCandidate] = []
        buckets = _category_buckets(user_sequence, item_category)
        category_limit = int(config.get("category_per_user", 20))
        for bucket in buckets:
            rows.extend(category_top.get(bucket, [])[:category_limit])
        return rows

    window = int(config.get("category_recent_positive_window", 10))
    per_bucket = int(config.get("category_per_bucket", config.get("category_per_user", 20)))
    max_total = int(config.get("category_max_total_per_user", per_bucket * max(1, window)))
    rows = []
    for bucket in _category_buckets(user_sequence, item_category, window=window):
        rows.extend(category_top.get(bucket, [])[:per_bucket])
        if len(rows) >= max_total:
            return rows[:max_total]
    return rows[:max_total]


def category_long_tail_candidates_for_user(
    user_sequence: dict[str, Any],
    item_category: dict[str, str],
    popular: list[RecallCandidate],
    config: dict,
) -> list[RecallCandidate]:
    if not config.get("category_long_tail_enabled"):
        return []
    popular_rank = {candidate.item_id: rank for rank, candidate in enumerate(popular, start=1)}
    seen_items = set(user_sequence.get("recent_item_sequence", []))
    long_tail_start_rank = int(config.get("category_long_tail_start_rank", len(popular) + 1))
    per_category = int(config.get("category_long_tail_per_category", config.get("category_long_tail_per_user", 20)))
    max_total = int(config.get("category_long_tail_per_user", per_category))
    categories = _seed_categories(user_sequence, item_category, int(config.get("category_long_tail_seed_window", 10)))
    by_item: dict[str, RecallCandidate] = {}
    for category_rank, category in enumerate(categories):
        category_rows = []
        for item_id, item_category_value in item_category.items():
            if item_id in seen_items or item_category_value != category:
                continue
            rank = popular_rank.get(item_id)
            if rank is not None and rank < long_tail_start_rank:
                continue
            score = 1.0 / float(1 + category_rank + (rank or long_tail_start_rank))
            category_rows.append((score, item_id, rank))
        category_rows.sort(key=lambda item: (-item[0], item[1]))
        for source_rank, (score, item_id, rank) in enumerate(category_rows[:per_category], start=1):
            by_item[item_id] = RecallCandidate(
                item_id=item_id,
                source="category_long_tail_recall",
                score=round(score, 6),
                category=category,
                metadata={
                    "reason": "category_long_tail",
                    "seed_category": category,
                    "source_rank": source_rank,
                    "popular_rank": rank,
                    "popularity_bucket": "not_in_popular_topn" if rank is None else "beyond_long_tail_start",
                },
            )
    rows = list(by_item.values())
    rows.sort(key=lambda item: (-item.score, item.item_id))
    return rows[:max_total]


def metadata_neighbor_candidates_for_user(
    user_sequence: dict[str, Any],
    metadata_index: dict[str, dict[str, Any]],
    config: dict,
) -> list[RecallCandidate]:
    if not config.get("metadata_neighbor_enabled") or not metadata_index:
        return []
    seen_items = set(user_sequence.get("recent_item_sequence", []))
    seed_items = _recent_unique_seeds(user_sequence.get("recent_positive_item_sequence", []), int(config.get("metadata_neighbor_seed_window", 10)))
    per_seed = int(config.get("metadata_neighbor_per_seed", 20))
    max_total = int(config.get("metadata_neighbor_per_user", per_seed * max(1, len(seed_items))))
    min_overlap = int(config.get("metadata_neighbor_min_token_overlap", 1))
    category_weight = float(config.get("metadata_neighbor_category_weight", 2.0))
    bucket_index = _metadata_neighbor_bucket_index(metadata_index, config)
    by_item: dict[str, RecallCandidate] = {}
    for seed_rank, seed_item in enumerate(seed_items):
        seed_record = metadata_index.get(seed_item)
        if not seed_record:
            continue
        seed_tokens = _metadata_neighbor_tokens(seed_record, config)
        seed_categories = _semantic_categories(seed_record)
        if not seed_tokens and not seed_categories:
            continue
        seed_rows = []
        candidate_ids = _metadata_neighbor_bucket_candidates(bucket_index, seed_tokens, seed_categories)
        max_bucket_candidates = int(config.get("metadata_neighbor_max_bucket_candidates", 5000))
        if max_bucket_candidates > 0:
            candidate_ids = set(heapq.nsmallest(max_bucket_candidates, candidate_ids))
        for item_id in candidate_ids:
            if item_id in seen_items or item_id == seed_item:
                continue
            record = metadata_index[item_id]
            candidate_tokens = _metadata_neighbor_tokens(record, config)
            candidate_categories = _semantic_categories(record)
            token_overlap = len(seed_tokens & candidate_tokens)
            category_overlap = len(seed_categories & candidate_categories)
            if token_overlap < min_overlap and category_overlap == 0:
                continue
            score = float(token_overlap) + float(category_overlap) * category_weight
            seed_rows.append((round(score, 6), item_id, token_overlap, category_overlap))
        seed_rows.sort(key=lambda item: (-item[0], item[1]))
        for source_rank, (score, item_id, token_overlap, category_overlap) in enumerate(seed_rows[:per_seed], start=1):
            record = metadata_index[item_id]
            metadata = {k: v for k, v in record.items() if k not in {"semantic_tokens", "two_tower_tokens"}}
            metadata.update({
                "reason": "metadata_neighbor",
                "seed_item_id": seed_item,
                "source_score": score,
                "source_rank": source_rank,
                "metadata_neighbor_seed_rank": seed_rank,
                "metadata_neighbor_token_overlap": token_overlap,
                "metadata_neighbor_category_overlap": category_overlap,
                "metadata_neighbor_index_mode": "bucketed_train_visible_metadata",
            })
            candidate = RecallCandidate(
                item_id=item_id,
                source="metadata_neighbor_recall",
                score=score,
                category=str(record.get("main_category") or record.get("category", "")),
                metadata=metadata,
            )
            current = by_item.get(item_id)
            if current is None or candidate.score > current.score:
                by_item[item_id] = candidate
    rows = list(by_item.values())
    rows.sort(key=lambda item: (-item.score, item.item_id))
    return rows[:max_total]


def _popular_candidates_for_pool(
    popular: list[RecallCandidate],
    raw_non_popular: list[RecallCandidate],
    config: dict,
) -> list[RecallCandidate]:
    fallback_count = int(config.get("popular_fallback_count", 50))
    if config.get("popular_fill_policy") != "capped_remainder" or not raw_non_popular:
        return popular[:fallback_count]

    pool_size = int(config.get("candidate_pool_size", 50))
    max_in_pool = int(config.get("popular_max_in_pool", fallback_count))
    remainder = max(pool_size - len({candidate.item_id for candidate in raw_non_popular if candidate.item_id}), 0)
    return popular[: min(max_in_pool, remainder)]


def _semantic_seed_aware_candidates_for_user(
    user_sequence: dict[str, Any],
    semantic_index: dict[str, dict[str, Any]],
    config: dict,
) -> list[RecallCandidate]:
    seen_items = set(user_sequence.get("recent_item_sequence", []))
    seed_window = int(config.get("semantic_seed_window", 10))
    per_seed = int(config.get("semantic_per_seed", config.get("semantic_per_user", 20)))
    limit = int(config.get("semantic_per_user", 20))
    min_overlap = int(config.get("semantic_min_overlap", 1))
    category_weight = float(config.get("semantic_category_weight", 2.0))
    token_fields = config.get("semantic_text_fields")
    if token_fields is not None:
        token_fields = [str(field) for field in token_fields]

    seed_items = _recent_unique_seeds(user_sequence.get("recent_positive_item_sequence", []), seed_window)
    context = _semantic_seed_aware_context(semantic_index, token_fields, float(config.get("semantic_max_df_ratio", 1.0)))
    allowed_tokens = context["allowed_tokens"]
    idf = context["idf"]
    item_tokens = context["item_tokens"]
    item_categories = context["item_categories"]
    inverted_index = context["inverted_index"]

    by_item: dict[str, RecallCandidate] = {}
    for seed_rank, seed_item in enumerate(seed_items):
        seed_record = semantic_index.get(seed_item)
        if not seed_record:
            continue
        seed_tokens = item_tokens.get(seed_item, set()) & allowed_tokens
        seed_categories = item_categories.get(seed_item, set())
        if not seed_tokens and not seed_categories:
            continue
        candidate_overlap_counts: Counter[str] = Counter()
        for token in seed_tokens:
            candidate_overlap_counts.update(inverted_index.get(token, set()))
        seed_scores: list[tuple[float, str]] = []
        for item_id, overlap_count in candidate_overlap_counts.items():
            if overlap_count < min_overlap or item_id in seen_items or item_id == seed_item:
                continue
            overlap_tokens = seed_tokens & item_tokens.get(item_id, set())
            if len(overlap_tokens) < min_overlap:
                continue
            category_overlap = len(seed_categories & item_categories.get(item_id, set()))
            token_score = sum(idf.get(token, 0.0) for token in overlap_tokens) / len(overlap_tokens)
            score = token_score + category_overlap * category_weight
            seed_scores.append((round(score, 6), item_id))
        top_seed_scores = heapq.nsmallest(per_seed, seed_scores, key=lambda item: (-item[0], item[1]))
        for score, item_id in top_seed_scores:
            record = semantic_index[item_id]
            candidate = RecallCandidate(
                item_id=item_id,
                source="semantic",
                score=score,
                category=str(record.get("main_category") or record.get("category", "")),
                metadata={k: v for k, v in record.items() if k != "semantic_tokens"} | {"semantic_seed_item": seed_item, "semantic_seed_rank": seed_rank},
            )
            current = by_item.get(candidate.item_id)
            if current is None or candidate.score > current.score:
                by_item[candidate.item_id] = candidate

    rows = list(by_item.values())
    rows.sort(key=lambda item: (-item.score, item.item_id))
    return rows[:limit]


def _looks_like_vector_artifact(path: str | Path) -> bool:
    artifact_path = Path(path)
    if artifact_path.suffix == ".json":
        return True
    return artifact_path.name.endswith("recall_index.jsonl")


def _semantic_token_df(
    semantic_index: dict[str, dict[str, Any]],
    token_fields: list[str] | None,
) -> Counter[str]:
    token_df: Counter[str] = Counter()
    for record in semantic_index.values():
        token_df.update(_record_semantic_tokens(record, token_fields))
    return token_df


def _semantic_title_category_context(semantic_index: dict[str, dict[str, Any]], token_fields: list[str]) -> dict[str, Any]:
    normalized_fields = tuple(token_fields)
    cache_key = (id(semantic_index), normalized_fields, len(semantic_index))
    context = _SEMANTIC_TITLE_CATEGORY_CONTEXT_CACHE.get(cache_key)
    if context:
        return context
    item_tokens = {item_id: _semantic_tokens(record, token_fields) for item_id, record in semantic_index.items()}
    item_categories = {item_id: _semantic_categories(record) for item_id, record in semantic_index.items()}
    inverted_index: dict[str, set[str]] = defaultdict(set)
    for item_id, tokens in item_tokens.items():
        for token in tokens:
            inverted_index[token].add(item_id)
    context = {
        "item_tokens": item_tokens,
        "item_categories": item_categories,
        "inverted_index": inverted_index,
    }
    if len(_SEMANTIC_TITLE_CATEGORY_CONTEXT_CACHE) >= _SEMANTIC_TITLE_CATEGORY_CONTEXT_CACHE_LIMIT:
        _SEMANTIC_TITLE_CATEGORY_CONTEXT_CACHE.pop(next(iter(_SEMANTIC_TITLE_CATEGORY_CONTEXT_CACHE)))
    _SEMANTIC_TITLE_CATEGORY_CONTEXT_CACHE[cache_key] = context
    return context


def _semantic_seed_aware_context(
    semantic_index: dict[str, dict[str, Any]],
    token_fields: list[str] | None,
    max_df_ratio: float,
) -> dict[str, Any]:
    normalized_fields = tuple(token_fields or ())
    cache_key = (id(semantic_index), normalized_fields, max_df_ratio, len(semantic_index))
    context = _SEMANTIC_SEED_CONTEXT_CACHE.get(cache_key)
    if context:
        return context

    item_tokens = {
        item_id: _record_semantic_tokens(record, token_fields)
        for item_id, record in semantic_index.items()
    }
    item_categories = {
        item_id: _semantic_categories(record)
        for item_id, record in semantic_index.items()
    }
    token_df: Counter[str] = Counter()
    for tokens in item_tokens.values():
        token_df.update(tokens)
    max_df = max(1, int(len(semantic_index) * max_df_ratio))
    allowed_tokens = {token for token, df in token_df.items() if df <= max_df}
    idf = {
        token: math.log((1.0 + len(item_tokens)) / (1.0 + df)) + 1.0
        for token, df in token_df.items()
        if token in allowed_tokens
    }
    inverted_index: dict[str, set[str]] = defaultdict(set)
    for item_id, tokens in item_tokens.items():
        for token in tokens & allowed_tokens:
            inverted_index[token].add(item_id)
    context = {
        "token_fields": normalized_fields,
        "max_df_ratio": max_df_ratio,
        "allowed_tokens": allowed_tokens,
        "idf": idf,
        "item_tokens": item_tokens,
        "item_categories": item_categories,
        "inverted_index": inverted_index,
    }
    if len(_SEMANTIC_SEED_CONTEXT_CACHE) >= _SEMANTIC_SEED_CONTEXT_CACHE_LIMIT:
        _SEMANTIC_SEED_CONTEXT_CACHE.pop(next(iter(_SEMANTIC_SEED_CONTEXT_CACHE)))
    _SEMANTIC_SEED_CONTEXT_CACHE[cache_key] = context
    return context


def _two_tower_token_df(
    two_tower_index: dict[str, dict[str, Any]],
    token_fields: list[str] | None,
) -> Counter[str]:
    token_df: Counter[str] = Counter()
    for record in two_tower_index.values():
        token_df.update(_record_two_tower_tokens(record, token_fields))
    return token_df


def _record_semantic_tokens(record: dict[str, Any], token_fields: list[str] | None) -> set[str]:
    if token_fields is None:
        return set(record.get("semantic_tokens", set()))
    return _semantic_tokens(record, token_fields)


def _record_two_tower_tokens(record: dict[str, Any], token_fields: list[str] | None) -> set[str]:
    if token_fields is None:
        return set(record.get("two_tower_tokens", set()))
    return _semantic_tokens(record, token_fields)


def _two_tower_vector(tokens: set[str], idf: dict[str, float]) -> dict[str, float]:
    counts = Counter(tokens)
    return {token: float(count) * idf.get(token, 0.0) for token, count in counts.items() if idf.get(token, 0.0) > 0.0}


def _vector_norm(vector: dict[str, float]) -> float:
    return math.sqrt(sum(value * value for value in vector.values()))


def _cosine_score(
    left: dict[str, float],
    left_norm: float,
    right: dict[str, float],
    right_norm: float,
) -> float:
    if not left_norm or not right_norm:
        return 0.0
    if len(left) > len(right):
        left, right = right, left
    dot = sum(value * right.get(token, 0.0) for token, value in left.items())
    return dot / (left_norm * right_norm)


def _candidate_sort_key(candidate: MergedCandidate, config: dict) -> tuple[float, str]:
    multi_source_boost = float(config.get("candidate_multi_source_boost", 0.0))
    score = sum(candidate.source_scores.values()) + max(len(candidate.sources) - 1, 0) * multi_source_boost
    return (-score, candidate.item_id)


def _candidate_in_group(candidate: MergedCandidate, group: str) -> bool:
    sources = _candidate_group_sources(group)
    return any(source in candidate.sources for source in sources)


def _would_exceed_maximum(
    candidate: MergedCandidate,
    group_counts: Counter[str],
    maximums: dict[str, int],
) -> bool:
    for group, maximum in maximums.items():
        if maximum <= 0 and _candidate_in_group(candidate, group):
            return True
        if maximum > 0 and _candidate_in_group(candidate, group) and group_counts[group] >= maximum:
            return True
    return False


def _increment_group_counts(
    group_counts: Counter[str],
    candidate: MergedCandidate,
    tracked_groups: dict[str, int],
) -> None:
    for group in tracked_groups:
        if _candidate_in_group(candidate, group):
            group_counts[group] += 1


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()



def _semantic_score(
    overlap: int,
    seed_tokens: set[str],
    candidate_tokens: set[str],
    category_overlap: int,
    config: dict,
) -> float:
    if config.get("semantic_score_mode") == "normalized":
        union_size = len(seed_tokens | candidate_tokens)
        jaccard = overlap / union_size if union_size else 0.0
        return round(jaccard * 100.0 + float(category_overlap) * float(config.get("semantic_category_weight", 2.0)), 6)
    return float(overlap) + float(category_overlap) * float(config.get("semantic_category_weight", 2.0))


def _category_buckets(user_sequence: dict[str, Any], item_category: dict[str, str], window: int | None = None) -> list[str]:
    return [f"main::{category}" for category in _seed_categories(user_sequence, item_category, window)]


def _seed_categories(user_sequence: dict[str, Any], item_category: dict[str, str], window: int | None = None) -> list[str]:
    categories: list[str] = []
    sequence = user_sequence.get("recent_positive_item_sequence", [])
    if window is not None:
        sequence = sequence[-window:]
    for item_id in reversed(sequence):
        category = item_category.get(item_id, "")
        if category and category not in categories:
            categories.append(category)
    return categories


def _metadata_neighbor_tokens(row: dict[str, Any], config: dict) -> set[str]:
    fields = config.get("metadata_neighbor_fields")
    if fields is not None:
        fields = [str(field) for field in fields]
    return _semantic_tokens(row, fields)


def _metadata_neighbor_bucket_index(metadata_index: dict[str, dict[str, Any]], config: dict) -> dict[str, dict[str, set[str]]]:
    fields = config.get("metadata_neighbor_fields")
    if fields is not None:
        fields = tuple(str(field) for field in fields)
    else:
        fields = ()
    cache_key = (id(metadata_index), fields)
    cached = _METADATA_NEIGHBOR_INDEX_CACHE.get(cache_key)
    if cached is not None:
        return cached
    token_buckets: dict[str, set[str]] = defaultdict(set)
    category_buckets: dict[str, set[str]] = defaultdict(set)
    for item_id, record in metadata_index.items():
        for token in _metadata_neighbor_tokens(record, config):
            token_buckets[token].add(item_id)
        for category in _semantic_categories(record):
            category_buckets[category].add(item_id)
    bucket_index = {"tokens": token_buckets, "categories": category_buckets}
    if len(_METADATA_NEIGHBOR_INDEX_CACHE) >= _METADATA_NEIGHBOR_INDEX_CACHE_LIMIT:
        _METADATA_NEIGHBOR_INDEX_CACHE.pop(next(iter(_METADATA_NEIGHBOR_INDEX_CACHE)))
    _METADATA_NEIGHBOR_INDEX_CACHE[cache_key] = bucket_index
    return bucket_index


def _metadata_neighbor_bucket_candidates(bucket_index: dict[str, dict[str, set[str]]], tokens: set[str], categories: set[str]) -> set[str]:
    candidates: set[str] = set()
    for token in tokens:
        candidates.update(bucket_index["tokens"].get(token, set()))
    for category in categories:
        candidates.update(bucket_index["categories"].get(category, set()))
    return candidates


def _semantic_tokens(row: dict[str, Any], token_fields: list[str] | None = None) -> set[str]:
    fields = token_fields or ["title_clean", "main_category", "category", "description_text", "features_text", "item_text", "categories_flat"]
    text_parts: list[str] = []
    for field in fields:
        value = row.get(field, "")
        if isinstance(value, list):
            text_parts.extend(str(item) for item in value)
        else:
            text_parts.append(str(value))
    return {token for token in re.findall(r"[a-z0-9]+", " ".join(text_parts).lower()) if len(token) >= 3}


def _semantic_categories(row: dict[str, Any]) -> set[str]:
    categories = {str(row.get("main_category", "")), str(row.get("category", ""))}
    categories.update(str(item) for item in row.get("categories_flat", []))
    categories.update(str(item) for item in row.get("source_categories", []))
    return {category.lower() for category in categories if category}
