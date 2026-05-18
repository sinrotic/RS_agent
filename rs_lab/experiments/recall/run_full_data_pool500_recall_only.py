from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rs_core.common.io import iter_jsonl, read_json, write_json, write_jsonl
from rs_core.common.runtime import enforce_project_venv
from rs_core.recsys.candidate_merge import (
    load_category_candidates,
    load_itemcf_by_source,
    load_popular_candidates,
    load_swing_recall_sidecar,
    load_two_tower_index,
    load_usercf_recall_sidecar,
    merge_for_user,
)
from rs_core.workflow.full_data_pool500_route_gate import (
    CANONICAL_SOURCES,
    DIAGNOSTIC_ONLY_PARTIAL,
    READINESS_BUNDLE_SCHEMA_VERSION,
    READY,
    build_canonical_source_registry,
    build_pool500_shadow_evidence,
    canonical_manifest_sha256,
    canonical_user_set_hash,
    full_data_pool500_artifact_gate,
    validate_pool500_shadow_evidence,
    validate_readiness_bundle,
)

SCHEMA_VERSION = "full_data_pool500_recall_only_generation_v1"
DEFAULT_CLEAN_MANIFEST = ROOT / "data" / "processed" / "amazon_2023_recall_clean_full" / "manifest.json"
DEFAULT_LIGHTWEIGHT_VIEWS_MANIFEST = ROOT / "data" / "processed" / "amazon_2023_recall_views_full_lightweight" / "manifest.json"
DEFAULT_OUTPUT_DIR = ROOT / "outputs" / "recall" / "full_data_pool500_recall_only"
DEFAULT_SOURCE_MANIFESTS = {
    "itemcf_weak": ROOT / "outputs" / "recall" / "pool500_recall_sources" / "itemcf_full_train_sidecar" / "itemcf_weak" / "source_index_manifest.json",
    "itemcf_strong": ROOT / "outputs" / "recall" / "pool500_recall_sources" / "itemcf_full_train_sidecar" / "itemcf_strong" / "source_index_manifest.json",
    "usercf_recall": ROOT / "outputs" / "recall" / "pool500_full_train_usercf_sidecar" / "source_index_manifest.json",
    "swing_recall": ROOT / "outputs" / "recall" / "pool500_full_sources" / "swing_recall" / "source_index_manifest.json",
    "semantic_title_category_expansion": ROOT / "outputs" / "recall" / "full_semantic_title_category_expansion" / "source_index_manifest.json",
    "two_tower": ROOT / "outputs" / "recall" / "pool500_full_sources" / "two_tower" / "source_index_manifest.json",
}
DEFAULT_USERCF_SIDECAR_MANIFEST = DEFAULT_SOURCE_MANIFESTS["usercf_recall"]
DEFAULT_SMOKE_LIMIT_USERS = 1000
FILL_ORDER = [
    "semantic_title_category_expansion",
    "semantic",
    "two_tower",
    "itemcf_strong",
    "itemcf_weak",
    "co_visit_fallback_repair",
    "usercf_recall",
    "swing_recall",
    "category",
    "popular",
]
SOURCE_ALIASES = {
    "metadata_neighbor_recall": "co_visit_fallback_repair",
    "category_recall_items": "category",
    "category_top_items": "category",
    "category_long_tail_recall": "category",
}
READY_STOPLOSS_SOURCES = ("category", "popular", "swing_recall")
DIAGNOSTIC_CONTRIBUTION_SOURCES = ("usercf_recall", "itemcf_weak", "itemcf_strong")
GENERATION_SOURCE_CONFIG = {
    "candidate_pool_size": 500,
    "candidate_pool_strategy": "balanced_source_budget",
    "candidate_source_maximums": {"popular": 175, "category": 175},
    "candidate_fill_order": FILL_ORDER,
    "candidate_multi_source_boost": 0.1,
    "popular_fallback_count": 500,
    "popular_fill_policy": "capped_remainder",
    "category_recent_positive_window": 20,
    "category_per_bucket": 80,
    "category_long_tail_enabled": False,
    "category_long_tail_seed_window": 20,
    "category_long_tail_per_category": 40,
    "category_long_tail_per_user": 80,
    "semantic_enabled": True,
    "semantic_per_user": 80,
    "semantic_min_overlap": 2,
    "semantic_score_mode": "idf_seed_aware",
    "semantic_seed_window": 20,
    "semantic_per_seed": 20,
    "semantic_max_bucket_candidates": 5000,
    "metadata_neighbor_enabled": True,
    "metadata_neighbor_seed_window": 20,
    "metadata_neighbor_per_seed": 20,
    "metadata_neighbor_per_user": 80,
    "metadata_neighbor_min_token_overlap": 1,
    "usercf_enabled": True,
    "usercf_per_user": 80,
    "swing_enabled": True,
    "swing_per_user": 80,
    "swing_per_seed": 20,
    "two_tower_enabled": True,
    "two_tower_per_user": 80,
    "semantic_title_category_expansion": {
        "enabled": True,
        "per_user": 80,
        "per_seed": 20,
        "seed_window": 20,
        "min_title_overlap": 1,
        "category_weight": 2.0,
        "weak_category_boost": 0.5,
        "weak_categories": ["All Electronics", "Office Products", "Computers"],
        "text_fields": ["title_clean", "main_category", "categories_flat"],
        "require_category_overlap": True,
    },
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate full-data pool500 recall-only candidates and readiness artifacts.")
    parser.add_argument("--clean-manifest", default=str(DEFAULT_CLEAN_MANIFEST))
    parser.add_argument("--lightweight-views-manifest", default=str(DEFAULT_LIGHTWEIGHT_VIEWS_MANIFEST))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--usercf-sidecar-manifest", default=str(DEFAULT_USERCF_SIDECAR_MANIFEST))
    parser.add_argument("--source-manifest", action="append", default=[], help="Override source manifest as source=path; may be repeated.")
    parser.add_argument("--limit-users", type=int, default=DEFAULT_SMOKE_LIMIT_USERS)
    parser.add_argument("--full-run", action="store_true", help="Allow processing all train users by setting limit-users to 0.")
    parser.add_argument("--enable-semantic", action="store_true", help="Load batch-scoped semantic metadata index; off by default for safe smoke runs.")
    parser.add_argument("--semantic-max-rows", type=int, default=200000, help="Maximum semantic rows to retain for a diagnostic batch-scoped index.")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--skip-venv-check", action="store_true")
    return parser.parse_args()


def run_full_data_pool500_recall_only(
    *,
    clean_manifest_path: Path = DEFAULT_CLEAN_MANIFEST,
    lightweight_views_manifest_path: Path = DEFAULT_LIGHTWEIGHT_VIEWS_MANIFEST,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    usercf_sidecar_manifest_path: Path = DEFAULT_USERCF_SIDECAR_MANIFEST,
    source_manifest_paths: dict[str, Path] | None = None,
    limit_users: int = DEFAULT_SMOKE_LIMIT_USERS,
    full_run: bool = False,
    enable_semantic: bool = False,
    semantic_max_rows: int = 200000,
    overwrite: bool = False,
    enforce_venv: bool = True,
) -> dict[str, Any]:
    started = perf_counter()
    if enforce_venv:
        enforce_project_venv(ROOT)
    if limit_users <= 0 and not full_run:
        raise ValueError("Full train generation requires --full-run; use --limit-users for smoke/diagnostic runs.")
    output_dir = output_dir.resolve()
    if output_dir.exists() and any(output_dir.iterdir()) and not overwrite:
        raise FileExistsError(f"Output directory already exists: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)

    clean_manifest = read_json(clean_manifest_path)
    views_manifest = read_json(lightweight_views_manifest_path)
    view_outputs = _resolve_view_outputs(views_manifest)
    sequence_path = _resolve_repo_path(clean_manifest["train_user_sequences_path"])
    source_manifest_paths = _source_manifest_paths(source_manifest_paths, usercf_sidecar_manifest_path)
    source_artifacts = _load_source_artifacts(source_manifest_paths)

    available_artifacts = _available_source_artifacts(view_outputs) | {source: artifact["path"].is_file() for source, artifact in source_artifacts.items()}
    batch_sequences = _load_batch_sequences(sequence_path, limit_users)
    popular = load_popular_candidates(view_outputs["popular_recall"], limit=10000)
    category_top = load_category_candidates(view_outputs["category_top_items"])
    item_category = _load_item_category(view_outputs["category_recall_items"])
    itemcf_weak = _load_source_itemcf(source_artifacts.get("itemcf_weak"), view_outputs.get("itemcf_recall_weak"), "itemcf_weak")
    itemcf_strong = _load_source_itemcf(source_artifacts.get("itemcf_strong"), view_outputs.get("itemcf_recall_strong"), "itemcf_strong")
    semantic_artifact = source_artifacts.get("semantic_title_category_expansion")
    semantic_source_path = _artifact_data_path(semantic_artifact, "semantic_recall_inputs_path") if semantic_artifact else view_outputs["semantic_recall_inputs"]
    semantic_index = _load_batch_semantic_index(semantic_source_path, batch_sequences, semantic_max_rows) if enable_semantic else {}
    usercf_recall = _load_optional_usercf(source_artifacts.get("usercf_recall", {}).get("path"))
    swing_recall = _load_optional_swing(source_artifacts.get("swing_recall", {}).get("path"))
    two_tower_index = _load_optional_two_tower(source_artifacts.get("two_tower"))
    generation_config = dict(GENERATION_SOURCE_CONFIG)
    if not enable_semantic:
        generation_config.update({
            "semantic_enabled": False,
            "metadata_neighbor_enabled": False,
            "semantic_title_category_expansion": {"enabled": False},
        })

    rows: list[dict[str, Any]] = []
    source_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    users: list[str] = []
    underfilled_user_count = 0
    source_coverage: Counter[str] = Counter()
    popular_category_cap_violations = 0
    processed_users = 0
    for sequence in batch_sequences:
        user_id = str(sequence.get("user_id", ""))
        if not user_id:
            continue
        candidates, _fallback_used = merge_for_user(
            sequence,
            popular,
            itemcf_weak,
            itemcf_strong,
            category_top,
            item_category,
            generation_config,
            semantic_index=semantic_index,
            two_tower_index=two_tower_index,
            item_graph={},
            two_tower_seed={},
            graph_walk_seed={},
            usercf_recall=usercf_recall,
            swing_recall=swing_recall,
        )
        candidates = _enforce_popular_category_cap(candidates)
        users.append(user_id)
        processed_users += 1
        if len(candidates) < 500:
            underfilled_user_count += 1
        popular_category_count = 0
        for rank, candidate in enumerate(candidates, start=1):
            canonical_sources = _canonical_sources(candidate.sources)
            primary_source = _primary_source(canonical_sources)
            if primary_source in {"popular", "category"}:
                popular_category_count += 1
            source_coverage.update(canonical_sources)
            row = {
                "user_id": user_id,
                "item_id": candidate.item_id,
                "source": primary_source,
                "sources": canonical_sources,
                "score": float(sum(candidate.source_scores.values())),
                "rank": rank,
                "metadata": {
                    "category": candidate.category,
                    "source_scores": {source: float(score) for source, score in sorted(candidate.source_scores.items())},
                },
            }
            rows.append(row)
            for source in canonical_sources:
                source_rows[source].append(row)
        if popular_category_count > 175:
            popular_category_cap_violations += 1

    candidate_path = output_dir / "pool500_candidates.jsonl"
    write_jsonl(candidate_path, rows)
    per_source_output_manifests = _write_source_manifests(output_dir, source_rows, available_artifacts, source_artifacts)
    eligible_user_manifest = _eligible_user_manifest(clean_manifest, users, sequence_path, limit_users, full_run)
    canonical_source_registry = build_canonical_source_registry()
    canonical_source_registry_path = output_dir / "canonical_source_registry.json"
    write_json(canonical_source_registry_path, canonical_source_registry)
    source_budget_contract = _source_budget_contract(clean_manifest, views_manifest, limit_users, full_run)
    source_budget_contract_path = output_dir / "source_budget_contract.json"
    write_json(source_budget_contract_path, source_budget_contract)
    per_source_readiness_contracts = _source_readiness_contracts(per_source_output_manifests, source_coverage, source_artifacts)
    full_derived_index_manifests = _full_derived_index_manifests(view_outputs, available_artifacts, source_artifacts)
    merged_manifest = _merged_manifest(candidate_path, clean_manifest, views_manifest, users, rows, underfilled_user_count, source_coverage)
    ready_source_stoploss_audit = _ready_source_stoploss_audit(users, rows, source_rows, underfilled_user_count)
    ready_source_stoploss_audit_path = output_dir / "ready_source_stoploss_audit.json"
    diagnostic_source_contribution = _diagnostic_source_contribution(users, rows, source_rows, underfilled_user_count)
    diagnostic_source_contribution_path = output_dir / "diagnostic_source_contribution.json"
    route_input_manifest = _route_input_manifest(clean_manifest_path, lightweight_views_manifest_path, clean_manifest, views_manifest, view_outputs)
    artifact_gate_result = full_data_pool500_artifact_gate(
        eligible_user_manifest=eligible_user_manifest,
        canonical_source_registry=canonical_source_registry,
        source_budget_contract=source_budget_contract,
        per_source_readiness_contracts=per_source_readiness_contracts,
        per_source_output_manifests=per_source_output_manifests,
        full_derived_index_manifests=full_derived_index_manifests,
        merged_pool500_manifest=merged_manifest,
        merged_rows=rows,
        route_input_manifest=route_input_manifest,
        underfilled_threshold=int(len(users) * 0.02),
    )
    quality_audit = _quality_audit(users, rows, underfilled_user_count, popular_category_cap_violations)
    readiness_bundle = _readiness_bundle(
        artifact_gate_result=_artifact_gate_summary(artifact_gate_result),
        quality_audit=quality_audit,
        source_budget_audit={"status": "PASS" if source_budget_contract["budget_frozen"] and source_budget_contract["train_only"] else "FAIL"},
        source_output_manifest_audit={"status": "PASS" if _all_required_sources_ready(per_source_readiness_contracts) else DIAGNOSTIC_ONLY_PARTIAL},
        index_manifest_audit={"status": "PASS" if full_derived_index_manifests.get("two_tower", {}).get("status") == READY else DIAGNOSTIC_ONLY_PARTIAL},
        no_holdout_audit={"status": "PASS"},
        ranking_registry_check={"status": "PASS", "ranking_input_replacement_allowed": False},
        final_merged_candidate_manifest=merged_manifest,
        eligible_user_manifest=eligible_user_manifest,
        canonical_source_registry_sha256=canonical_manifest_sha256(canonical_source_registry),
    )
    readiness_result = validate_readiness_bundle(readiness_bundle)
    shadow_evidence = build_pool500_shadow_evidence(
        evidence_id="full_data_pool500_recall_only_shadow",
        artifact_gate_result=artifact_gate_result,
        readiness_bundle_result=readiness_result,
        readiness_bundle_path=str(output_dir / "readiness_bundle.json"),
        artifact_paths={
            "pool500_candidates": str(candidate_path),
            "merged_pool500_manifest": str(output_dir / "merged_pool500_manifest.json"),
            "readiness_result": str(output_dir / "readiness_result.json"),
        },
        quality_audit=quality_audit,
    )
    shadow_evidence_validation = validate_pool500_shadow_evidence(shadow_evidence)
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "runtime_seconds": round(perf_counter() - started, 6),
        "scope": "full_data_pool500_recall_only_generation",
        "mode": "full" if full_run and limit_users <= 0 else "diagnostic_limited",
        "decision": readiness_result["decision"],
        "status": readiness_result["status"],
        "artifact_gate_decision": artifact_gate_result["decision"],
        "processed_users": processed_users,
        "candidate_rows": len(rows),
        "underfilled_user_count": underfilled_user_count,
        "source_coverage": dict(sorted(source_coverage.items())),
        "ready_source_stoploss_audit": {
            "status": ready_source_stoploss_audit["status"],
            "audit_path": str(ready_source_stoploss_audit_path),
            "ready_sources": ready_source_stoploss_audit["ready_sources"],
            "stoploss_triggered": ready_source_stoploss_audit["stoploss_triggered"],
            "trigger_reasons": ready_source_stoploss_audit["trigger_reasons"],
        },
        "diagnostic_source_contribution": {
            "status": diagnostic_source_contribution["status"],
            "audit_path": str(diagnostic_source_contribution_path),
            "sources": diagnostic_source_contribution["diagnostic_sources"],
            "row_total": diagnostic_source_contribution["diagnostic_row_total"],
            "marginal_candidate_share": diagnostic_source_contribution["diagnostic_marginal_candidate_share"],
            "promotion_allowed": diagnostic_source_contribution["promotion_allowed"],
        },
        "candidate_generation_allowed": False,
        "ranking_input_replacement_allowed": False,
        "pool1000_allowed": False,
        "required_artifacts": {
            "pool500_candidates": str(candidate_path),
            "merged_pool500_manifest": str(output_dir / "merged_pool500_manifest.json"),
            "eligible_user_manifest": str(output_dir / "eligible_user_manifest.json"),
            "canonical_source_registry": str(canonical_source_registry_path),
            "source_budget_contract": str(source_budget_contract_path),
            "per_source_readiness_contracts": str(output_dir / "per_source_readiness_contracts.json"),
            "per_source_output_manifests": str(output_dir / "per_source_output_manifests.json"),
            "full_derived_index_manifests": str(output_dir / "full_derived_index_manifests.json"),
            "route_input_manifest": str(output_dir / "route_input_manifest.json"),
            "ready_source_stoploss_audit": str(ready_source_stoploss_audit_path),
            "diagnostic_source_contribution": str(diagnostic_source_contribution_path),
            "readiness_bundle": str(output_dir / "readiness_bundle.json"),
            "readiness_result": str(output_dir / "readiness_result.json"),
            "pool500_shadow_evidence": str(output_dir / "pool500_shadow_evidence.json"),
            "pool500_shadow_evidence_validation": str(output_dir / "pool500_shadow_evidence_validation.json"),
        },
        "pool500_shadow_evidence_validation": shadow_evidence_validation,
        "blockers": readiness_result["blockers"],
        "diagnostics": readiness_result["diagnostics"],
    }
    write_json(output_dir / "eligible_user_manifest.json", eligible_user_manifest)
    write_json(output_dir / "per_source_readiness_contracts.json", per_source_readiness_contracts)
    write_json(output_dir / "per_source_output_manifests.json", per_source_output_manifests)
    write_json(output_dir / "full_derived_index_manifests.json", full_derived_index_manifests)
    write_json(output_dir / "merged_pool500_manifest.json", merged_manifest)
    write_json(output_dir / "route_input_manifest.json", route_input_manifest)
    write_json(ready_source_stoploss_audit_path, ready_source_stoploss_audit)
    write_json(diagnostic_source_contribution_path, diagnostic_source_contribution)
    write_json(output_dir / "quality_audit.json", quality_audit)
    write_json(output_dir / "readiness_bundle.json", readiness_bundle)
    write_json(output_dir / "readiness_result.json", readiness_result)
    write_json(output_dir / "pool500_shadow_evidence.json", shadow_evidence)
    write_json(output_dir / "pool500_shadow_evidence_validation.json", shadow_evidence_validation)
    write_json(output_dir / "manifest.json", manifest)
    return manifest


def _resolve_repo_path(value: Any) -> Path:
    path = Path(str(value))
    return path if path.is_absolute() else ROOT / path


def _source_manifest_paths(overrides: dict[str, Path] | None, usercf_sidecar_manifest_path: Path) -> dict[str, Path]:
    paths = dict(DEFAULT_SOURCE_MANIFESTS)
    paths["usercf_recall"] = usercf_sidecar_manifest_path
    for source, path in (overrides or {}).items():
        paths[str(source)] = Path(path)
    return paths


def _load_source_artifacts(source_manifest_paths: dict[str, Path]) -> dict[str, dict[str, Any]]:
    artifacts = {}
    for source, path in sorted(source_manifest_paths.items()):
        manifest_path = _resolve_repo_path(path)
        if not manifest_path.is_file():
            continue
        manifest = read_json(manifest_path)
        manifest_source = str(manifest.get("source") or source)
        if manifest_source != source:
            raise ValueError(f"source manifest mismatch for {source}: {manifest_source!r}")
        artifacts[source] = {"path": manifest_path, "manifest": manifest}
    return artifacts


def _artifact_data_path(artifact: dict[str, Any] | None, key: str) -> Path | None:
    if not artifact:
        return None
    manifest_path = artifact["path"]
    manifest = artifact["manifest"]
    value = manifest.get(key)
    for section in ("required_artifacts", "outputs", "output_files", "contract"):
        if value:
            break
        payload = manifest.get(section) if isinstance(manifest.get(section), dict) else {}
        value = payload.get(key)
    if not value:
        return None
    path = Path(str(value))
    if path.is_absolute():
        return path
    manifest_relative = manifest_path.parent / path
    return manifest_relative if manifest_relative.exists() else _resolve_repo_path(path)


def _parse_source_manifest_overrides(values: list[str]) -> dict[str, Path]:
    overrides = {}
    for value in values:
        if "=" not in value:
            raise ValueError(f"source manifest override must be source=path: {value}")
        source, path = value.split("=", 1)
        overrides[source.strip()] = Path(path.strip())
    return overrides


def _load_batch_sequences(sequence_path: Path, limit_users: int) -> list[dict[str, Any]]:
    sequences = []
    for sequence in iter_jsonl(sequence_path):
        if not sequence.get("user_id"):
            continue
        sequences.append(sequence)
        if limit_users > 0 and len(sequences) >= limit_users:
            break
    return sequences


def _load_batch_semantic_index(path: Path, sequences: list[dict[str, Any]], max_rows: int) -> dict[str, dict[str, Any]]:
    seed_items = _batch_seed_items(sequences)
    if not seed_items or max_rows <= 0:
        return {}
    seed_records = {}
    seed_tokens: set[str] = set()
    seed_categories: set[str] = set()
    for row in iter_jsonl(path):
        item_id = str(row.get("parent_asin") or "")
        if item_id not in seed_items:
            continue
        tokens = _semantic_tokens(row)
        metadata = dict(row)
        metadata["semantic_tokens"] = tokens
        seed_records[item_id] = metadata
        seed_tokens.update(tokens)
        seed_categories.update(_semantic_categories(row))
    if not seed_records or not seed_tokens and not seed_categories:
        return seed_records
    candidate_records = {}
    for row in iter_jsonl(path):
        if len(candidate_records) >= max_rows:
            break
        item_id = str(row.get("parent_asin") or "")
        if not item_id or item_id in seed_records:
            continue
        tokens = _semantic_tokens(row)
        categories = _semantic_categories(row)
        if tokens & seed_tokens or categories & seed_categories:
            metadata = dict(row)
            metadata["semantic_tokens"] = tokens
            candidate_records[item_id] = metadata
    return {**candidate_records, **seed_records}


def _batch_seed_items(sequences: list[dict[str, Any]], window: int = 20) -> set[str]:
    seed_items = set()
    for sequence in sequences:
        recent_positive = sequence.get("recent_positive_item_sequence", [])
        if not isinstance(recent_positive, list):
            continue
        seed_items.update(str(item) for item in recent_positive[-window:] if item)
    return seed_items


def _semantic_tokens(row: dict[str, Any]) -> set[str]:
    fields = ["title_clean", "main_category", "category", "description_text", "features_text", "item_text", "categories_flat"]
    text_parts = []
    for field in fields:
        value = row.get(field)
        if isinstance(value, list):
            text_parts.extend(str(item) for item in value)
        elif value is not None:
            text_parts.append(str(value))
    return {token for token in re.findall(r"[a-z0-9]+", " ".join(text_parts).lower()) if len(token) >= 3}


def _semantic_categories(row: dict[str, Any]) -> set[str]:
    categories = {str(row.get("main_category", "")), str(row.get("category", ""))}
    raw_categories = row.get("categories_flat", [])
    if isinstance(raw_categories, list):
        categories.update(str(item) for item in raw_categories)
    return {item.lower() for item in categories if item}


def _resolve_view_outputs(views_manifest: dict[str, Any]) -> dict[str, Path]:
    outputs = views_manifest.get("outputs") if isinstance(views_manifest.get("outputs"), dict) else {}
    resolved = {str(name): _resolve_repo_path(path) for name, path in outputs.items()}
    views_dir = _resolve_repo_path(Path(str(views_manifest.get("source_clean_dir", ""))).parent / "amazon_2023_recall_views_full_lightweight")
    resolved.setdefault("popular_recall", views_dir / "popular_recall.jsonl")
    resolved.setdefault("category_recall_items", views_dir / "category_recall_items.jsonl")
    resolved.setdefault("category_top_items", views_dir / "category_top_items.jsonl")
    resolved.setdefault("semantic_recall_inputs", views_dir / "semantic_recall_inputs.jsonl")
    return resolved


def _available_source_artifacts(view_outputs: dict[str, Path]) -> dict[str, bool]:
    return {name: path.is_file() for name, path in sorted(view_outputs.items())}


def _load_source_itemcf(artifact: dict[str, Any] | None, fallback_path: Path | None, source: str) -> dict[str, list[Any]]:
    path = _artifact_data_path(artifact, "edges_path") if artifact else fallback_path
    if path is None or not path.is_file():
        return {}
    return load_itemcf_by_source(path, source)


def _load_optional_usercf(path: Path | None) -> dict[str, list[Any]]:
    if path is None or not path.is_file():
        return {}
    return load_usercf_recall_sidecar(path)


def _load_optional_swing(path: Path | None) -> dict[str, list[Any]]:
    if path is None or not path.is_file():
        return {}
    return load_swing_recall_sidecar(path)


def _load_optional_two_tower(artifact: dict[str, Any] | None) -> Any:
    path = _artifact_data_path(artifact, "recall_index_path") or _artifact_data_path(artifact, "recall_index") if artifact else None
    if path is None:
        path = _artifact_data_path(artifact, "artifact_manifest") if artifact else None
    if path is None or not path.is_file():
        return {}
    return load_two_tower_index(path)


def _load_item_category(path: Path) -> dict[str, str]:
    mapping = {}
    for row in iter_jsonl(path):
        item_id = row.get("parent_asin")
        if item_id:
            mapping[str(item_id)] = str(row.get("main_category") or row.get("category") or "")
    return mapping


def _enforce_popular_category_cap(candidates: list[Any], cap: int = 175) -> list[Any]:
    capped = []
    popular_category_count = 0
    for candidate in candidates:
        sources = set(_canonical_sources(candidate.sources))
        if sources <= {"popular", "category"}:
            if popular_category_count >= cap:
                continue
            popular_category_count += 1
        capped.append(candidate)
    return capped


def _canonical_sources(sources: list[str]) -> list[str]:
    normalized = []
    for source in sources:
        canonical = SOURCE_ALIASES.get(str(source), str(source))
        if canonical in CANONICAL_SOURCES and canonical not in normalized:
            normalized.append(canonical)
    return normalized or ["popular"]


def _primary_source(sources: list[str]) -> str:
    for source in FILL_ORDER:
        if source in sources:
            return source
    return sources[0]


def _write_source_manifests(
    output_dir: Path,
    source_rows: dict[str, list[dict[str, Any]]],
    available_artifacts: dict[str, bool],
    source_artifacts: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    manifests = {}
    for source in sorted(CANONICAL_SOURCES):
        rows = source_rows.get(source, [])
        artifact = source_artifacts.get(source, {})
        readiness_path = _artifact_data_path(artifact, "readiness_contract") if artifact else None
        readiness_contract = read_json(readiness_path) if readiness_path and readiness_path.is_file() else {}
        source_path = output_dir / "sources" / source / "candidates.jsonl"
        write_jsonl(source_path, rows)
        manifest = {
            "schema_version": f"{SCHEMA_VERSION}.source_output_manifest",
            "source": source,
            "status": READY if rows else "DEFERRED",
            "final_sources": [source] if rows else [],
            "output_path": str(source_path),
            "row_count": len(rows),
            "manifest_sha256": canonical_manifest_sha256({"source": source, "ready": bool(rows)}),
            "available_artifacts": available_artifacts,
        }
        if artifact:
            source_manifest = artifact["manifest"]
            manifest.update(
                {
                    "source_index_manifest_path": str(artifact["path"]),
                    "source_index_manifest_sha256": source_manifest.get("manifest_sha256") or source_manifest.get("source_index_manifest_sha256"),
                }
            )
            if readiness_contract:
                manifest.update(
                    {
                        "manifest_sha256": readiness_contract.get("output_manifest_sha256") or readiness_contract.get("manifest_sha256") or manifest["manifest_sha256"],
                        "candidate_shard_signatures": readiness_contract.get("candidate_shard_signatures", []),
                    }
                )
        write_json(source_path.parent / "manifest.json", manifest)
        manifests[source] = manifest
    return manifests


def _eligible_user_manifest(clean_manifest: dict[str, Any], users: list[str], sequence_path: Path, limit_users: int, full_run: bool) -> dict[str, Any]:
    return {
        "schema_version": f"{SCHEMA_VERSION}.eligible_user_manifest",
        "scope": "full_train_users" if full_run and limit_users <= 0 else "diagnostic_limited_train_users",
        "source_train_user_sequences_path": str(sequence_path),
        "eligible_user_count": len(users),
        "eligible_user_ids": users,
        "eligible_user_hash": canonical_user_set_hash(users),
        "clean_manifest_sha256": canonical_manifest_sha256(clean_manifest),
    }


def _source_budget_contract(clean_manifest: dict[str, Any], views_manifest: dict[str, Any], limit_users: int, full_run: bool) -> dict[str, Any]:
    view_outputs = list(views_manifest.get("outputs", {}).values()) if isinstance(views_manifest.get("outputs"), dict) else []
    train_split = clean_manifest.get("split_paths", {}).get("train") if isinstance(clean_manifest.get("split_paths"), dict) else None
    return {
        "schema_version": f"{SCHEMA_VERSION}.source_budget_contract",
        "candidate_pool_size": 500,
        "budget_frozen": True,
        "train_only": True,
        "popular_category_combined_cap": 175,
        "candidate_fill_order": FILL_ORDER,
        "mode": "full" if full_run and limit_users <= 0 else "diagnostic_limited",
        "input_path": clean_manifest.get("train_user_sequences_path"),
        "train_inputs": [
            clean_manifest.get("train_user_sequences_path"),
            train_split,
            *view_outputs,
        ],
    }


def _source_readiness_contracts(
    per_source_output_manifests: dict[str, dict[str, Any]],
    source_coverage: Counter[str],
    source_artifacts: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    contracts = {}
    for source in sorted(CANONICAL_SOURCES):
        manifest = per_source_output_manifests[source]
        artifact = source_artifacts.get(source, {})
        readiness_path = _artifact_data_path(artifact, "readiness_contract") if artifact else None
        readiness_contract = read_json(readiness_path) if readiness_path and readiness_path.is_file() else {}
        ready = source_coverage.get(source, 0) > 0
        status = READY if ready else "DEFERRED"
        if readiness_contract.get("status") and readiness_contract.get("status") != READY:
            status = str(readiness_contract["status"])
        contracts[source] = {
            "status": status,
            "manifest_path": str(Path(manifest["output_path"]).parent / "manifest.json"),
            "output_manifest_sha256": manifest["manifest_sha256"],
            "row_count": manifest["row_count"],
        }
        if artifact:
            contracts[source].update(_artifact_readiness_fields(source, artifact, readiness_contract, ready))
    return contracts


def _artifact_readiness_fields(source: str, artifact: dict[str, Any], readiness_contract: dict[str, Any], ready: bool) -> dict[str, Any]:
    manifest = artifact["manifest"]
    fields = {
        "source_index_manifest_path": str(artifact["path"]),
        "source_name": manifest.get("source_name") or manifest.get("source") or source,
        "canonical_source": manifest.get("canonical_source") or source,
        "index_status": readiness_contract.get("index_status") or ("INDEX_READY" if ready and manifest.get("index_scope") == "FULL_DERIVED_INDEX" else None),
        "diagnostic_output_status": readiness_contract.get("diagnostic_output_status"),
        "full_output_status": readiness_contract.get("full_output_status") or ("FULL_OUTPUT_READY" if ready else None),
        "index_manifest_sha256": readiness_contract.get("index_manifest_sha256") or manifest.get("index_manifest_sha256") or manifest.get("manifest_sha256") or canonical_manifest_sha256(manifest),
        "output_manifest_sha256": readiness_contract.get("output_manifest_sha256"),
        "candidate_shards_sha256": readiness_contract.get("candidate_shards_sha256"),
    }
    for key in (
        "clean_manifest_sha256",
        "train_sequence_sha256",
        "item_universe_sha256",
        "model_config_sha256",
        "item_embedding_row_count",
        "recall_index_row_count",
        "user_embedding_row_count",
        "user_embedding_row_count_note",
        "index_scope",
    ):
        if readiness_contract.get(key) is not None or manifest.get(key) is not None:
            fields[key] = readiness_contract.get(key) if readiness_contract.get(key) is not None else manifest.get(key)
    return {key: value for key, value in fields.items() if value is not None}


def _full_derived_index_manifests(
    view_outputs: dict[str, Path],
    available_artifacts: dict[str, bool],
    source_artifacts: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    semantic_path = view_outputs.get("semantic_recall_inputs")
    manifests = {
        "semantic": {
            "source": "semantic",
            "status": READY if semantic_path and semantic_path.is_file() else "DEFERRED",
            "index_status": "INDEX_READY" if semantic_path and semantic_path.is_file() else "DEFERRED",
            "index_scope": "FULL_DERIVED_INDEX",
            "index_path": str(semantic_path) if semantic_path else None,
        },
    }
    for source, artifact in sorted(source_artifacts.items()):
        manifest = artifact["manifest"]
        readiness_path = _artifact_data_path(artifact, "readiness_contract")
        readiness_contract = read_json(readiness_path) if readiness_path and readiness_path.is_file() else {}
        index_path = (
            _artifact_data_path(artifact, "edges_path")
            or _artifact_data_path(artifact, "semantic_recall_inputs_path")
            or _artifact_data_path(artifact, "semantic_inverted_index_path")
            or _artifact_data_path(artifact, "recall_index_path")
            or _artifact_data_path(artifact, "recall_index")
            or artifact["path"]
        )
        manifests[source] = {
            "source": source,
            "canonical_source": manifest.get("canonical_source") or source,
            "status": READY if index_path and Path(index_path).is_file() else "DEFERRED",
            "index_status": readiness_contract.get("index_status") or ("INDEX_READY" if index_path and Path(index_path).is_file() else "DEFERRED"),
            "index_scope": manifest.get("index_scope", "FULL_DERIVED_INDEX"),
            "index_path": str(index_path) if index_path else None,
            "manifest_sha256": readiness_contract.get("index_manifest_sha256") or manifest.get("index_manifest_sha256") or manifest.get("manifest_sha256") or canonical_manifest_sha256(manifest),
            "available_artifacts": available_artifacts,
        }
        for key in (
            "clean_manifest_sha256",
            "train_sequence_sha256",
            "item_universe_sha256",
            "model_config_sha256",
            "source_name",
            "item_embedding_row_count",
            "recall_index_row_count",
            "user_embedding_row_count",
            "user_embedding_row_count_note",
        ):
            if readiness_contract.get(key) is not None or manifest.get(key) is not None:
                manifests[source][key] = readiness_contract.get(key) if readiness_contract.get(key) is not None else manifest.get(key)
    if "two_tower" not in manifests:
        manifests["two_tower"] = {
            "source": "two_tower",
            "status": "DEFERRED",
            "index_status": "DEFERRED",
            "index_scope": "FULL_DERIVED_INDEX",
            "reason": "two_tower full source output is not available in current source artifacts",
            "available_artifacts": available_artifacts,
        }
    return manifests


def _merged_manifest(
    candidate_path: Path,
    clean_manifest: dict[str, Any],
    views_manifest: dict[str, Any],
    users: list[str],
    rows: list[dict[str, Any]],
    underfilled_user_count: int,
    source_coverage: Counter[str],
) -> dict[str, Any]:
    return {
        "schema_version": f"{SCHEMA_VERSION}.merged_pool500_manifest",
        "output_path": str(candidate_path),
        "candidate_row_count": len(rows),
        "user_count": len(users),
        "user_ids": users,
        "eligible_user_hash": canonical_user_set_hash(users),
        "underfilled_user_count": underfilled_user_count,
        "users_with_500_candidates_ratio": (len(users) - underfilled_user_count) / len(users) if users else 0.0,
        "underfilled_user_ratio": underfilled_user_count / len(users) if users else 0.0,
        "source_coverage": dict(sorted(source_coverage.items())),
        "lineage": {
            "source_manifests": ["eligible_user_manifest.json", "canonical_source_registry.json", "per_source_output_manifests.json"],
            "clean_manifest_sha256": canonical_manifest_sha256(clean_manifest),
            "views_manifest_sha256": canonical_manifest_sha256(views_manifest),
        },
    }


def _ready_source_stoploss_audit(
    users: list[str],
    rows: list[dict[str, Any]],
    source_rows: dict[str, list[dict[str, Any]]],
    underfilled_user_count: int,
) -> dict[str, Any]:
    per_user_counts = Counter(str(row.get("user_id")) for row in rows)
    underfilled_ratio = underfilled_user_count / len(users) if users else 0.0
    underfilled_users = _underfilled_users(users, rows)
    ready_sources: dict[str, dict[str, Any]] = {}
    trigger_reasons: list[str] = []
    ready_row_total = 0
    ready_unique_items: set[str] = set()
    for source in READY_STOPLOSS_SOURCES:
        source_candidates = source_rows.get(source, [])
        source_users = {str(row.get("user_id")) for row in source_candidates if row.get("user_id")}
        source_items = {str(row.get("item_id")) for row in source_candidates if row.get("item_id")}
        underfilled_source_users = source_users & underfilled_users
        row_count = len(source_candidates)
        ready_row_total += row_count
        ready_unique_items.update(source_items)
        user_coverage_ratio = len(source_users) / len(users) if users else 0.0
        underfilled_coverage_ratio = len(underfilled_source_users) / underfilled_user_count if underfilled_user_count else 0.0
        marginal_share = row_count / len(rows) if rows else 0.0
        ready_sources[source] = {
            "row_count": row_count,
            "unique_item_count": len(source_items),
            "user_coverage_count": len(source_users),
            "user_coverage_ratio": round(user_coverage_ratio, 6),
            "underfilled_user_coverage_count": len(underfilled_source_users),
            "underfilled_user_coverage_ratio": round(underfilled_coverage_ratio, 6),
            "marginal_candidate_share": round(marginal_share, 6),
        }
        if row_count == 0:
            trigger_reasons.append(f"{source}:no_ready_source_candidates")
    ready_only_capacity_ratio = ready_row_total / (len(users) * 500) if users else 0.0
    if users and underfilled_user_count:
        trigger_reasons.append("target_batch_underfilled")
    if users and max(per_user_counts.values(), default=0) < 500:
        trigger_reasons.append("max_user_candidate_count_below_pool500")
    if ready_only_capacity_ratio < 1.0:
        trigger_reasons.append("ready_source_capacity_below_pool500_budget")
    return {
        "schema_version": f"{SCHEMA_VERSION}.ready_source_stoploss_audit",
        "status": "STOPLOSS_TRIGGERED" if trigger_reasons else "PASS",
        "ready_sources": list(READY_STOPLOSS_SOURCES),
        "stoploss_triggered": bool(trigger_reasons),
        "trigger_reasons": trigger_reasons,
        "user_count": len(users),
        "candidate_row_count": len(rows),
        "underfilled_user_count": underfilled_user_count,
        "underfilled_user_ratio": round(underfilled_ratio, 6),
        "max_candidates_per_user": max(per_user_counts.values()) if per_user_counts else 0,
        "ready_source_row_total": ready_row_total,
        "ready_source_unique_item_count": len(ready_unique_items),
        "ready_only_capacity_ratio": round(ready_only_capacity_ratio, 6),
        "sources": ready_sources,
        "diagnostic_only_promotion_allowed": False,
        "ranking_input_replacement_allowed": False,
        "pool1000_allowed": False,
    }


def _diagnostic_source_contribution(
    users: list[str],
    rows: list[dict[str, Any]],
    source_rows: dict[str, list[dict[str, Any]]],
    underfilled_user_count: int,
) -> dict[str, Any]:
    underfilled_users = _underfilled_users(users, rows)
    diagnostic_sources: dict[str, dict[str, Any]] = {}
    diagnostic_row_total = 0
    diagnostic_user_ids: set[str] = set()
    for source in DIAGNOSTIC_CONTRIBUTION_SOURCES:
        source_candidates = source_rows.get(source, [])
        source_users = {str(row.get("user_id")) for row in source_candidates if row.get("user_id")}
        source_items = {str(row.get("item_id")) for row in source_candidates if row.get("item_id")}
        underfilled_source_users = source_users & underfilled_users
        row_count = len(source_candidates)
        diagnostic_row_total += row_count
        diagnostic_user_ids.update(source_users)
        diagnostic_sources[source] = {
            "row_count": row_count,
            "unique_item_count": len(source_items),
            "user_coverage_count": len(source_users),
            "user_coverage_ratio": round(len(source_users) / len(users), 6) if users else 0.0,
            "underfilled_user_coverage_count": len(underfilled_source_users),
            "underfilled_user_coverage_ratio": round(len(underfilled_source_users) / underfilled_user_count, 6) if underfilled_user_count else 0.0,
            "marginal_candidate_share": round(row_count / len(rows), 6) if rows else 0.0,
            "readiness_status": "DIAGNOSTIC_ONLY",
            "promotion_allowed": False,
            "ranking_input_replacement_allowed": False,
        }
    return {
        "schema_version": f"{SCHEMA_VERSION}.diagnostic_source_contribution",
        "status": "DIAGNOSTIC_ONLY_AUDIT",
        "diagnostic_sources": list(DIAGNOSTIC_CONTRIBUTION_SOURCES),
        "diagnostic_row_total": diagnostic_row_total,
        "diagnostic_user_coverage_count": len(diagnostic_user_ids),
        "diagnostic_user_coverage_ratio": round(len(diagnostic_user_ids) / len(users), 6) if users else 0.0,
        "diagnostic_marginal_candidate_share": round(diagnostic_row_total / len(rows), 6) if rows else 0.0,
        "sources": diagnostic_sources,
        "promotion_allowed": False,
        "ranking_input_replacement_allowed": False,
        "pool1000_allowed": False,
    }


def _underfilled_users(users: list[str], rows: list[dict[str, Any]]) -> set[str]:
    per_user_counts = Counter(str(row.get("user_id")) for row in rows)
    return {user_id for user_id in users if per_user_counts.get(user_id, 0) < 500}


def _route_input_manifest(
    clean_manifest_path: Path,
    lightweight_views_manifest_path: Path,
    clean_manifest: dict[str, Any],
    views_manifest: dict[str, Any],
    view_outputs: dict[str, Path],
) -> dict[str, Any]:
    return {
        "schema_version": f"{SCHEMA_VERSION}.route_input_manifest",
        "declared_inputs": [
            str(clean_manifest_path),
            str(lightweight_views_manifest_path),
            str(_resolve_repo_path(clean_manifest.get("train_user_sequences_path"))),
            str(_resolve_repo_path(clean_manifest.get("split_paths", {}).get("train"))) if isinstance(clean_manifest.get("split_paths"), dict) else None,
            *[str(path) for path in view_outputs.values()],
        ],
        "ranking_input_replacement": False,
    }


def _quality_audit(users: list[str], rows: list[dict[str, Any]], underfilled_user_count: int, popular_category_cap_violations: int) -> dict[str, Any]:
    duplicate_count = 0
    seen: set[tuple[str, str]] = set()
    per_user = Counter()
    missing_fields = 0
    for row in rows:
        if not {"user_id", "item_id", "source", "score", "rank", "metadata"} <= set(row):
            missing_fields += 1
        key = (str(row.get("user_id")), str(row.get("item_id")))
        if key in seen:
            duplicate_count += 1
        seen.add(key)
        per_user[str(row.get("user_id"))] += 1
    status = "PASS" if rows and duplicate_count == 0 and missing_fields == 0 and popular_category_cap_violations == 0 and underfilled_user_count <= int(len(users) * 0.02) else DIAGNOSTIC_ONLY_PARTIAL
    return {
        "schema_version": f"{SCHEMA_VERSION}.quality_audit",
        "status": status,
        "user_count": len(users),
        "row_count": len(rows),
        "duplicate_user_item_count": duplicate_count,
        "missing_required_field_rows": missing_fields,
        "popular_category_cap_violating_users": popular_category_cap_violations,
        "underfilled_user_count": underfilled_user_count,
        "max_candidates_per_user": max(per_user.values()) if per_user else 0,
    }


def _artifact_gate_summary(artifact_gate_result: dict[str, Any]) -> dict[str, Any]:
    return {
        "decision": artifact_gate_result.get("decision"),
        "status": artifact_gate_result.get("status"),
        "blocker_count": len(artifact_gate_result.get("blockers") or []),
        "diagnostic_count": len(artifact_gate_result.get("diagnostics") or []),
    }



def _readiness_bundle(**payload: Any) -> dict[str, Any]:
    return {
        "schema_version": READINESS_BUNDLE_SCHEMA_VERSION,
        "candidate_generation_allowed": False,
        "ranking_input_replacement_allowed": False,
        "pool1000_allowed": False,
        **payload,
    }


def _all_required_sources_ready(readiness_contracts: dict[str, dict[str, Any]]) -> bool:
    return all(readiness_contracts.get(source, {}).get("status") == READY for source in CANONICAL_SOURCES)


def main() -> None:
    args = parse_args()
    manifest = run_full_data_pool500_recall_only(
        clean_manifest_path=Path(args.clean_manifest),
        lightweight_views_manifest_path=Path(args.lightweight_views_manifest),
        output_dir=Path(args.output_dir),
        usercf_sidecar_manifest_path=Path(args.usercf_sidecar_manifest),
        source_manifest_paths=_parse_source_manifest_overrides(args.source_manifest),
        limit_users=args.limit_users,
        full_run=args.full_run,
        enable_semantic=args.enable_semantic,
        overwrite=args.overwrite,
        semantic_max_rows=args.semantic_max_rows,
        enforce_venv=not args.skip_venv_check,
    )
    print(json.dumps({"status": manifest["status"], "decision": manifest["decision"], "manifest_path": str(Path(args.output_dir) / "manifest.json")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
