from __future__ import annotations

import argparse
import json
import math
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
    semantic_candidates_for_user,
    semantic_title_category_expansion_candidates_for_user,
    two_tower_candidates_for_user,
)
from rs_core.recsys.types import RecallCandidate
from rs_core.recsys.vector_index import VectorIndex, average_vectors
from rs_core.workflow.full_data_pool500_route_gate import (
    CANONICAL_SOURCES,
    DIAGNOSTIC_ONLY_PARTIAL,
    READINESS_BUNDLE_SCHEMA_VERSION,
    READY,
    STOP,
    build_canonical_source_registry,
    build_pool500_shadow_evidence,
    canonical_manifest_sha256,
    canonical_user_set_hash,
    full_data_pool500_artifact_gate,
    validate_pool500_shadow_evidence,
    validate_readiness_bundle,
)
from rs_lab.experiments.recall.pool500.fallback_completion import (
    Pool500FallbackCompletionConfig,
    build_completion_audit_bundle,
    build_fallback_completion_context,
    complete_pool500_for_user,
)

SCHEMA_VERSION = "full_data_pool500_recall_only_generation_v1"
DEFAULT_CLEAN_MANIFEST = ROOT / "data" / "processed" / "amazon_2023_recall_clean_full" / "manifest.json"
DEFAULT_LIGHTWEIGHT_VIEWS_MANIFEST = ROOT / "data" / "processed" / "amazon_2023_recall_views_full_lightweight" / "manifest.json"
DEFAULT_OUTPUT_DIR = ROOT / "outputs" / "recall" / "full_data_pool500_recall_only"
DEFAULT_SOURCE_MANIFESTS = {
    "itemcf_weak": ROOT / "outputs" / "recall" / "pool500_method_sources" / "itemcf_weak" / "target500_train_weak_edges_v1" / "source_index_manifest.json",
    "itemcf_strong": ROOT / "outputs" / "recall" / "pool500_method_sources" / "itemcf_strong" / "itemcf_strong_20260519T0945Z" / "source_index_manifest.json",
    "usercf_recall": ROOT / "outputs" / "recall" / "pool500_method_sources" / "usercf_recall" / "usercf_recall_pool500_heavy_probe_train_only_20260520" / "source_index_manifest.json",
    "swing_recall": ROOT / "outputs" / "recall" / "pool500_method_sources" / "swing_recall" / "target_slice_diagnostic_v1" / "source_index_manifest.json",
    "semantic_title_category_expansion": ROOT / "outputs" / "recall" / "pool500_method_sources" / "semantic_title_category_expansion" / "target500_semantic_title_category_v1" / "source_index_manifest.json",
    "co_visit_fallback_repair": ROOT / "outputs" / "recall" / "pool500_method_sources" / "co_visit_fallback_repair" / "target_slice_20260519_0001" / "source_index_manifest.json",
    "two_tower": ROOT / "outputs" / "recall" / "pool500_full_sources" / "two_tower_target500_slice_expanded" / "source_index_manifest.json",
}
DEFAULT_USERCF_SIDECAR_MANIFEST = DEFAULT_SOURCE_MANIFESTS["usercf_recall"]
DEFAULT_SMOKE_LIMIT_USERS = 1000
FILL_ORDER = [
    "semantic_title_category_expansion",
    "two_tower",
    "co_visit_fallback_repair",
    "usercf_recall",
    "swing_recall",
    "itemcf",
    "category",
    "popular",
]
MAIN_ROUTE_SOURCE_MINIMUMS = {
    "semantic_title_category_expansion": 40,
    "two_tower": 10,
    "co_visit_fallback_repair": 20,
    "usercf_recall": 10,
    "swing_recall": 10,
}
MAIN_ROUTE_SOURCE_MAXIMUMS = {"popular": 40}
SOURCE_ALIASES = {
    "metadata_neighbor_recall": "co_visit_fallback_repair",
    "category_recall_items": "category",
    "category_top_items": "category",
    "category_long_tail_recall": "category",
}
READY_STOPLOSS_SOURCES = ("category", "popular", "swing_recall")
DIAGNOSTIC_CONTRIBUTION_SOURCES = ("usercf_recall", "itemcf_weak", "itemcf_strong")
BATCH_SCOPED_DEFERRED_SOURCES = {"semantic", "semantic_title_category_expansion", "co_visit_fallback_repair"}
GENERATION_SOURCE_CONFIG = {
    "candidate_pool_size": 500,
    "candidate_pool_strategy": "balanced_source_budget",
    "candidate_source_minimums": MAIN_ROUTE_SOURCE_MINIMUMS,
    "candidate_source_maximums": MAIN_ROUTE_SOURCE_MAXIMUMS,
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
    "semantic_enabled": False,
    "semantic_per_user": 0,
    "semantic_min_overlap": 2,
    "semantic_score_mode": "idf_seed_aware",
    "semantic_seed_window": 20,
    "semantic_per_seed": 20,
    "semantic_max_bucket_candidates": 5000,
    "metadata_neighbor_enabled": True,
    "metadata_neighbor_seed_window": 20,
    "metadata_neighbor_per_seed": 20,
    "metadata_neighbor_per_user": 30,
    "metadata_neighbor_min_token_overlap": 1,
    "metadata_neighbor_max_bucket_candidates": 500,
    "usercf_enabled": True,
    "usercf_per_user": 30,
    "swing_enabled": True,
    "swing_per_user": 30,
    "swing_per_seed": 20,
    "two_tower_enabled": True,
    "two_tower_per_user": 30,
    "two_tower_query_batch_size": 10,
    "semantic_title_category_expansion": {
        "enabled": True,
        "per_user": 20,
        "per_seed": 10,
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
    source_target_user_ids = _source_aligned_target_user_ids(source_artifacts) if limit_users > 0 else []
    batch_sequences = _load_batch_sequences(sequence_path, limit_users, source_target_user_ids)
    popular = load_popular_candidates(view_outputs["popular_recall"], limit=10000)
    category_top = load_category_candidates(view_outputs["category_top_items"])
    item_category = _load_item_category(view_outputs["category_recall_items"])
    itemcf_weak = _load_source_itemcf(source_artifacts.get("itemcf_weak"), view_outputs.get("itemcf_recall_weak"), "itemcf_weak")
    itemcf_strong = _load_source_itemcf(source_artifacts.get("itemcf_strong"), view_outputs.get("itemcf_recall_strong"), "itemcf_strong")
    semantic_artifact = source_artifacts.get("semantic_title_category_expansion")
    semantic_source_path = _artifact_data_path(semantic_artifact, "semantic_recall_inputs_path") if semantic_artifact else None
    semantic_source_path = semantic_source_path or view_outputs["semantic_recall_inputs"]
    semantic_index = _load_batch_semantic_index(semantic_source_path, batch_sequences, semantic_max_rows) if enable_semantic else {}
    semantic_input_manifest = _semantic_input_manifest(semantic_source_path, semantic_index, batch_sequences, semantic_max_rows, enable_semantic)
    usercf_recall = _load_optional_usercf(source_artifacts.get("usercf_recall", {}).get("path"))
    swing_recall = _load_optional_swing(source_artifacts.get("swing_recall", {}).get("path"))
    pregenerated_recall = _load_pregenerated_recall_sources(
        source_artifacts,
        {"semantic_title_category_expansion", "co_visit_fallback_repair"},
    )
    two_tower_index = _load_optional_two_tower(source_artifacts.get("two_tower"))
    generation_config = dict(GENERATION_SOURCE_CONFIG)
    if not enable_semantic:
        generation_config.update({
            "semantic_enabled": False,
            "metadata_neighbor_enabled": False,
            "semantic_title_category_expansion": {"enabled": False},
        })
    _apply_source_generation_overrides(generation_config, source_artifacts)
    two_tower_recall = _precompute_two_tower_recall(batch_sequences, two_tower_index, generation_config)
    fallback_config = Pool500FallbackCompletionConfig()
    fallback_context = build_fallback_completion_context(
        batch_sequences=batch_sequences,
        clean_manifest=clean_manifest,
        view_outputs=view_outputs,
        config=fallback_config,
    )

    rows: list[dict[str, Any]] = []
    source_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    semantic_candidate_diagnostics: dict[str, dict[str, Any]] = {}
    fallback_audit_inputs: list[dict[str, Any]] = []
    users: list[str] = []
    underfilled_user_count = 0
    source_coverage: Counter[str] = Counter()
    popular_category_cap_violations = 0
    processed_users = 0
    for sequence in batch_sequences:
        user_id = str(sequence.get("user_id", ""))
        if not user_id:
            continue
        baseline_config = _semantic_disabled_config(generation_config)
        baseline_candidates, _baseline_fallback_used = merge_for_user(
            sequence,
            popular,
            itemcf_weak,
            itemcf_strong,
            category_top,
            item_category,
            baseline_config,
            semantic_index={},
            two_tower_index=two_tower_index,
            item_graph={},
            two_tower_seed={},
            graph_walk_seed={},
            usercf_recall=usercf_recall,
            swing_recall=swing_recall,
            two_tower_recall=two_tower_recall,
            pregenerated_recall=pregenerated_recall,
        )
        baseline_candidates = _enforce_popular_category_cap(baseline_candidates)
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
            two_tower_recall=two_tower_recall,
            pregenerated_recall=pregenerated_recall,
        )
        candidates = _enforce_popular_category_cap(candidates)
        completion = complete_pool500_for_user(
            sequence=sequence,
            existing_candidates=candidates,
            context=fallback_context,
            config=fallback_config,
        )
        candidates = completion.candidates
        fallback_audit_inputs.append(completion.audit_input)
        if enable_semantic:
            semantic_candidate_diagnostics[user_id] = _semantic_candidate_diagnostic_for_user(
                sequence,
                semantic_index,
                generation_config,
                baseline_candidates,
                candidates,
            )
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
                    **candidate.metadata,
                    "category": candidate.category,
                    "source_scores": {source: float(score) for source, score in sorted(candidate.source_scores.items())},
                },
            }
            rows.append(row)
            for source in canonical_sources:
                source_rows[source].append(row)
        if popular_category_count > 175:
            popular_category_cap_violations += 1

    fallback_completion_audit, fallback_completion_validation = build_completion_audit_bundle(fallback_audit_inputs, fallback_config)
    fallback_completion_audit_path = output_dir / "fallback_completion_audit.json"
    fallback_completion_validation_path = output_dir / "fallback_completion_validation.json"
    fallback_completion_resource_audit_path = output_dir / "fallback_completion_resource_audit.json"
    fallback_added_row_count = sum(int(item.get("fallback_added_count", 0)) for item in fallback_audit_inputs)
    users_completed_by_fallback = sum(
        1
        for item in fallback_audit_inputs
        if int(item.get("fallback_added_count", 0)) > 0 and int(item.get("final_candidate_count", 0)) >= 500
    )

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
    semantic_input_manifest_path = output_dir / "semantic_input_manifest.json"
    diagnostic_candidate_manifest = _diagnostic_candidate_manifest(
        users,
        rows,
        source_rows,
        semantic_candidate_diagnostics,
        semantic_input_manifest_path,
    )
    diagnostic_candidate_manifest_path = output_dir / "diagnostic_candidate_manifest.json"
    semantic_no_holdout_audit = _semantic_no_holdout_audit(clean_manifest_path, lightweight_views_manifest_path, semantic_input_manifest)
    semantic_no_holdout_audit_path = output_dir / "semantic_no_holdout_audit.json"
    semantic_resource_audit = _semantic_resource_audit(semantic_input_manifest, diagnostic_candidate_manifest)
    semantic_resource_audit_path = output_dir / "semantic_resource_audit.json"
    final_merge_manifest = _final_merge_manifest(merged_manifest, users, rows)
    final_merge_manifest_path = output_dir / "final_merge_manifest.json"
    underfill_audit = _underfill_audit(users, rows, underfilled_user_count)
    underfill_audit_path = output_dir / "underfill_audit.json"
    source_contribution_audit = _source_contribution_audit(users, rows, source_rows, underfilled_user_count)
    source_contribution_audit_path = output_dir / "source_contribution_audit.json"
    source_overlap_audit = _source_overlap_audit(source_rows)
    source_overlap_audit_path = output_dir / "source_overlap_audit.json"
    final_resource_audit = _final_resource_audit(users, rows, source_rows, semantic_resource_audit, limit_users, full_run, semantic_max_rows)
    final_resource_audit_path = output_dir / "final_resource_audit.json"
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
        no_holdout_audit={"status": semantic_no_holdout_audit["status"]},
        ranking_registry_check={"status": "PASS", "ranking_input_replacement_allowed": False},
        final_merged_candidate_manifest=final_merge_manifest,
        eligible_user_manifest=eligible_user_manifest,
        canonical_source_registry_sha256=canonical_manifest_sha256(canonical_source_registry),
    )
    readiness_result = validate_readiness_bundle(readiness_bundle)
    final_readiness_contract = _final_readiness_contract(
        artifact_gate_result=artifact_gate_result,
        readiness_bundle=readiness_bundle,
        readiness_bundle_result=readiness_result,
        quality_audit=quality_audit,
        underfill_audit=underfill_audit,
        source_contribution_audit=source_contribution_audit,
        source_overlap_audit=source_overlap_audit,
        final_resource_audit=final_resource_audit,
        no_holdout_audit=semantic_no_holdout_audit,
    )
    final_readiness_contract_path = output_dir / "final_readiness_contract.json"
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
        "fallback_completion": {
            "enabled": True,
            "users_completed_by_fallback": users_completed_by_fallback,
            "fallback_added_row_count": fallback_added_row_count,
            "audit_path": str(fallback_completion_audit_path),
            "validation_path": str(fallback_completion_validation_path),
            "resource_audit_path": str(fallback_completion_resource_audit_path),
            "promotion_allowed": False,
            "ranking_input_replacement_allowed": False,
            "pool1000_allowed": False,
            "full_pool500_ready_declared": False,
        },
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
            "semantic_input_manifest": str(semantic_input_manifest_path),
            "diagnostic_candidate_manifest": str(diagnostic_candidate_manifest_path),
            "semantic_no_holdout_audit": str(semantic_no_holdout_audit_path),
            "semantic_resource_audit": str(semantic_resource_audit_path),
            "final_merge_manifest": str(final_merge_manifest_path),
            "underfill_audit": str(underfill_audit_path),
            "source_contribution_audit": str(source_contribution_audit_path),
            "source_overlap_audit": str(source_overlap_audit_path),
            "final_resource_audit": str(final_resource_audit_path),
            "final_readiness_contract": str(final_readiness_contract_path),
            "readiness_bundle": str(output_dir / "readiness_bundle.json"),
            "readiness_result": str(output_dir / "readiness_result.json"),
            "pool500_shadow_evidence": str(output_dir / "pool500_shadow_evidence.json"),
            "pool500_shadow_evidence_validation": str(output_dir / "pool500_shadow_evidence_validation.json"),
            "fallback_completion_audit": str(fallback_completion_audit_path),
            "fallback_completion_validation": str(fallback_completion_validation_path),
            "fallback_completion_resource_audit": str(fallback_completion_resource_audit_path),
        },
        "pool500_shadow_evidence_validation": shadow_evidence_validation,
        "blockers": readiness_result["blockers"],
        "diagnostics": [
            *readiness_result["diagnostics"],
            {
                "code": "POOL500_FALLBACK_COMPLETION_SHADOW_ONLY",
                "evidence": {
                    "fallback_added_row_count": fallback_added_row_count,
                    "users_completed_by_fallback": users_completed_by_fallback,
                    "promotion_allowed": False,
                },
            },
        ],
    }
    write_json(output_dir / "eligible_user_manifest.json", eligible_user_manifest)
    write_json(output_dir / "per_source_readiness_contracts.json", per_source_readiness_contracts)
    write_json(output_dir / "per_source_output_manifests.json", per_source_output_manifests)
    write_json(output_dir / "full_derived_index_manifests.json", full_derived_index_manifests)
    write_json(output_dir / "merged_pool500_manifest.json", merged_manifest)
    write_json(output_dir / "route_input_manifest.json", route_input_manifest)
    write_json(ready_source_stoploss_audit_path, ready_source_stoploss_audit)
    write_json(diagnostic_source_contribution_path, diagnostic_source_contribution)
    write_json(semantic_input_manifest_path, semantic_input_manifest)
    write_json(diagnostic_candidate_manifest_path, diagnostic_candidate_manifest)
    write_json(semantic_no_holdout_audit_path, semantic_no_holdout_audit)
    write_json(semantic_resource_audit_path, semantic_resource_audit)
    write_json(final_merge_manifest_path, final_merge_manifest)
    write_json(underfill_audit_path, underfill_audit)
    write_json(source_contribution_audit_path, source_contribution_audit)
    write_json(source_overlap_audit_path, source_overlap_audit)
    write_json(final_resource_audit_path, final_resource_audit)
    write_json(final_readiness_contract_path, final_readiness_contract)
    write_json(fallback_completion_audit_path, fallback_completion_audit)
    write_json(fallback_completion_validation_path, fallback_completion_validation)
    write_json(fallback_completion_resource_audit_path, fallback_context.resource_audit)
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


def _load_batch_sequences(sequence_path: Path, limit_users: int, priority_user_ids: list[str] | None = None) -> list[dict[str, Any]]:
    if not priority_user_ids:
        sequences = []
        for sequence in iter_jsonl(sequence_path):
            if not sequence.get("user_id"):
                continue
            sequences.append(sequence)
            if limit_users > 0 and len(sequences) >= limit_users:
                break
        return sequences

    priority_set = set(priority_user_ids)
    priority_sequences: dict[str, dict[str, Any]] = {}
    filler_sequences: list[dict[str, Any]] = []
    for sequence in iter_jsonl(sequence_path):
        user_id = str(sequence.get("user_id") or "")
        if not user_id:
            continue
        if user_id in priority_set:
            priority_sequences[user_id] = sequence
        elif limit_users <= 0 or len(filler_sequences) < limit_users:
            filler_sequences.append(sequence)
        if limit_users > 0 and len(priority_sequences) >= len(priority_set) and len(filler_sequences) >= limit_users:
            break
    selected = [priority_sequences[user_id] for user_id in priority_user_ids if user_id in priority_sequences]
    if limit_users <= 0:
        return selected
    selected_user_ids = {str(sequence.get("user_id") or "") for sequence in selected}
    for sequence in filler_sequences:
        if len(selected) >= limit_users:
            break
        user_id = str(sequence.get("user_id") or "")
        if user_id in selected_user_ids:
            continue
        selected.append(sequence)
        selected_user_ids.add(user_id)
    return selected


def _source_aligned_target_user_ids(source_artifacts: dict[str, dict[str, Any]]) -> list[str]:
    target_user_ids: list[str] = []
    seen: set[str] = set()
    for source in ("usercf_recall",):
        manifest = (source_artifacts.get(source) or {}).get("manifest") or {}
        for user_id in _source_manifest_target_user_ids(source_artifacts.get(source), manifest):
            if user_id not in seen:
                target_user_ids.append(user_id)
                seen.add(user_id)
    return target_user_ids


def _source_manifest_target_user_ids(artifact: dict[str, Any] | None, manifest: dict[str, Any]) -> list[str]:
    values = manifest.get("target_user_ids")
    if isinstance(values, list):
        return [str(user_id) for user_id in values if user_id]
    method_dataset_path = _artifact_data_path(artifact, "method_dataset_manifest") if artifact else None
    if method_dataset_path and method_dataset_path.is_file():
        method_dataset = read_json(method_dataset_path)
        values = method_dataset.get("target_user_ids")
        if isinstance(values, list):
            return [str(user_id) for user_id in values if user_id]
    eligible_path = _artifact_data_path(artifact, "eligible_user_quality_manifest") if artifact else None
    if eligible_path and eligible_path.is_file():
        eligible_manifest = read_json(eligible_path)
        profiles = eligible_manifest.get("profiles") if isinstance(eligible_manifest.get("profiles"), list) else []
        return [str(profile.get("user_id")) for profile in profiles if isinstance(profile, dict) and profile.get("user_id")]
    return []


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


def _load_pregenerated_recall_sources(source_artifacts: dict[str, dict[str, Any]], sources: set[str]) -> dict[str, list[RecallCandidate]]:
    by_user: dict[str, list[RecallCandidate]] = defaultdict(list)
    for source in sorted(sources):
        artifact = source_artifacts.get(source)
        candidate_path = _artifact_data_path(artifact, "candidates_path") or _artifact_data_path(artifact, "candidates") if artifact else None
        if candidate_path is None or not candidate_path.is_file():
            continue
        for row in iter_jsonl(candidate_path):
            user_id = str(row.get("user_id") or "")
            item_id = str(row.get("item_id") or row.get("parent_asin") or "")
            if not user_id or not item_id:
                continue
            source_scores = row.get("source_scores") if isinstance(row.get("source_scores"), dict) else {}
            score = source_scores.get(source, row.get("score", 0.0))
            metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
            by_user[user_id].append(
                RecallCandidate(
                    item_id=item_id,
                    source=source,
                    score=float(score or 0.0),
                    category=str(row.get("category") or metadata.get("category") or metadata.get("main_category") or ""),
                    metadata={**metadata, "pregenerated_source_manifest_path": str(artifact["path"])},
                )
            )
    for rows in by_user.values():
        rows.sort(key=lambda item: (-item.score, item.item_id))
    return by_user


def _load_optional_two_tower(artifact: dict[str, Any] | None) -> Any:
    path = _artifact_data_path(artifact, "recall_index_path") or _artifact_data_path(artifact, "recall_index") if artifact else None
    if path is None:
        path = _artifact_data_path(artifact, "artifact_manifest") if artifact else None
    if path is None or not path.is_file():
        return {}
    return load_two_tower_index(path)


def _apply_source_generation_overrides(config: dict[str, Any], source_artifacts: dict[str, dict[str, Any]]) -> None:
    allowed_keys = {
        "two_tower": ("two_tower_per_user", "two_tower_seed_window", "two_tower_query_batch_size"),
        "usercf_recall": ("usercf_per_user",),
        "itemcf_weak": ("itemcf_weak_per_seed", "itemcf_recent_positive_window"),
        "itemcf_strong": ("itemcf_strong_per_seed", "itemcf_recent_strong_window"),
        "swing_recall": ("swing_per_user", "swing_per_seed", "swing_seed_window"),
    }
    for source, keys in allowed_keys.items():
        manifest = (source_artifacts.get(source) or {}).get("manifest") or {}
        overrides = manifest.get("generation_config_overrides") if isinstance(manifest.get("generation_config_overrides"), dict) else {}
        for key in keys:
            value = overrides.get(key)
            if isinstance(value, int) and value > 0:
                config[key] = value


def _precompute_two_tower_recall(sequences: list[dict[str, Any]], two_tower_index: Any, config: dict[str, Any]) -> dict[str, list[RecallCandidate]]:
    if not config.get("two_tower_enabled") or not two_tower_index:
        return {}
    if not isinstance(two_tower_index, VectorIndex):
        return {str(sequence.get("user_id") or ""): two_tower_candidates_for_user(sequence, two_tower_index, config) for sequence in sequences if sequence.get("user_id")}
    limit = int(config.get("two_tower_per_user", 20))
    seed_window = int(config.get("two_tower_seed_window", 10))
    recency_decay = float(config.get("two_tower_recency_decay", 0.85))
    query_vectors = {}
    excluded_items = {}
    metadata_by_user = {}
    for sequence in sequences:
        user_id = str(sequence.get("user_id") or "")
        if not user_id:
            continue
        seen_items = set(sequence.get("recent_item_sequence", []))
        query_vector = two_tower_index.get_user_vector(user_id)
        if not query_vector:
            seed_items = list(dict.fromkeys(reversed(sequence.get("recent_positive_item_sequence", [])[-seed_window:])))
            query_vector = average_vectors([two_tower_index.get_item_vector(item_id) for item_id in seed_items], recency_decay)
        if query_vector:
            query_vectors[user_id] = query_vector
            excluded_items[user_id] = seen_items
            metadata_by_user[user_id] = {"two_tower_manifest_batch_mode": "batch_vector_search"}
    query_batch_size = max(1, int(config.get("two_tower_query_batch_size", 25)))
    search_results = {}
    query_user_ids = list(query_vectors)
    for start in range(0, len(query_user_ids), query_batch_size):
        batch_user_ids = query_user_ids[start : start + query_batch_size]
        batch_query_vectors = {user_id: query_vectors[user_id] for user_id in batch_user_ids}
        batch_excluded_items = {user_id: excluded_items[user_id] for user_id in batch_user_ids}
        search_results.update(two_tower_index.search_many(batch_query_vectors, limit=limit, excluded_items=batch_excluded_items))
    return {
        user_id: [
            RecallCandidate(
                item_id=result.item_id,
                source="two_tower",
                score=result.score,
                category=str(result.metadata.get("main_category") or result.metadata.get("category", "")),
                metadata=dict(result.metadata) | metadata_by_user.get(user_id, {}),
            )
            for result in results
        ]
        for user_id, results in search_results.items()
    }


def _load_item_category(path: Path) -> dict[str, str]:
    mapping = {}
    for row in iter_jsonl(path):
        item_id = row.get("parent_asin")
        if item_id:
            mapping[str(item_id)] = str(row.get("main_category") or row.get("category") or "")
    return mapping


def _semantic_disabled_config(config: dict[str, Any]) -> dict[str, Any]:
    disabled = dict(config)
    disabled.update({
        "semantic_enabled": False,
        "metadata_neighbor_enabled": False,
        "semantic_title_category_expansion": {"enabled": False},
    })
    return disabled


def _semantic_input_manifest(
    semantic_source_path: Path | None,
    semantic_index: dict[str, dict[str, Any]],
    sequences: list[dict[str, Any]],
    max_rows: int,
    enabled: bool,
) -> dict[str, Any]:
    seed_items = _batch_seed_items(sequences)
    title_count = 0
    category_count = 0
    clean_title_token_count = 0
    seed_item_coverage_count = 0
    for item_id, row in semantic_index.items():
        title = str(row.get("title") or row.get("title_clean") or "")
        category = str(row.get("main_category") or row.get("category") or "")
        clean_title_tokens = _clean_title_tokens(row)
        title_count += int(bool(title))
        category_count += int(bool(category))
        clean_title_token_count += int(bool(clean_title_tokens))
        seed_item_coverage_count += int(item_id in seed_items)
    item_universe_count = len(semantic_index)
    return {
        "schema_version": f"{SCHEMA_VERSION}.semantic_input_manifest",
        "status": "BATCH_SCOPED_DIAGNOSTIC" if enabled else "DISABLED",
        "source": "semantic_title_category_expansion",
        "semantic_source_path": str(semantic_source_path) if semantic_source_path else None,
        "batch_user_count": len(sequences),
        "batch_seed_item_count": len(seed_items),
        "semantic_max_rows": max_rows,
        "item_universe_count": item_universe_count,
        "item_universe_coverage": _coverage(seed_item_coverage_count, len(seed_items)),
        "title_coverage": _coverage(title_count, item_universe_count),
        "category_coverage": _coverage(category_count, item_universe_count),
        "clean_title_token_coverage": _coverage(clean_title_token_count, item_universe_count),
        "coverage_counts": {
            "title": title_count,
            "category": category_count,
            "clean_title_tokens": clean_title_token_count,
            "item_universe_seed_items": seed_item_coverage_count,
        },
        "readiness_status": "DEFERRED",
        "batch_scoped_evidence_only": True,
        "candidate_generation_allowed": False,
        "promotion_allowed": False,
        "ranking_input_replacement_allowed": False,
        "pool1000_allowed": False,
    }


def _semantic_candidate_diagnostic_for_user(
    sequence: dict[str, Any],
    semantic_index: dict[str, dict[str, Any]],
    config: dict[str, Any],
    baseline_candidates: list[Any],
    merged_candidates: list[Any],
) -> dict[str, Any]:
    semantic_rows = semantic_candidates_for_user(sequence, semantic_index, config)
    title_category_rows = semantic_title_category_expansion_candidates_for_user(sequence, semantic_index, config)
    generated_items = [candidate.item_id for candidate in [*semantic_rows, *title_category_rows] if candidate.item_id]
    unique_generated_items = set(generated_items)
    baseline_items = {candidate.item_id for candidate in baseline_candidates}
    merged_items = {candidate.item_id for candidate in merged_candidates}
    final_semantic_items = {
        candidate.item_id
        for candidate in merged_candidates
        if {"semantic", "semantic_title_category_expansion"} & set(candidate.sources)
    }
    return {
        "baseline_candidate_count": len(baseline_candidates),
        "final_candidate_count": len(merged_candidates),
        "semantic_candidate_generation_count": len(semantic_rows),
        "title_category_candidate_generation_count": len(title_category_rows),
        "generated_candidate_count": len(generated_items),
        "unique_generated_candidate_count": len(unique_generated_items),
        "duplicate_removed_count": len(generated_items) - len(unique_generated_items),
        "final_semantic_candidate_count": len(final_semantic_items),
        "marginal_contribution_count": len(final_semantic_items - baseline_items),
        "underfill_improved": len(baseline_candidates) < 500 and len(merged_candidates) > len(baseline_candidates),
        "final_gain_count": max(len(merged_items) - len(baseline_items), 0),
    }


def _diagnostic_candidate_manifest(
    users: list[str],
    rows: list[dict[str, Any]],
    source_rows: dict[str, list[dict[str, Any]]],
    semantic_candidate_diagnostics: dict[str, dict[str, Any]],
    semantic_input_manifest_path: Path,
) -> dict[str, Any]:
    generated_count = sum(item["generated_candidate_count"] for item in semantic_candidate_diagnostics.values())
    unique_generated_count = sum(item["unique_generated_candidate_count"] for item in semantic_candidate_diagnostics.values())
    duplicate_removed_count = sum(item["duplicate_removed_count"] for item in semantic_candidate_diagnostics.values())
    marginal_count = sum(item["marginal_contribution_count"] for item in semantic_candidate_diagnostics.values())
    improved_count = sum(int(item["underfill_improved"]) for item in semantic_candidate_diagnostics.values())
    semantic_rows = [*source_rows.get("semantic", []), *source_rows.get("semantic_title_category_expansion", [])]
    return {
        "schema_version": f"{SCHEMA_VERSION}.diagnostic_candidate_manifest",
        "status": "BATCH_SCOPED_DIAGNOSTIC",
        "source": "semantic_title_category_expansion",
        "semantic_input_manifest_path": str(semantic_input_manifest_path),
        "user_count": len(users),
        "candidate_row_count": len(rows),
        "semantic_final_row_count": len(semantic_rows),
        "candidate_generation_count": generated_count,
        "unique_generated_candidate_count": unique_generated_count,
        "duplicate_removal_count": duplicate_removed_count,
        "underfill_improved_user_count": improved_count,
        "underfill_improved_user_ratio": round(improved_count / len(users), 6) if users else 0.0,
        "marginal_contribution_count": marginal_count,
        "marginal_contribution_share": round(marginal_count / len(rows), 6) if rows else 0.0,
        "per_user": semantic_candidate_diagnostics,
        "readiness_status": "DEFERRED",
        "batch_scoped_evidence_only": True,
        "candidate_generation_allowed": False,
        "promotion_allowed": False,
        "ranking_input_replacement_allowed": False,
        "pool1000_allowed": False,
    }


def _semantic_no_holdout_audit(clean_manifest_path: Path, lightweight_views_manifest_path: Path, semantic_input_manifest: dict[str, Any]) -> dict[str, Any]:
    paths = [clean_manifest_path, lightweight_views_manifest_path]
    if semantic_input_manifest.get("semantic_source_path"):
        paths.append(Path(str(semantic_input_manifest["semantic_source_path"])))
    forbidden_tokens = ("holdout", "valid", "test", "clean_10000", "lopo", "youtube_dnn", "pool1000")
    forbidden_inputs = [str(path) for path in paths if _semantic_forbidden_path(path, forbidden_tokens)]
    return {
        "schema_version": f"{SCHEMA_VERSION}.semantic_no_holdout_audit",
        "status": "PASS" if not forbidden_inputs else "BLOCKED",
        "declared_inputs": [str(path) for path in paths],
        "forbidden_inputs": forbidden_inputs,
        "forbidden_tokens": list(forbidden_tokens),
        "batch_scoped_evidence_only": True,
        "candidate_generation_allowed": False,
        "promotion_allowed": False,
        "ranking_input_replacement_allowed": False,
        "pool1000_allowed": False,
    }


def _semantic_forbidden_path(path: Path, forbidden_tokens: tuple[str, ...]) -> bool:
    parts = [part.lower() for part in path.parts]
    filename = path.name.lower()
    for token in forbidden_tokens:
        if token in {"holdout", "valid", "test"}:
            if token in parts or filename.endswith(f".{token}.jsonl"):
                return True
            continue
        if any(token in part for part in parts):
            return True
    return False


def _semantic_resource_audit(semantic_input_manifest: dict[str, Any], diagnostic_candidate_manifest: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": f"{SCHEMA_VERSION}.semantic_resource_audit",
        "status": "PASS",
        "mode": "small_batch_diagnostic",
        "batch_user_count": semantic_input_manifest["batch_user_count"],
        "semantic_max_rows": semantic_input_manifest["semantic_max_rows"],
        "item_universe_count": semantic_input_manifest["item_universe_count"],
        "candidate_generation_count": diagnostic_candidate_manifest["candidate_generation_count"],
        "candidate_row_count": diagnostic_candidate_manifest["candidate_row_count"],
        "heavy_job": False,
        "full_run_claimed": False,
        "batch_scoped_evidence_only": True,
        "candidate_generation_allowed": False,
        "promotion_allowed": False,
        "ranking_input_replacement_allowed": False,
        "pool1000_allowed": False,
    }


def _coverage(numerator: int, denominator: int) -> dict[str, Any]:
    return {"count": numerator, "total": denominator, "ratio": round(numerator / denominator, 6) if denominator else 0.0}


def _clean_title_tokens(row: dict[str, Any]) -> set[str]:
    return {token for token in re.findall(r"[a-z0-9]+", str(row.get("title_clean") or "").lower()) if len(token) >= 3}


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
        status = "BATCH_SCOPED_DIAGNOSTIC" if source in BATCH_SCOPED_DEFERRED_SOURCES and rows else READY if rows else "DEFERRED"
        manifest = {
            "schema_version": f"{SCHEMA_VERSION}.source_output_manifest",
            "source": source,
            "status": status,
            "final_sources": [source] if rows and source not in BATCH_SCOPED_DEFERRED_SOURCES else [],
            "output_path": str(source_path),
            "row_count": len(rows),
            "manifest_sha256": canonical_manifest_sha256({"source": source, "ready": bool(rows) and source not in BATCH_SCOPED_DEFERRED_SOURCES}),
            "available_artifacts": available_artifacts,
            "batch_scoped_evidence_only": source in BATCH_SCOPED_DEFERRED_SOURCES,
            "promotion_allowed": False,
            "ranking_input_replacement_allowed": False,
            "pool1000_allowed": False,
        }
        if artifact:
            source_manifest = artifact["manifest"]
            manifest.update(
                {
                    "source_index_manifest_path": str(artifact["path"]),
                    "source_index_manifest_sha256": source_manifest.get("manifest_sha256") or source_manifest.get("source_index_manifest_sha256") or canonical_manifest_sha256(source_manifest),
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
        if source in BATCH_SCOPED_DEFERRED_SOURCES and ready:
            status = "BATCH_SCOPED_DIAGNOSTIC"
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


def _final_merge_manifest(merged_manifest: dict[str, Any], users: list[str], rows: list[dict[str, Any]]) -> dict[str, Any]:
    per_user_counts = Counter(str(row.get("user_id")) for row in rows)
    candidate_counts = [per_user_counts.get(user_id, 0) for user_id in users]
    return {
        **merged_manifest,
        "schema_version": f"{SCHEMA_VERSION}.final_merge_manifest",
        "status": "PASS" if users and all(count >= 500 for count in candidate_counts) else DIAGNOSTIC_ONLY_PARTIAL,
        "candidate_count_min": min(candidate_counts) if candidate_counts else 0,
        "candidate_count_p50": _percentile(candidate_counts, 0.5),
        "candidate_count_p90": _percentile(candidate_counts, 0.9),
        "candidate_count_max": max(candidate_counts) if candidate_counts else 0,
        "users_with_500_candidates": sum(1 for count in candidate_counts if count >= 500),
        "final_pool500_ready_claimed": False,
        "ranking_input_replacement_allowed": False,
        "pool1000_allowed": False,
    }


def _underfill_audit(users: list[str], rows: list[dict[str, Any]], underfilled_user_count: int) -> dict[str, Any]:
    per_user_counts = Counter(str(row.get("user_id")) for row in rows)
    remaining = [user_id for user_id in users if per_user_counts.get(user_id, 0) < 500]
    counts = [per_user_counts.get(user_id, 0) for user_id in users]
    return {
        "schema_version": f"{SCHEMA_VERSION}.underfill_audit",
        "status": "PASS" if users and not remaining else DIAGNOSTIC_ONLY_PARTIAL,
        "target_user_count": len(users),
        "users_with_500_candidates": len(users) - len(remaining),
        "underfilled_user_count": underfilled_user_count,
        "remaining_underfilled_user_count": len(remaining),
        "remaining_underfilled_users": remaining,
        "candidate_count_min": min(counts) if counts else 0,
        "candidate_count_p50": _percentile(counts, 0.5),
        "candidate_count_p90": _percentile(counts, 0.9),
        "candidate_count_max": max(counts) if counts else 0,
        "promotion_allowed": False,
        "ranking_input_replacement_allowed": False,
        "pool1000_allowed": False,
    }


def _source_contribution_audit(users: list[str], rows: list[dict[str, Any]], source_rows: dict[str, list[dict[str, Any]]], underfilled_user_count: int) -> dict[str, Any]:
    underfilled_users = _underfilled_users(users, rows)
    sources = {}
    for source in sorted(CANONICAL_SOURCES):
        candidates = source_rows.get(source, [])
        user_ids = {str(row.get("user_id")) for row in candidates if row.get("user_id")}
        items = {str(row.get("item_id")) for row in candidates if row.get("item_id")}
        status = "READY" if source in READY_STOPLOSS_SOURCES else "DIAGNOSTIC_ONLY" if source in DIAGNOSTIC_CONTRIBUTION_SOURCES else "DEFERRED"
        sources[source] = {
            "row_count": len(candidates),
            "unique_item_count": len(items),
            "user_coverage_count": len(user_ids),
            "user_coverage_ratio": round(len(user_ids) / len(users), 6) if users else 0.0,
            "underfilled_user_coverage_count": len(user_ids & underfilled_users),
            "underfilled_user_coverage_ratio": round(len(user_ids & underfilled_users) / underfilled_user_count, 6) if underfilled_user_count else 0.0,
            "marginal_candidate_share": round(len(candidates) / len(rows), 6) if rows else 0.0,
            "readiness_status": status,
            "promotion_allowed": False,
            "ranking_input_replacement_allowed": False,
            "pool1000_allowed": False,
        }
    return {
        "schema_version": f"{SCHEMA_VERSION}.source_contribution_audit",
        "status": "DIAGNOSTIC_ONLY_AUDIT",
        "candidate_row_count": len(rows),
        "user_count": len(users),
        "sources": sources,
        "ready_sources": list(READY_STOPLOSS_SOURCES),
        "diagnostic_sources": list(DIAGNOSTIC_CONTRIBUTION_SOURCES),
        "deferred_sources": sorted(CANONICAL_SOURCES - set(READY_STOPLOSS_SOURCES) - set(DIAGNOSTIC_CONTRIBUTION_SOURCES)),
        "promotion_allowed": False,
        "ranking_input_replacement_allowed": False,
        "pool1000_allowed": False,
    }


def _source_overlap_audit(source_rows: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    source_items = {
        source: {(str(row.get("user_id")), str(row.get("item_id"))) for row in rows if row.get("user_id") and row.get("item_id")}
        for source, rows in source_rows.items()
    }
    overlaps = {}
    for left in sorted(CANONICAL_SOURCES):
        left_items = source_items.get(left, set())
        overlaps[left] = {}
        for right in sorted(CANONICAL_SOURCES):
            if left == right:
                continue
            right_items = source_items.get(right, set())
            overlaps[left][right] = len(left_items & right_items)
    return {
        "schema_version": f"{SCHEMA_VERSION}.source_overlap_audit",
        "status": "DIAGNOSTIC_ONLY_AUDIT",
        "pairwise_user_item_overlap_count": overlaps,
        "promotion_allowed": False,
        "ranking_input_replacement_allowed": False,
        "pool1000_allowed": False,
    }


def _final_resource_audit(
    users: list[str],
    rows: list[dict[str, Any]],
    source_rows: dict[str, list[dict[str, Any]]],
    semantic_resource_audit: dict[str, Any],
    limit_users: int,
    full_run: bool,
    semantic_max_rows: int,
) -> dict[str, Any]:
    return {
        "schema_version": f"{SCHEMA_VERSION}.final_resource_audit",
        "status": "PASS",
        "mode": "full" if full_run and limit_users <= 0 else "diagnostic_limited",
        "target_user_count": len(users),
        "candidate_row_count": len(rows),
        "source_row_counts": {source: len(source_rows.get(source, [])) for source in sorted(CANONICAL_SOURCES)},
        "semantic_max_rows": semantic_max_rows,
        "semantic_resource_audit_status": semantic_resource_audit.get("status"),
        "heavy_job": bool(full_run and limit_users <= 0),
        "resource_guard_required": True,
        "promotion_allowed": False,
        "ranking_input_replacement_allowed": False,
        "pool1000_allowed": False,
    }


def _final_readiness_contract(
    *,
    artifact_gate_result: dict[str, Any],
    readiness_bundle: dict[str, Any],
    readiness_bundle_result: dict[str, Any],
    quality_audit: dict[str, Any],
    underfill_audit: dict[str, Any],
    source_contribution_audit: dict[str, Any],
    source_overlap_audit: dict[str, Any],
    final_resource_audit: dict[str, Any],
    no_holdout_audit: dict[str, Any],
) -> dict[str, Any]:
    audit_statuses = {
        "artifact_gate": artifact_gate_result.get("decision"),
        "quality_audit": quality_audit.get("status"),
        "underfill_audit": underfill_audit.get("status"),
        "source_contribution_audit": source_contribution_audit.get("status"),
        "source_overlap_audit": source_overlap_audit.get("status"),
        "final_resource_audit": final_resource_audit.get("status"),
        "no_holdout_audit": no_holdout_audit.get("status"),
    }
    blockers = [*artifact_gate_result.get("blockers", [])]
    diagnostics = [*artifact_gate_result.get("diagnostics", [])]
    if underfill_audit.get("remaining_underfilled_user_count", 0):
        diagnostics.append({"code": "POOL500_UNDERFILLED_USERS_REMAIN", "evidence": {"count": underfill_audit["remaining_underfilled_user_count"]}})
    decision = STOP if blockers else DIAGNOSTIC_ONLY_PARTIAL if diagnostics or any(status != "PASS" for status in audit_statuses.values()) else "FULL_POOL500_READY_CANDIDATE"
    return {
        "schema_version": f"{SCHEMA_VERSION}.final_readiness_contract",
        "status": "PASS" if decision == "FULL_POOL500_READY_CANDIDATE" else decision,
        "decision": decision,
        "readiness_bundle_schema_version": readiness_bundle.get("schema_version"),
        "readiness_bundle_result": readiness_bundle_result,
        "artifact_gate_decision": artifact_gate_result.get("decision"),
        "audit_statuses": audit_statuses,
        "candidate_generation_allowed": False,
        "promotion_allowed": False,
        "ranking_input_replacement_allowed": False,
        "pool1000_allowed": False,
        "final_pool500_ready_claimed": False,
        "blockers": blockers,
        "diagnostics": diagnostics,
    }


def _percentile(values: list[int], percentile: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, math.ceil(len(ordered) * percentile) - 1))
    return ordered[index]


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
