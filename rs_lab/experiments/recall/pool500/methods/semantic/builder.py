from __future__ import annotations

import math
import re
import shutil
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any

from rs_core.common.io import read_json, write_json, write_jsonl
from rs_core.recsys.candidate_merge import _semantic_categories, _semantic_score
from rs_lab.experiments.recall.pool500.common.source_layout import FORBIDDEN_EVIDENCE_SCOPES, REQUIRED_SOURCE_OUTPUTS
from rs_lab.experiments.recall.pool500.methods.semantic_title_category_expansion.builder import (
    _candidate_ids_from_inverted_index,
    _file_signature,
    _input_dataset_rows,
    _load_records_by_ids,
    _load_target_sequences,
    _record_tokens,
    _resolve_repo_path,
    _seed_items_by_user,
    _target_user_ids,
    _with_semantic_tokens,
)

ROOT = Path(__file__).resolve().parents[6]
SOURCE = "semantic"
SOURCE_STATUS = "TARGET_SLICE_DIAGNOSTIC"
SCHEMA_VERSION = "pool500_semantic_source_v1"
DEFAULT_CLEAN_MANIFEST = ROOT / "data" / "processed" / "amazon_2023_recall_clean_full" / "manifest.json"
DEFAULT_LIGHTWEIGHT_VIEWS_MANIFEST = ROOT / "data" / "processed" / "amazon_2023_recall_views_full_lightweight" / "manifest.json"
DEFAULT_ELIGIBLE_USER_MANIFEST = ROOT / "outputs" / "recall" / "pool500_main_route_direct_recall_full_promoted" / "eligible_user_manifest.json"
GOVERNANCE_FIELDS = {
    "candidate_generation_allowed": False,
    "ranking_input_replacement_allowed": False,
    "pool1000_allowed": False,
    "promotion_allowed": False,
    "full_pool500_ready_declared": False,
    "final_pool500_ready_claimed": False,
}
CANDIDATE_METADATA_POLICY_LEAN = "lean_reference"
CANDIDATE_METADATA_POLICY_EMBEDDED = "embedded_full"
CANDIDATE_METADATA_POLICIES = {CANDIDATE_METADATA_POLICY_LEAN, CANDIDATE_METADATA_POLICY_EMBEDDED}
ITEM_METADATA_FIELDS = (
    "title_clean",
    "main_category",
    "category",
    "categories_flat",
    "description_text",
    "features_text",
    "item_text",
    "store",
    "brand",
)


def build_semantic_method_source(*, config: dict[str, Any], run_id: str, output_dir: Path, overwrite: bool) -> dict[str, Any]:
    started = perf_counter()
    _precheck_output(output_dir, overwrite)
    output_dir.mkdir(parents=True, exist_ok=False)

    input_contract = config.get("input_contract") if isinstance(config.get("input_contract"), dict) else {}
    method_config = config.get("method_config") if isinstance(config.get("method_config"), dict) else {}
    clean_manifest_path = _config_path(input_contract, DEFAULT_CLEAN_MANIFEST, "clean_manifest", "clean_manifest_path")
    lightweight_views_manifest_path = _config_path(input_contract, DEFAULT_LIGHTWEIGHT_VIEWS_MANIFEST, "lightweight_views_manifest", "lightweight_views_manifest_path")
    eligible_user_manifest_path = _config_path(input_contract, DEFAULT_ELIGIBLE_USER_MANIFEST, "eligible_user_manifest", "eligible_user_manifest_path")
    limit_users = int(method_config.get("limit_users", 500))
    seed_window = int(method_config.get("seed_window", 20))
    per_user = int(method_config.get("per_user", 80))
    per_token_item_limit = int(method_config.get("per_token_item_limit", 2000))
    max_candidate_items = int(method_config.get("max_candidate_items", 80000))
    min_overlap = int(method_config.get("min_overlap", method_config.get("semantic_min_overlap", 2)))
    per_user_candidate_pool_limit = int(method_config.get("per_user_candidate_pool_limit", max_candidate_items))
    candidate_metadata_policy = str(method_config.get("candidate_metadata_policy", CANDIDATE_METADATA_POLICY_LEAN))
    if candidate_metadata_policy not in CANDIDATE_METADATA_POLICIES:
        raise ValueError(f"unsupported semantic candidate metadata policy: {candidate_metadata_policy}")
    semantic_score_config = _semantic_score_config(method_config)

    clean_manifest = read_json(clean_manifest_path)
    views_manifest = read_json(lightweight_views_manifest_path)
    train_sequences_path = _resolve_repo_path(clean_manifest["train_user_sequences_path"])
    canonical_items_path = _resolve_repo_path(clean_manifest["canonical_items_path"])
    view_outputs = views_manifest.get("outputs") if isinstance(views_manifest.get("outputs"), dict) else {}
    semantic_inputs_path = _resolve_repo_path(view_outputs["semantic_recall_inputs"])
    semantic_inverted_index_path = _resolve_repo_path(view_outputs["semantic_inverted_index"])

    target_user_ids = _target_user_ids(eligible_user_manifest_path, limit_users)
    sequences = _load_target_sequences(train_sequences_path, target_user_ids, limit_users)
    seed_items_by_user = _seed_items_by_user(sequences, seed_window)
    seed_items = {item for items in seed_items_by_user.values() for item in items}
    seed_records = _load_records_by_ids(semantic_inputs_path, seed_items)
    seed_tokens = _record_tokens(seed_records.values())
    candidate_item_ids, _token_candidate_ids, token_bucket_stats = _candidate_ids_from_inverted_index(
        semantic_inverted_index_path,
        seed_tokens,
        per_token_item_limit=per_token_item_limit,
        max_candidate_items=max_candidate_items,
    )
    candidate_records = _load_records_by_ids(semantic_inputs_path, candidate_item_ids | seed_items)
    semantic_index = {item_id: _with_semantic_tokens(record) for item_id, record in candidate_records.items()}

    input_dataset_path = output_dir / "semantic_input_dataset.jsonl"
    write_jsonl(input_dataset_path, _input_dataset_rows(semantic_index))
    rows = _candidate_rows(
        sequences,
        seed_items_by_user,
        semantic_index,
        per_user,
        min_overlap,
        per_token_item_limit=per_token_item_limit,
        max_candidate_items=per_user_candidate_pool_limit,
        candidate_metadata_policy=candidate_metadata_policy,
        semantic_score_config=semantic_score_config,
    )
    candidates_path = output_dir / "candidates.jsonl"
    write_jsonl(candidates_path, rows)

    input_paths = [
        clean_manifest_path,
        lightweight_views_manifest_path,
        eligible_user_manifest_path,
        train_sequences_path,
        canonical_items_path,
        semantic_inputs_path,
        semantic_inverted_index_path,
    ]
    artifact_refs = _artifact_refs(
        semantic_inputs_path=semantic_inputs_path,
        semantic_inverted_index_path=semantic_inverted_index_path,
        candidate_metadata_policy=candidate_metadata_policy,
    )
    signatures = {
        "clean_manifest": _file_signature(clean_manifest_path),
        "lightweight_views_manifest": _file_signature(lightweight_views_manifest_path),
        "train_user_sequences": _file_signature(train_sequences_path),
        "canonical_items": _file_signature(canonical_items_path),
        "semantic_recall_inputs": _file_signature(semantic_inputs_path),
        "semantic_inverted_index": _file_signature(semantic_inverted_index_path),
        "semantic_input_dataset": _file_signature(input_dataset_path),
        "candidates": _file_signature(candidates_path),
    }
    target_user_list = [str(sequence.get("user_id", "")) for sequence in sequences]
    per_user_counts = _counts_by_user(rows, target_user_list)
    coverage_audit = _coverage_audit(
        sequences=sequences,
        semantic_index=semantic_index,
        seed_items=seed_items,
        seed_records=seed_records,
        rows=rows,
        per_user_counts=list(per_user_counts.values()),
        token_bucket_stats=token_bucket_stats,
    )
    undercoverage_audit = _undercoverage_audit(target_user_list, per_user_counts, per_user)
    resource_audit = {
        "schema_version": f"{SCHEMA_VERSION}.resource_audit",
        "status": "PASS",
        "source": SOURCE,
        "canonical_source": SOURCE,
        "source_status": SOURCE_STATUS,
        "heavy_job": False,
        "checkpoint_enabled": True,
        "runtime_seconds": round(perf_counter() - started, 6),
        "resource_profile": "train_only_semantic_inverted_index_slice",
        "candidate_metadata_policy": candidate_metadata_policy,
        "semantic_score_config": semantic_score_config,
        "artifact_refs": artifact_refs,
        "batching": {
            "limit_users": limit_users,
            "seed_window": seed_window,
            "per_token_item_limit": per_token_item_limit,
            "max_candidate_items": max_candidate_items,
            "per_user_candidate_pool_limit": per_user_candidate_pool_limit,
        },
        "source_signatures": signatures,
        **GOVERNANCE_FIELDS,
    }
    no_holdout_audit = _no_holdout_audit(input_paths)
    if no_holdout_audit["status"] != "PASS":
        write_json(output_dir / "no_holdout_audit.json", no_holdout_audit)
        raise ValueError(f"forbidden input path detected for semantic source: {no_holdout_audit['forbidden_inputs']}")
    method_dataset_manifest = {
        "schema_version": f"{SCHEMA_VERSION}.method_dataset_manifest",
        "status": "PASS",
        "source": SOURCE,
        "canonical_source": SOURCE,
        "source_status": SOURCE_STATUS,
        "run_id": run_id,
        "created_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "output_dir": str(output_dir),
        "dataset_name": "semantic_input_dataset",
        "input_dataset_path": str(input_dataset_path),
        "declared_input_paths": [str(path) for path in input_paths],
        "candidate_metadata_policy": candidate_metadata_policy,
        "artifact_refs": artifact_refs,
        "train_only": True,
        "target_user_count": len(sequences),
        "seed_item_count": len(seed_items),
        "seed_item_metadata_count": len(seed_records),
        "semantic_index_record_count": len(semantic_index),
        "candidate_row_count": len(rows),
        "user_coverage_count": coverage_audit["user_coverage_count"],
        **GOVERNANCE_FIELDS,
    }
    source_index_manifest = {
        "schema_version": f"{SCHEMA_VERSION}.source_index_manifest",
        "status": "PASS",
        "source": SOURCE,
        "canonical_source": SOURCE,
        "source_status": SOURCE_STATUS,
        "run_id": run_id,
        "created_at": method_dataset_manifest["created_at"],
        "output_dir": str(output_dir),
        "index_scope": "TRAIN_ONLY_SEMANTIC_TOKEN_INDEX_SLICE",
        "train_only": True,
        "candidate_metadata_policy": candidate_metadata_policy,
        "artifact_refs": artifact_refs,
        "method_dataset_manifest_path": str(output_dir / "method_dataset_manifest.json"),
        "source_index_manifest_path": str(output_dir / "source_index_manifest.json"),
        "candidates_path": str(candidates_path),
        "candidate_row_count": len(rows),
        "user_coverage_count": coverage_audit["user_coverage_count"],
        "candidate_count_min": coverage_audit["candidate_count_min"],
        "candidate_count_p50": coverage_audit["candidate_count_p50"],
        "candidate_count_p90": coverage_audit["candidate_count_p90"],
        "candidate_count_max": coverage_audit["candidate_count_max"],
        "required_artifacts": {name: str(output_dir / name) for name in REQUIRED_SOURCE_OUTPUTS},
        "outputs": {name.removesuffix(".json").removesuffix(".jsonl"): str(output_dir / name) for name in REQUIRED_SOURCE_OUTPUTS},
        "audit_statuses": {
            "coverage_audit": coverage_audit["status"],
            "undercoverage_audit": undercoverage_audit["status"],
            "resource_audit": resource_audit["status"],
            "no_holdout_audit": no_holdout_audit["status"],
            "method_dataset_manifest": method_dataset_manifest["status"],
        },
        "source_signatures": signatures,
        **GOVERNANCE_FIELDS,
    }

    write_json(output_dir / "method_dataset_manifest.json", method_dataset_manifest)
    write_json(output_dir / "source_index_manifest.json", source_index_manifest)
    write_json(output_dir / "coverage_audit.json", coverage_audit)
    write_json(output_dir / "undercoverage_audit.json", undercoverage_audit)
    write_json(output_dir / "resource_audit.json", resource_audit)
    write_json(output_dir / "no_holdout_audit.json", no_holdout_audit)
    _assert_required_outputs(output_dir)
    return source_index_manifest


def _candidate_rows(
    sequences: list[dict[str, Any]],
    seed_items_by_user: dict[str, list[str]],
    semantic_index: dict[str, dict[str, Any]],
    per_user: int,
    min_overlap: int,
    *,
    per_token_item_limit: int,
    max_candidate_items: int,
    candidate_metadata_policy: str,
    semantic_score_config: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    score_config = semantic_score_config or _semantic_score_config({})
    token_to_items = _token_to_items(semantic_index, per_token_item_limit=per_token_item_limit)
    token_doc_freq = {token: len(items) for token, items in token_to_items.items()}
    avg_field_lengths = _avg_field_lengths(semantic_index, score_config["field_weights"].keys())
    document_count = max(1, len(semantic_index))
    max_doc_freq = max(1, int(document_count * float(score_config["semantic_max_df_ratio"])))
    generic_tokens = {str(token).lower() for token in score_config.get("generic_tokens", set())}
    rows: list[dict[str, Any]] = []
    for sequence in sequences:
        user_id = str(sequence.get("user_id", ""))
        seen_items = {str(item_id) for item_id in sequence.get("recent_item_sequence", []) if item_id}
        seed_tokens: set[str] = set()
        seed_categories: set[str] = set()
        for item_id in seed_items_by_user.get(user_id, []):
            record = semantic_index.get(item_id)
            if not record:
                continue
            seed_tokens.update(record.get("semantic_tokens", set()))
            seed_categories.update(_semantic_categories(record))
        if not seed_tokens and not seed_categories:
            continue

        overlap_counts: Counter[str] = Counter()
        query_tokens = {
            token
            for token in seed_tokens
            if token not in generic_tokens and token_doc_freq.get(token, 0) <= max_doc_freq
        }
        if not query_tokens:
            query_tokens = seed_tokens
        for token in sorted(query_tokens):
            overlap_counts.update(token_to_items.get(token, []))
        if max_candidate_items > 0 and len(overlap_counts) > max_candidate_items:
            overlap_counts = Counter(dict(overlap_counts.most_common(max_candidate_items)))

        candidates: list[tuple[float, str, int, int, float, dict[str, float]]] = []
        for item_id, overlap in overlap_counts.items():
            if item_id in seen_items or overlap < min_overlap:
                continue
            record = semantic_index.get(item_id)
            if not record:
                continue
            candidate_tokens = record.get("semantic_tokens", set())
            category_overlap = len(seed_categories & _semantic_categories(record))
            if score_config["semantic_score_mode"] == "bm25f":
                bm25f_score, field_scores = _bm25f_score(query_tokens, seed_categories, record, token_doc_freq, avg_field_lengths, document_count, score_config)
                score = bm25f_score
            else:
                field_scores = {}
                bm25f_score = 0.0
                score = _semantic_score(overlap, seed_tokens, candidate_tokens, category_overlap, {"semantic_category_weight": 2.0})
            candidates.append((score, item_id, overlap, category_overlap, bm25f_score, field_scores))

        candidates.sort(key=lambda item: (-item[0], item[1]))
        for rank, (score, item_id, overlap, category_overlap, bm25f_score, field_scores) in enumerate(candidates[:per_user], start=1):
            record = semantic_index[item_id]
            row = {
                "user_id": user_id,
                "item_id": item_id,
                "source": SOURCE,
                "canonical_source": SOURCE,
                "sources": [SOURCE],
                "source_scores": {SOURCE: score},
                "score": score,
                "rank": rank,
                "semantic_token_overlap": overlap,
                "semantic_category_overlap": category_overlap,
                "bm25f_score": bm25f_score,
                "field_scores": field_scores,
            }
            if candidate_metadata_policy == CANDIDATE_METADATA_POLICY_EMBEDDED:
                metadata = {k: v for k, v in record.items() if k != "semantic_tokens"}
                metadata["canonical_source"] = SOURCE
                metadata["source_status"] = SOURCE_STATUS
                metadata["source_scores"] = {SOURCE: score}
                metadata["semantic_token_overlap"] = overlap
                metadata["semantic_category_overlap"] = category_overlap
                metadata["bm25f_score"] = bm25f_score
                metadata["field_scores"] = field_scores
                row["metadata"] = metadata
            rows.append(row)
    return rows


def _semantic_score_config(method_config: dict[str, Any]) -> dict[str, Any]:
    raw_field_weights = method_config.get("field_weights") if isinstance(method_config.get("field_weights"), dict) else {}
    field_weights = {
        "title_clean": float(raw_field_weights.get("title_clean", 3.0)),
        "main_category": float(raw_field_weights.get("main_category", 2.5)),
        "category": float(raw_field_weights.get("category", 2.0)),
        "categories_flat": float(raw_field_weights.get("categories_flat", 1.5)),
        "description_text": float(raw_field_weights.get("description_text", 0.5)),
        "features_text": float(raw_field_weights.get("features_text", 0.5)),
        "item_text": float(raw_field_weights.get("item_text", 0.25)),
    }
    generic_tokens = method_config.get("generic_tokens", ["and", "the", "with", "for", "from", "item", "product"])
    return {
        "semantic_score_mode": str(method_config.get("semantic_score_mode", "bm25f")),
        "bm25_k1": float(method_config.get("bm25_k1", 1.2)),
        "bm25_b": float(method_config.get("bm25_b", 0.75)),
        "field_weights": field_weights,
        "semantic_max_df_ratio": float(method_config.get("semantic_max_df_ratio", 0.5)),
        "generic_tokens": [str(token).lower() for token in generic_tokens] if isinstance(generic_tokens, list) else [],
        "category_boost": float(method_config.get("category_boost", 1.0)),
        "title_boost": float(method_config.get("title_boost", 0.5)),
    }



def _bm25f_score(
    seed_tokens: set[str],
    seed_categories: set[str],
    record: dict[str, Any],
    token_doc_freq: dict[str, int],
    avg_field_lengths: dict[str, float],
    document_count: int,
    config: dict[str, Any],
) -> tuple[float, dict[str, float]]:
    k1 = float(config["bm25_k1"])
    b = float(config["bm25_b"])
    field_weights = config["field_weights"]
    field_scores: dict[str, float] = {}
    total = 0.0
    for field, weight in field_weights.items():
        tokens = _field_tokens(record.get(field))
        if not tokens:
            continue
        counts = Counter(tokens)
        field_len = max(1, len(tokens))
        field_score = 0.0
        for token in seed_tokens:
            tf = counts.get(token, 0)
            if tf <= 0:
                continue
            df = max(1, token_doc_freq.get(token, 1))
            idf = math.log(1.0 + (document_count - df + 0.5) / (df + 0.5))
            avg_field_len = max(1.0, float(avg_field_lengths.get(field, field_len)))
            denom = tf + k1 * (1.0 - b + b * field_len / avg_field_len)
            field_score += idf * ((tf * (k1 + 1.0)) / denom)
        if field_score:
            weighted = field_score * float(weight)
            field_scores[field] = round(weighted, 6)
            total += weighted
    category_overlap = len(seed_categories & _semantic_categories(record))
    if category_overlap:
        boost = category_overlap * float(config["category_boost"])
        field_scores["category_channel_boost"] = round(boost, 6)
        total += boost
    title_overlap = len(seed_tokens & set(_field_tokens(record.get("title_clean"))))
    if title_overlap:
        boost = title_overlap * float(config["title_boost"])
        field_scores["title_channel_boost"] = round(boost, 6)
        total += boost
    return round(total, 6), field_scores



def _field_tokens(value: Any) -> list[str]:
    if isinstance(value, list):
        text = " ".join(str(item) for item in value)
    elif value is None:
        text = ""
    else:
        text = str(value)
    return [token for token in re.findall(r"[a-z0-9]+", text.lower()) if len(token) >= 3]



def _avg_field_lengths(semantic_index: dict[str, dict[str, Any]], fields: Any) -> dict[str, float]:
    lengths: dict[str, list[int]] = {str(field): [] for field in fields}
    for record in semantic_index.values():
        for field in lengths:
            tokens = _field_tokens(record.get(field))
            if tokens:
                lengths[field].append(len(tokens))
    return {
        field: (sum(values) / len(values) if values else 1.0)
        for field, values in lengths.items()
    }



def _token_to_items(semantic_index: dict[str, dict[str, Any]], *, per_token_item_limit: int) -> dict[str, list[str]]:
    token_to_items: dict[str, list[str]] = {}
    for item_id in sorted(semantic_index):
        record = semantic_index[item_id]
        for token in sorted(record.get("semantic_tokens", set())):
            bucket = token_to_items.setdefault(str(token), [])
            if per_token_item_limit <= 0 or len(bucket) < per_token_item_limit:
                bucket.append(item_id)
    return token_to_items


def _artifact_refs(
    *,
    semantic_inputs_path: Path,
    semantic_inverted_index_path: Path,
    candidate_metadata_policy: str,
) -> dict[str, Any]:
    return {
        "candidate_metadata_policy": candidate_metadata_policy,
        "candidate_row_contract": {
            "storage_mode": "reference_only" if candidate_metadata_policy == CANDIDATE_METADATA_POLICY_LEAN else "embedded_full_metadata",
            "join_key": "item_id",
            "required_fields": [
                "user_id",
                "item_id",
                "source",
                "canonical_source",
                "sources",
                "source_scores",
                "score",
                "rank",
                "semantic_token_overlap",
                "semantic_category_overlap",
                "bm25f_score",
                "field_scores",
            ],
            "omitted_item_metadata_fields": list(ITEM_METADATA_FIELDS) if candidate_metadata_policy == CANDIDATE_METADATA_POLICY_LEAN else [],
        },
        "item_metadata_ref": {
            "path": str(semantic_inputs_path),
            "join_key": "item_id",
            "description": "Recent-2y train-only semantic item metadata; candidates keep item_id references instead of repeating title/category/description fields per user-item row.",
        },
        "semantic_index_ref": {
            "path": str(semantic_inverted_index_path),
            "join_key": "semantic_token",
            "description": "Recent-2y train-only semantic inverted index used for candidate lookup; retained as replay evidence for lean candidates.",
        },
    }


def _candidate_ids_for_seed_tokens(seed_tokens: set[str], token_to_items: dict[str, list[str]], *, max_candidate_items: int) -> set[str]:
    candidate_ids: set[str] = set()
    for token in sorted(seed_tokens):
        for item_id in token_to_items.get(token, []):
            candidate_ids.add(item_id)
            if max_candidate_items > 0 and len(candidate_ids) >= max_candidate_items:
                return candidate_ids
    return candidate_ids


def _coverage_audit(
    *,
    sequences: list[dict[str, Any]],
    semantic_index: dict[str, dict[str, Any]],
    seed_items: set[str],
    seed_records: dict[str, dict[str, Any]],
    rows: list[dict[str, Any]],
    per_user_counts: list[int],
    token_bucket_stats: dict[str, Any],
) -> dict[str, Any]:
    record_count = len(semantic_index)
    return {
        "schema_version": f"{SCHEMA_VERSION}.coverage_audit",
        "status": "PASS" if rows else "EMPTY",
        "source": SOURCE,
        "canonical_source": SOURCE,
        "source_status": SOURCE_STATUS,
        "target_user_count": len(sequences),
        "semantic_index_record_count": record_count,
        "seed_item_count": len(seed_items),
        "seed_item_metadata_count": len(seed_records),
        "seed_item_metadata_coverage": _ratio(len(seed_records), len(seed_items)),
        "candidate_row_count": len(rows),
        "unique_item_count": len({str(row.get("item_id")) for row in rows if row.get("item_id")}),
        "user_coverage_count": sum(1 for count in per_user_counts if count > 0),
        "candidate_count_min": min(per_user_counts) if per_user_counts else 0,
        "candidate_count_p50": _percentile(per_user_counts, 0.5),
        "candidate_count_p90": _percentile(per_user_counts, 0.9),
        "candidate_count_max": max(per_user_counts) if per_user_counts else 0,
        "token_bucket_stats": token_bucket_stats,
        **GOVERNANCE_FIELDS,
    }


def _undercoverage_audit(target_user_ids: list[str], counts: dict[str, int], per_user: int) -> dict[str, Any]:
    undercovered = [user_id for user_id in target_user_ids if counts.get(user_id, 0) < per_user]
    empty = [user_id for user_id in target_user_ids if counts.get(user_id, 0) <= 0]
    return {
        "schema_version": f"{SCHEMA_VERSION}.undercoverage_audit",
        "status": "DIAGNOSTIC_ONLY_AUDIT",
        "source": SOURCE,
        "canonical_source": SOURCE,
        "source_status": SOURCE_STATUS,
        "target_user_count": len(target_user_ids),
        "method_target_per_user": per_user,
        "user_coverage_count": len(target_user_ids) - len(empty),
        "undercovered_user_count": len(undercovered),
        "empty_user_count": len(empty),
        "undercovered_user_sample": undercovered[:20],
        **GOVERNANCE_FIELDS,
    }


def _no_holdout_audit(paths: list[Path]) -> dict[str, Any]:
    forbidden = [str(path) for path in paths if _is_forbidden_path(path)]
    return {
        "schema_version": f"{SCHEMA_VERSION}.no_holdout_audit",
        "status": "PASS" if not forbidden else "BLOCKED",
        "source": SOURCE,
        "canonical_source": SOURCE,
        "source_status": SOURCE_STATUS,
        "train_only": not forbidden,
        "candidate_generation_uses_holdout": bool(forbidden),
        "forbidden_inputs": forbidden,
        "declared_inputs": [str(path) for path in paths],
        **GOVERNANCE_FIELDS,
    }


def _config_path(config: dict[str, Any], default: Path, *keys: str) -> Path:
    for key in keys:
        value = config.get(key)
        if value:
            path = Path(str(value))
            return path if path.is_absolute() else ROOT / path
    return default


def _precheck_output(output_dir: Path, overwrite: bool) -> None:
    if output_dir.exists():
        if not overwrite:
            raise FileExistsError(f"output directory already exists: {output_dir}")
        shutil.rmtree(output_dir)


def _counts_by_user(rows: list[dict[str, Any]], target_user_ids: list[str]) -> dict[str, int]:
    counts = {user_id: 0 for user_id in target_user_ids}
    observed = Counter(str(row.get("user_id", "")) for row in rows)
    for user_id in counts:
        counts[user_id] = observed[user_id]
    return counts


def _is_forbidden_path(path: Path) -> bool:
    parts = [part.lower() for part in path.parts]
    tokens = {token.lower() for token in FORBIDDEN_EVIDENCE_SCOPES}
    return any(token in part for part in parts for token in tokens)


def _ratio(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 6) if denominator else 0.0


def _percentile(values: list[int], percentile: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(len(ordered) * percentile + 0.999999) - 1))
    return ordered[index]


def _assert_required_outputs(output_dir: Path) -> None:
    missing = [name for name in REQUIRED_SOURCE_OUTPUTS if not (output_dir / name).is_file()]
    if missing:
        raise RuntimeError(f"missing required semantic source outputs: {missing}")
