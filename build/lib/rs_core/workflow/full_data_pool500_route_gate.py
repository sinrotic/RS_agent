from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

from rs_core.common.io import read_json
from rs_core.recsys.recall import (
    CANONICAL_SOURCES,
    FINAL_SOURCE_WHITELIST,
    FORBIDDEN_SOURCE_LABELS,
    GROUP_SOURCE_EXPANSIONS,
    SOURCE_ALIASES,
    canonicalize_source_label,
    canonicalize_source_set,
)

SCHEMA_VERSION = "full_data_pool500_route_gate_v1"
ARTIFACT_GATE_SCHEMA_VERSION = "full_data_pool500_artifact_gate_v5"
READINESS_BUNDLE_SCHEMA_VERSION = "full_data_pool500_readiness_bundle_v1"
POOL500_SHADOW_EVIDENCE_SCHEMA_VERSION = "pool500_shadow_evidence_v1"
POOL500_SHADOW_MODE = "read_only_shadow_evidence"
POOL500_FULL_READY_SEMANTICS = "recall_artifact_readiness_only"
ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CLEAN_MANIFEST = ROOT / "data" / "processed" / "amazon_2023_recall_clean_full" / "manifest.json"
DEFAULT_LIGHTWEIGHT_VIEWS_MANIFEST = ROOT / "data" / "processed" / "amazon_2023_recall_views_full_lightweight" / "manifest.json"

POOL500_RECALL_READY = "POOL500_RECALL_READY"
FULL_POOL500_READY = "FULL_POOL500_READY"
DIAGNOSTIC_ONLY = "DIAGNOSTIC_ONLY"
DIAGNOSTIC_ONLY_PARTIAL = "DIAGNOSTIC_ONLY_PARTIAL"
STOP = "STOP"

READY = "READY"
READY_CANDIDATE = "READY_CANDIDATE"
BLOCKED = "BLOCKED"
FAILED = "FAILED"
DEFERRED = "DEFERRED"
DIAGNOSTIC_ONLY_STATUS = "DIAGNOSTIC_ONLY"
BATCH_SCOPED_DIAGNOSTIC = "BATCH_SCOPED_DIAGNOSTIC"
INDEX_READY = "INDEX_READY"
INDEX_MISSING = "INDEX_MISSING"
FULL_OUTPUT_READY = "FULL_OUTPUT_READY"
DIAGNOSTIC_OUTPUT_READY = "DIAGNOSTIC_OUTPUT_READY"
OUTPUT_MISSING = "OUTPUT_MISSING"
READINESS_STATUSES = {READY, READY_CANDIDATE, BLOCKED, FAILED, DEFERRED, DIAGNOSTIC_ONLY_STATUS, BATCH_SCOPED_DIAGNOSTIC}
INDEX_STATUSES = {INDEX_READY, INDEX_MISSING, BLOCKED, FAILED, DEFERRED, DIAGNOSTIC_ONLY_STATUS}
OUTPUT_STATUSES = {FULL_OUTPUT_READY, DIAGNOSTIC_OUTPUT_READY, OUTPUT_MISSING, BLOCKED, FAILED, DEFERRED, DIAGNOSTIC_ONLY_STATUS}
NON_READY_STATUSES = {READY_CANDIDATE, BLOCKED, FAILED, DEFERRED, DIAGNOSTIC_ONLY_STATUS, BATCH_SCOPED_DIAGNOSTIC}

FORBIDDEN_FINAL_ARTIFACT_TOKENS = {"legacy", "probe", "custom", "contract"}
FORBIDDEN_INPUT_FILENAMES = {
    "canonical_interactions.valid.jsonl",
    "canonical_interactions.test.jsonl",
    "canonical_items.all.jsonl",
    "user_sequences.valid.jsonl",
    "user_sequences.test.jsonl",
    "holdout.jsonl",
}
FORBIDDEN_INPUT_TOKENS = {
    "/valid/",
    "/validation/",
    "/test/",
    "/holdout/",
    "holdout",
    "lopo",
    "oracle",
    "/label/",
    "eval_label",
    "label_artifact",
    "canonical_items.all",
    "future_interactions",
    "future interactions",
    "eval_answers",
    "eval answers",
    "clean_10000",
    "recall_clean_10000",
    "clean_10k",
    "recall_clean_10k",
}
FORBIDDEN_CANDIDATE_READ_TOKENS = {"/valid/", "/test/", "valid_test", "evaluation_only", "holdout", "oracle"}
FORBIDDEN_SERVING_ITEM_UNIVERSE_TOKENS = {"all", "eval", "evaluation", "display_only", "display-only"}
REQUIRED_CANDIDATE_ARTIFACT_FIELDS = {
    "source",
    "train_only",
    "candidate_generation_allowed",
    "ranking_input_replacement_allowed",
    "promotion_allowed",
}
ALLOWED_ARTIFACT_ROLES = {"rag_evidence", "diagnostic_only", "recall_candidate_source"}
ROUTE_INFERENCE_TOKENS = {"glob", "latest", "log_inference", "log inference", "from_log", "infer_from_log"}
GENERATION_OPERATIONS = {"candidate_generation", "index_build", "model_training"}
LEAKAGE_SENSITIVE_OPERATIONS = GENERATION_OPERATIONS | {"budget_profiling"}
REPRESENTATIVE_PROBE_MARKERS = {
    "representative_sample_size": 500,
    "custom_index_scope_only": True,
    "feasibility_only": True,
    "candidate_generation_executed": False,
    "no_model_training_executed": True,
}
REQUIRED_LIGHTWEIGHT_OUTPUTS = {
    "popular_recall",
    "category_recall_items",
    "category_top_items",
    "semantic_recall_inputs",
    "semantic_inverted_index",
}
REQUIRED_CLEAN_MANIFEST_FIELDS = {
    "canonical_items_path",
    "train_user_sequences_path",
    "split_paths",
}
REQUIRED_JSONL_ROW_FIELDS = {"user_id", "item_id", "source", "score", "rank", "metadata"}
REQUIRED_TWO_TOWER_FULL_CLEAN_FIELDS = {
    "clean_manifest_sha256",
    "train_sequence_sha256",
    "item_universe_sha256",
    "model_config_sha256",
    "source_name",
    "canonical_source",
    "item_embedding_row_count",
    "recall_index_row_count",
    "index_scope",
}
FORBIDDEN_TWO_TOWER_ARTIFACT_TOKENS = {
    "clean_smoke_e2e",
    "amazon_2023_recall_clean_10000",
    "valid_test",
    "leave_one_positive_out",
    "holdout",
    "outputs/training/two_tower",
    "youtube_dnn",
}
DEFAULT_UNDERFILLED_THRESHOLD = 0


def full_data_pool500_route_gate(
    *,
    method_contract: dict[str, Any],
    index_manifest: dict[str, Any],
    clean_manifest: dict[str, Any] | None = None,
    lightweight_views_manifest: dict[str, Any] | None = None,
    observed_outputs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    clean_manifest = clean_manifest or _read_optional_json(DEFAULT_CLEAN_MANIFEST)
    lightweight_views_manifest = lightweight_views_manifest or _read_optional_json(DEFAULT_LIGHTWEIGHT_VIEWS_MANIFEST)
    method_audit = validate_method_contract(method_contract)
    index_audit = validate_index_manifest(index_manifest)
    foundation_audit = build_data_foundation_audit(clean_manifest, lightweight_views_manifest)
    leakage_audit = no_holdout_leakage_audit(_collect_declared_inputs(method_contract, index_manifest), GENERATION_OPERATIONS)
    diagnostic_audit = representative_probe_boundary(method_contract, index_manifest)
    partial_output_audit = reject_partial_outputs(observed_outputs or {})
    blockers = [
        *method_audit["blockers"],
        *index_audit["blockers"],
        *foundation_audit["blockers"],
        *leakage_audit["blockers"],
        *partial_output_audit["blockers"],
    ]
    if blockers:
        decision = STOP
    elif diagnostic_audit["diagnostic_only"]:
        decision = DIAGNOSTIC_ONLY
    else:
        decision = POOL500_RECALL_READY
    return {
        "schema_version": SCHEMA_VERSION,
        "decision": decision,
        "status": "PASS" if decision == POOL500_RECALL_READY else decision,
        "candidate_generation_allowed": decision == POOL500_RECALL_READY,
        "ranking_input_replacement_allowed": False,
        "pool1000_allowed": False,
        "legacy_reference_signature_pass_authority": False,
        "method_contract_audit": method_audit,
        "index_manifest_audit": index_audit,
        "data_foundation_audit": foundation_audit,
        "no_holdout_leakage_audit": leakage_audit,
        "representative_probe_audit": diagnostic_audit,
        "partial_output_audit": partial_output_audit,
        "blockers": blockers,
    }


def full_data_pool500_artifact_gate(
    *,
    eligible_user_manifest: dict[str, Any] | None = None,
    canonical_source_registry: dict[str, Any] | None = None,
    source_budget_contract: dict[str, Any] | None = None,
    per_source_readiness_contracts: dict[str, Any] | None = None,
    per_source_output_manifests: dict[str, Any] | None = None,
    full_derived_index_manifests: dict[str, Any] | None = None,
    merged_pool500_manifest: dict[str, Any] | None = None,
    merged_rows: list[dict[str, Any]] | None = None,
    route_input_manifest: dict[str, Any] | None = None,
    train_item_ids: set[str] | list[str] | tuple[str, ...] | None = None,
    underfilled_threshold: int = DEFAULT_UNDERFILLED_THRESHOLD,
) -> dict[str, Any]:
    eligible_user_manifest = eligible_user_manifest or {}
    registry = canonical_source_registry or build_canonical_source_registry()
    source_budget_contract = source_budget_contract or {}
    per_source_readiness_contracts = per_source_readiness_contracts or {}
    per_source_output_manifests = per_source_output_manifests or {}
    full_derived_index_manifests = full_derived_index_manifests or {}
    merged_pool500_manifest = merged_pool500_manifest or {}
    merged_rows = merged_rows or []
    route_input_manifest = route_input_manifest or {}

    registry_audit = validate_canonical_source_registry(registry)
    readiness_audit = validate_per_source_readiness(per_source_readiness_contracts, registry)
    route_audit = validate_route_input_manifest(route_input_manifest)
    budget_audit = validate_source_budget_contract(source_budget_contract)
    output_audit = validate_per_source_outputs(per_source_output_manifests, per_source_readiness_contracts)
    index_audit = validate_full_derived_index_manifests(full_derived_index_manifests, per_source_readiness_contracts)
    two_tower_audit = validate_two_tower_full_clean_artifact(
        source_manifest=per_source_readiness_contracts.get("two_tower") or per_source_readiness_contracts.get("youtube_dnn") or {},
        index_manifest=full_derived_index_manifests.get("two_tower") or full_derived_index_manifests.get("youtube_dnn") or {},
        output_manifest=per_source_output_manifests.get("two_tower") or per_source_output_manifests.get("youtube_dnn") or {},
    )
    merged_audit = validate_merged_pool500_manifest(
        eligible_user_manifest=eligible_user_manifest,
        source_registry=registry,
        per_source_readiness_contracts=per_source_readiness_contracts,
        merged_pool500_manifest=merged_pool500_manifest,
        merged_rows=merged_rows,
        underfilled_threshold=underfilled_threshold,
    )
    leakage_audit = no_holdout_leakage_audit(
        _collect_manifest_inputs(route_input_manifest, source_budget_contract, full_derived_index_manifests),
        LEAKAGE_SENSITIVE_OPERATIONS,
    )
    marker_audit = validate_marker_isolation(
        route_input_manifest,
        per_source_output_manifests,
        merged_pool500_manifest,
    )
    artifact_leakage_audit = validate_artifact_level_leakage(
        artifacts={
            "route_input_manifest": route_input_manifest,
            "source_budget_contract": source_budget_contract,
            "per_source_readiness_contracts": per_source_readiness_contracts,
            "per_source_output_manifests": per_source_output_manifests,
            "full_derived_index_manifests": full_derived_index_manifests,
            "merged_pool500_manifest": merged_pool500_manifest,
        },
        candidate_rows=merged_rows,
        train_item_ids=train_item_ids,
    )

    blockers = [
        *registry_audit["blockers"],
        *readiness_audit["blockers"],
        *route_audit["blockers"],
        *output_audit["blockers"],
        *index_audit["blockers"],
        *two_tower_audit["blockers"],
        *merged_audit["blockers"],
        *leakage_audit["blockers"],
        *marker_audit["blockers"],
        *artifact_leakage_audit["blockers"],
    ]
    diagnostics = [
        *readiness_audit["diagnostics"],
        *budget_audit["diagnostics"],
        *index_audit["diagnostics"],
        *two_tower_audit["diagnostics"],
        *merged_audit["diagnostics"],
        *marker_audit["diagnostics"],
    ]

    if blockers:
        decision = STOP
    elif diagnostics:
        decision = DIAGNOSTIC_ONLY_PARTIAL
    else:
        decision = FULL_POOL500_READY

    return {
        "schema_version": ARTIFACT_GATE_SCHEMA_VERSION,
        "decision": decision,
        "status": "PASS" if decision == FULL_POOL500_READY else decision,
        "candidate_generation_allowed": False,
        "ranking_input_replacement_allowed": False,
        "pool1000_allowed": False,
        "registry_audit": registry_audit,
        "readiness_audit": readiness_audit,
        "route_input_audit": route_audit,
        "source_budget_audit": budget_audit,
        "per_source_output_audit": output_audit,
        "two_tower_full_clean_audit": two_tower_audit,
        "full_derived_index_audit": index_audit,
        "merged_pool500_audit": merged_audit,
        "no_holdout_leakage_audit": leakage_audit,
        "artifact_level_leakage_audit": artifact_leakage_audit,
        "marker_isolation_audit": marker_audit,
        "blockers": blockers,
        "diagnostics": diagnostics,
    }


def build_pool500_shadow_evidence(
    *,
    evidence_id: str,
    artifact_gate_result: dict[str, Any],
    readiness_bundle_result: dict[str, Any] | None = None,
    readiness_bundle_path: str | None = None,
    raw_route_gate_result: dict[str, Any] | None = None,
    artifact_paths: dict[str, Any] | None = None,
    quality_audit: dict[str, Any] | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    readiness_bundle_result = readiness_bundle_result or {}
    raw_route_gate_result = raw_route_gate_result or {}
    return {
        "schema_version": POOL500_SHADOW_EVIDENCE_SCHEMA_VERSION,
        "evidence_id": evidence_id,
        "shadow_mode": POOL500_SHADOW_MODE,
        "full_pool500_ready_semantics": POOL500_FULL_READY_SEMANTICS,
        "decision": artifact_gate_result.get("decision"),
        "status": artifact_gate_result.get("status"),
        "artifact_gate_schema_version": artifact_gate_result.get("schema_version"),
        "artifact_gate_decision": artifact_gate_result.get("decision"),
        "raw_route_gate_schema_version": raw_route_gate_result.get("schema_version"),
        "raw_route_gate_decision": raw_route_gate_result.get("decision"),
        "raw_route_gate_status": raw_route_gate_result.get("status"),
        "readiness_bundle_decision": readiness_bundle_result.get("decision"),
        "readiness_bundle_path": readiness_bundle_path,
        "candidate_generation_allowed": False,
        "ranking_replacement_allowed": False,
        "ranking_input_replacement_allowed": False,
        "promotion_allowed": False,
        "full_pool500_ready_declared": False,
        "final_pool500_ready_claimed": False,
        "pool1000_allowed": False,
        "artifact_paths": dict(artifact_paths or {}),
        "quality_audit": quality_audit or {},
        "blockers": artifact_gate_result.get("blockers", []),
        "diagnostics": artifact_gate_result.get("diagnostics", []),
        "generated_at": generated_at,
    }


def validate_pool500_shadow_evidence(evidence: dict[str, Any]) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    if evidence.get("schema_version") != POOL500_SHADOW_EVIDENCE_SCHEMA_VERSION:
        blockers.append(_blocker("POOL500_SHADOW_EVIDENCE_SCHEMA_VERSION_MISMATCH", {"schema_version": evidence.get("schema_version")}))
    if evidence.get("shadow_mode") != POOL500_SHADOW_MODE:
        blockers.append(_blocker("POOL500_SHADOW_MODE_REQUIRED", {"shadow_mode": evidence.get("shadow_mode")}))
    if evidence.get("full_pool500_ready_semantics") != POOL500_FULL_READY_SEMANTICS:
        blockers.append(_blocker("POOL500_FULL_READY_SEMANTICS_REQUIRED", {"full_pool500_ready_semantics": evidence.get("full_pool500_ready_semantics")}))
    if _truthy(evidence, "candidate_generation_allowed"):
        blockers.append(_blocker("CANDIDATE_GENERATION_NOT_AUTHORIZED_BY_SHADOW_EVIDENCE", {"candidate_generation_allowed": True}))
    if _truthy(evidence, "ranking_replacement_allowed") or _truthy(evidence, "ranking_input_replacement_allowed"):
        blockers.append(_blocker("RANKING_REPLACEMENT_FORBIDDEN_BY_SHADOW_EVIDENCE", _pick(evidence, ["ranking_replacement_allowed", "ranking_input_replacement_allowed"])))
    if _truthy(evidence, "promotion_allowed"):
        blockers.append(_blocker("PROMOTION_FORBIDDEN_BY_SHADOW_EVIDENCE", {"promotion_allowed": True}))
    if _truthy(evidence, "full_pool500_ready_declared"):
        blockers.append(_blocker("FULL_POOL500_READY_DECLARATION_FORBIDDEN_BY_SHADOW_EVIDENCE", {"full_pool500_ready_declared": True}))
    if _truthy(evidence, "final_pool500_ready_claimed"):
        blockers.append(_blocker("FINAL_POOL500_READY_CLAIM_FORBIDDEN_BY_SHADOW_EVIDENCE", {"final_pool500_ready_claimed": True}))
    if "current_ranking_route" in evidence:
        blockers.append(_blocker("CURRENT_RANKING_ROUTE_WRITE_FORBIDDEN", {"current_ranking_route": evidence.get("current_ranking_route")}))
    marker_audit = {"status": "PASS", "blockers": [], "diagnostics": []}
    decision = STOP if blockers else evidence.get("decision", DIAGNOSTIC_ONLY_PARTIAL)
    return {
        "schema_version": POOL500_SHADOW_EVIDENCE_SCHEMA_VERSION,
        "decision": decision,
        "status": "PASS" if not blockers else STOP,
        "candidate_generation_allowed": False,
        "ranking_replacement_allowed": False,
        "ranking_input_replacement_allowed": False,
        "promotion_allowed": False,
        "full_pool500_ready_declared": False,
        "final_pool500_ready_claimed": False,
        "pool1000_allowed": False,
        "marker_isolation_audit": marker_audit,
        "blockers": blockers,
    }


def validate_pool500_itemcf_per_source_metrics(metrics: dict[str, Any]) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    if metrics.get("schema_version") != "pool500_itemcf_per_source_metrics.v1":
        blockers.append(_blocker("PER_SOURCE_METRIC_SCHEMA_VERSION_MISMATCH", {"schema_version": metrics.get("schema_version")}))
    if metrics.get("split") not in {"valid", "test"}:
        blockers.append(_blocker("PER_SOURCE_METRIC_SPLIT_INVALID", {"split": metrics.get("split")}))
    source_metrics = metrics.get("source_metrics") if isinstance(metrics.get("source_metrics"), dict) else {}
    source_roles: dict[str, Any] = {}
    required_by_source = {
        "itemcf_weak": {"source_role", "raw_recall@500", "in_universe_recall@500", "candidate_user_coverage", "unique_candidate_count", "ablation_delta_recall@500"},
        "itemcf_strong": {"source_role", "raw_recall@500", "in_universe_recall@500", "candidate_user_coverage", "strong_hit_rate@500", "ablation_delta_recall@500"},
    }
    for source, required_fields in required_by_source.items():
        source_payload = source_metrics.get(source)
        if not isinstance(source_payload, dict):
            blockers.append(_blocker("PER_SOURCE_METRIC_MISSING", {"source": source}))
            continue
        source_roles[source] = source_payload.get("source_role")
        missing_fields = sorted(field for field in required_fields if field not in source_payload)
        if missing_fields:
            blockers.append(_blocker("PER_SOURCE_METRIC_FIELD_MISSING", {"source": source, "fields": missing_fields}))
    weak_strong_metrics_distinguishable = bool(source_roles.get("itemcf_weak") and source_roles.get("itemcf_strong") and source_roles.get("itemcf_weak") != source_roles.get("itemcf_strong"))
    if not weak_strong_metrics_distinguishable:
        blockers.append(_blocker("WEAK_STRONG_METRICS_NOT_DISTINGUISHABLE", {"source_roles": source_roles}))
    return {"status": "PASS" if not blockers else "BLOCKED", "source_roles": source_roles, "weak_strong_metrics_distinguishable": weak_strong_metrics_distinguishable, "blockers": blockers}


IN_UNIVERSE_EVALUATION_ONLY_BOUNDARY = "只用于评估 denominator 与命中统计，不得作为训练、建边、候选生成或 rerank 输入"


def validate_in_universe_denominator_report(report: dict[str, Any]) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    if report.get("schema_version") != "in_universe_denominator.v1":
        blockers.append(_blocker("IN_UNIVERSE_SCHEMA_VERSION_MISMATCH", {"schema_version": report.get("schema_version")}))
    if report.get("evaluation_only") is not True or report.get("evaluation_only_boundary") != IN_UNIVERSE_EVALUATION_ONLY_BOUNDARY:
        blockers.append(_blocker("IN_UNIVERSE_EVALUATION_ONLY_VIOLATION", _pick(report, ["evaluation_only", "evaluation_only_boundary"])))
    for field in ("used_for_training", "used_for_index_build", "used_for_candidate_generation", "used_for_rerank", "used_for_ranking_input"):
        if bool(report.get(field)):
            blockers.append(_blocker("IN_UNIVERSE_EVALUATION_ONLY_VIOLATION", {field: report.get(field)}))
    if report.get("label_split") not in {"valid", "test"}:
        blockers.append(_blocker("IN_UNIVERSE_LABEL_SPLIT_MUST_BE_EVAL", {"label_split": report.get("label_split")}))
    for field in ("universe_source", "train_item_set_hash", "label_total_count", "label_in_universe_count", "label_out_of_universe_count", "metrics_by_k", "source_breakdown"):
        if field not in report:
            blockers.append(_blocker("IN_UNIVERSE_FIELD_MISSING", {"field": field}))
    total = int(report.get("label_total_count", -1))
    in_universe = int(report.get("label_in_universe_count", -1))
    out_of_universe = int(report.get("label_out_of_universe_count", -1))
    if total < 0 or in_universe < 0 or out_of_universe < 0 or in_universe + out_of_universe != total:
        blockers.append(_blocker("IN_UNIVERSE_LABEL_COUNTS_INVALID", {"total": total, "in_universe": in_universe, "out_of_universe": out_of_universe}))
    metrics_by_k = report.get("metrics_by_k") if isinstance(report.get("metrics_by_k"), dict) else {}
    for k, payload in metrics_by_k.items():
        missing_fields = [field for field in (f"hit_in_universe@{k}", f"recall_in_universe@{k}", f"raw_hit@{k}", f"raw_recall@{k}") if field not in payload]
        if missing_fields:
            blockers.append(_blocker("IN_UNIVERSE_METRICS_BY_K_FIELD_MISSING", {"k": k, "fields": missing_fields}))
    return {"status": "PASS" if not blockers else "BLOCKED", "evaluation_only": report.get("evaluation_only") is True, "label_in_universe_count": report.get("label_in_universe_count"), "blockers": blockers}


def validate_success_criteria_freeze(criteria: dict[str, Any]) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    if criteria.get("schema_version") != "pool500_itemcf_success_criteria.v1":
        blockers.append(_blocker("SUCCESS_CRITERIA_SCHEMA_VERSION_MISMATCH", {"schema_version": criteria.get("schema_version")}))
    if criteria.get("frozen") is not True or criteria.get("frozen_before_test") is not True:
        blockers.append(_blocker("SUCCESS_CRITERIA_NOT_FROZEN", _pick(criteria, ["frozen", "frozen_before_test"])))
    for field in ("config_hash", "success_criteria_hash", "weak_min_in_universe_recall@500", "strong_min_in_universe_recall@500", "combined_min_in_universe_recall@500", "max_underfilled_user_rate", "max_duplicate_user_item_rate", "max_source_budget_violation_rate"):
        if field not in criteria:
            blockers.append(_blocker("SUCCESS_CRITERIA_FIELD_MISSING", {"field": field}))
    return {"status": "PASS" if not blockers else "BLOCKED", "test_final_allowed": not blockers, "blockers": blockers}


def validate_test_attempt_ledger(ledger: list[dict[str, Any]], *, expected_config_hash: str, expected_success_criteria_hash: str) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    if not isinstance(ledger, list) or not ledger:
        blockers.append(_blocker("TEST_ATTEMPT_LEDGER_REQUIRED", {"type": type(ledger).__name__}))
        ledger = []
    seen_attempts: set[str] = set()
    for index, record in enumerate(ledger):
        if record.get("schema_version") != "pool500_itemcf_test_attempt_ledger.v1":
            blockers.append(_blocker("TEST_ATTEMPT_LEDGER_SCHEMA_VERSION_MISMATCH", {"row": index, "schema_version": record.get("schema_version")}))
        for field in ("attempt_id", "split", "config_hash", "success_criteria_hash", "test_final_only", "tuned_after_test", "result_status", "created_at"):
            if field not in record:
                blockers.append(_blocker("TEST_ATTEMPT_LEDGER_FIELD_MISSING", {"row": index, "field": field}))
        attempt_id = str(record.get("attempt_id", ""))
        if attempt_id in seen_attempts:
            blockers.append(_blocker("TEST_ATTEMPT_LEDGER_DUPLICATE_ATTEMPT", {"attempt_id": attempt_id}))
        seen_attempts.add(attempt_id)
        if record.get("split") != "test" or record.get("test_final_only") is not True:
            blockers.append(_blocker("TEST_FINAL_ONLY_REQUIRED", {"row": index, "split": record.get("split"), "test_final_only": record.get("test_final_only")}))
        if record.get("config_hash") != expected_config_hash or record.get("success_criteria_hash") != expected_success_criteria_hash:
            blockers.append(_blocker("TEST_ATTEMPT_LEDGER_HASH_MISMATCH", {"row": index, "config_hash": record.get("config_hash"), "success_criteria_hash": record.get("success_criteria_hash")}))
        if record.get("tuned_after_test") is not False:
            blockers.append(_blocker("TEST_TUNING_AFTER_FINAL_FORBIDDEN", {"row": index, "attempt_id": attempt_id}))
        if record.get("result_status") not in {"PASS", "FAIL"}:
            blockers.append(_blocker("TEST_ATTEMPT_RESULT_STATUS_INVALID", {"row": index, "result_status": record.get("result_status")}))
    return {"status": "PASS" if not blockers else "BLOCKED", "test_attempt_count": len(ledger), "blockers": blockers}


def validate_stage_gate_verifier_checklist(checklist: dict[str, Any], required_stage: str | None = None) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    if checklist.get("schema_version") != "pool500_itemcf_stage_gate_checklist.v1":
        blockers.append(_blocker("STAGE_GATE_SCHEMA_VERSION_MISMATCH", {"schema_version": checklist.get("schema_version")}))
    if required_stage is not None and checklist.get("stage") != required_stage:
        blockers.append(_blocker("STAGE_GATE_STAGE_MISMATCH", {"expected": required_stage, "actual": checklist.get("stage")}))
    if checklist.get("status") != "PASS":
        blockers.append(_blocker("STAGE_GATE_STATUS_NOT_PASS", {"status": checklist.get("status")}))
    checks = checklist.get("checks") if isinstance(checklist.get("checks"), dict) else {}
    required_checks = {"forbidden_input_audit_pass", "per_source_metrics_present", "in_universe_denominator_present", "success_criteria_frozen", "test_attempt_ledger_present", "remote_provenance_present", "pool200_route_authority_unchanged", "ranking_input_contract_unchanged", "underfill_duplicate_source_budget_within_threshold"}
    missing_checks = sorted(required_checks - set(checks))
    if missing_checks:
        blockers.append(_blocker("STAGE_GATE_CHECK_MISSING", {"checks": missing_checks}))
    failed_checks = sorted(check for check, value in checks.items() if value is not True)
    for check in failed_checks:
        blockers.append(_blocker("STAGE_GATE_CHECK_FAILED", {"check": check}))
    hard_failures = checklist.get("hard_failures") if isinstance(checklist.get("hard_failures"), dict) else {}
    if checks.get("underfill_duplicate_source_budget_within_threshold") is False or any(float(value or 0) > 0 for value in hard_failures.values()):
        blockers.append(_blocker("UNDERFILL_DUPLICATE_SOURCE_BUDGET_HARD_FAILURE", hard_failures))
    return {"status": "PASS" if not blockers else "BLOCKED", "decision": STOP if blockers else READY, "blockers": blockers}


def validate_remote_provenance_bundle(provenance: dict[str, Any]) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    if provenance.get("schema_version") != "pool500_itemcf_remote_provenance.v1":
        blockers.append(_blocker("REMOTE_PROVENANCE_SCHEMA_VERSION_MISMATCH", {"schema_version": provenance.get("schema_version")}))
    for field in ("execution_location", "command", "git_commit", "git_dirty", "python_executable", "input_manifest_hashes", "artifact_hashes", "resource_audit", "local_reverification"):
        if field not in provenance:
            blockers.append(_blocker("REMOTE_PROVENANCE_FIELD_MISSING", {"field": field}))
    resource_audit = provenance.get("resource_audit") if isinstance(provenance.get("resource_audit"), dict) else {}
    for field in ("peak_rss_bytes", "disk_bytes_written", "shard_count"):
        if field not in resource_audit:
            blockers.append(_blocker("REMOTE_RESOURCE_AUDIT_FIELD_MISSING", {"field": field}))
    local_reverification = provenance.get("local_reverification") if isinstance(provenance.get("local_reverification"), dict) else {}
    if local_reverification.get("status") != "PASS" or local_reverification.get("hash_match") is not True:
        blockers.append(_blocker("REMOTE_ARTIFACT_LOCAL_REVERIFY_REQUIRED", local_reverification))
    return {"status": "PASS" if not blockers else "BLOCKED", "local_reverification_required": True, "blockers": blockers}


def validate_pool500_ranking_freeze(freeze: dict[str, Any]) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    if freeze.get("schema_version") != "pool500_itemcf_ranking_freeze.v1":
        blockers.append(_blocker("POOL500_RANKING_FREEZE_SCHEMA_VERSION_MISMATCH", {"schema_version": freeze.get("schema_version")}))
    for field in ("candidate_fill_order_unchanged", "pool200_authority_unchanged", "ranking_baseline_unchanged", "ranking_top_k_unchanged", "ranking_route_unchanged"):
        if freeze.get(field) is not True:
            blockers.append(_blocker("POOL200_RANKING_FREEZE_VIOLATION", {"field": field, "value": freeze.get(field)}))
    if freeze.get("ranking_input_replacement_allowed") is not False:
        blockers.append(_blocker("POOL200_RANKING_FREEZE_VIOLATION", {"field": "ranking_input_replacement_allowed", "value": freeze.get("ranking_input_replacement_allowed")}))
    changed_files = [str(path).replace("\\", "/") for path in _as_list(freeze.get("changed_files"))]
    forbidden_changed_files = [path for path in changed_files if not path.startswith("outputs/recall/pool500_itemcf_new_dataset/")]
    if forbidden_changed_files:
        blockers.append(_blocker("POOL200_RANKING_FREEZE_VIOLATION", {"changed_files": forbidden_changed_files}))
    return {"status": "PASS" if not blockers else "BLOCKED", "ranking_input_replacement_allowed": False, "blockers": blockers}


def validate_readiness_bundle(readiness_bundle: dict[str, Any]) -> dict[str, Any]:
    artifact_gate_result = readiness_bundle.get("artifact_gate_result") if isinstance(readiness_bundle.get("artifact_gate_result"), dict) else {}
    audit_fields = {
        "quality_audit": DIAGNOSTIC_ONLY_PARTIAL,
        "source_budget_audit": DIAGNOSTIC_ONLY_PARTIAL,
        "source_output_manifest_audit": DIAGNOSTIC_ONLY_PARTIAL,
        "index_manifest_audit": DIAGNOSTIC_ONLY_PARTIAL,
        "no_holdout_audit": STOP,
        "ranking_registry_check": STOP,
    }
    blockers: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    schema_version = readiness_bundle.get("schema_version")
    if schema_version != READINESS_BUNDLE_SCHEMA_VERSION:
        diagnostics.append(_diagnostic("READINESS_BUNDLE_SCHEMA_VERSION_MISMATCH", {"schema_version": schema_version, "required": READINESS_BUNDLE_SCHEMA_VERSION}))
    artifact_decision = artifact_gate_result.get("decision")
    if artifact_decision == STOP:
        blockers.append(_blocker("ARTIFACT_GATE_STOP", {"decision": artifact_decision}))
    elif artifact_decision != FULL_POOL500_READY:
        diagnostics.append(_diagnostic("ARTIFACT_GATE_NOT_FULL_READY", {"decision": artifact_decision}))
    for field, failure_decision in audit_fields.items():
        audit = readiness_bundle.get(field) if isinstance(readiness_bundle.get(field), dict) else {}
        status = audit.get("status")
        if status != "PASS":
            evidence = {"field": field, "status": status}
            if failure_decision == STOP:
                blockers.append(_blocker("READINESS_AUDIT_NOT_PASS", evidence))
            else:
                diagnostics.append(_diagnostic("READINESS_AUDIT_NOT_PASS", evidence))
    required_fields = {
        "final_merged_candidate_manifest",
        "eligible_user_manifest",
        "canonical_source_registry_sha256",
    }
    missing_fields = sorted(field for field in required_fields if not readiness_bundle.get(field))
    if missing_fields:
        diagnostics.append(_diagnostic("READINESS_BUNDLE_FIELD_MISSING", {"fields": missing_fields}))
    if _truthy(readiness_bundle, "candidate_generation_allowed"):
        blockers.append(_blocker("CANDIDATE_GENERATION_NOT_AUTHORIZED_BY_BUNDLE", {"candidate_generation_allowed": True}))
    if _truthy(readiness_bundle, "ranking_input_replacement_allowed") or _truthy(readiness_bundle, "promote_to_ranking_input"):
        blockers.append(_blocker("RANKING_INPUT_REPLACEMENT_FORBIDDEN", _pick(readiness_bundle, ["ranking_input_replacement_allowed", "promote_to_ranking_input"])))
    if _truthy(readiness_bundle, "pool1000_allowed") or _truthy(readiness_bundle, "pool1000_ready"):
        blockers.append(_blocker("POOL1000_OUTPUT_FORBIDDEN", _pick(readiness_bundle, ["pool1000_allowed", "pool1000_ready"])))
    marker_audit = validate_marker_isolation(readiness_bundle)
    blockers.extend(marker_audit["blockers"])
    diagnostics.extend(marker_audit["diagnostics"])
    if blockers:
        decision = STOP
    elif diagnostics:
        decision = DIAGNOSTIC_ONLY_PARTIAL
    else:
        decision = FULL_POOL500_READY
    return {
        "schema_version": READINESS_BUNDLE_SCHEMA_VERSION,
        "decision": decision,
        "status": "PASS" if decision == FULL_POOL500_READY else decision,
        "candidate_generation_allowed": False,
        "ranking_input_replacement_allowed": False,
        "pool1000_allowed": False,
        "artifact_gate_decision": artifact_decision,
        "marker_isolation_audit": marker_audit,
        "blockers": blockers,
        "diagnostics": diagnostics,
    }


def validate_method_contract(contract: dict[str, Any]) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    raw_sources = _source_labels(contract)
    forbidden_sources = sorted({source for source in raw_sources if source in FORBIDDEN_SOURCE_LABELS})
    canonical_sources = sorted(canonicalize_source_set(raw_sources))
    missing_sources = sorted(CANONICAL_SOURCES - set(canonical_sources))
    unknown_sources = sorted(set(canonical_sources) - CANONICAL_SOURCES)
    candidate_pool_size = contract.get("candidate_pool_size")
    if candidate_pool_size != 500:
        blockers.append(_blocker("INVALID_CANDIDATE_POOL_SIZE", {"candidate_pool_size": candidate_pool_size, "required": 500}))
    if forbidden_sources:
        blockers.append(_blocker("FORBIDDEN_SOURCE_LABEL", {"sources": forbidden_sources}))
    if missing_sources:
        blockers.append(_blocker("MISSING_CANONICAL_SOURCE", {"sources": missing_sources}))
    if unknown_sources:
        blockers.append(_blocker("UNKNOWN_SOURCE_LABEL", {"sources": unknown_sources}))
    if _truthy(contract, "pool1000_artifact") or _truthy(contract, "pool1000_ready") or _truthy(contract, "pool1000_readiness_peer"):
        blockers.append(_blocker("POOL1000_OUTPUT_FORBIDDEN", _pick(contract, ["pool1000_artifact", "pool1000_ready", "pool1000_readiness_peer"])))
    if _truthy(contract, "ranking_input_replacement") or _truthy(contract, "promote_to_ranking_input"):
        blockers.append(_blocker("RANKING_INPUT_REPLACEMENT_FORBIDDEN", _pick(contract, ["ranking_input_replacement", "promote_to_ranking_input"])))
    if contract.get("legacy_reference_signature") and contract.get("legacy_reference_signature_pass_authority"):
        blockers.append(_blocker("LEGACY_REFERENCE_SIGNATURE_NOT_AUTHORITY", {"legacy_reference_signature_pass_authority": True}))
    return {
        "status": "PASS" if not blockers else "BLOCKED",
        "canonical_sources": canonical_sources,
        "required_sources": sorted(CANONICAL_SOURCES),
        "forbidden_source_labels": forbidden_sources,
        "candidate_pool_size": candidate_pool_size,
        "legacy_reference_signature_accepted_as_reference_only": bool(contract.get("legacy_reference_signature")),
        "blockers": blockers,
    }


def validate_index_manifest(index_manifest: dict[str, Any]) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    index_scope = index_manifest.get("index_scope")
    declared_inputs = _as_list(index_manifest.get("inputs") or index_manifest.get("input_paths") or index_manifest.get("source_files"))
    leakage_audit = no_holdout_leakage_audit(declared_inputs, {"index_build"})
    blockers.extend(leakage_audit["blockers"])
    index_scope_diagnostic_only = index_scope != "FULL_DERIVED_INDEX"
    if _truthy(index_manifest, "pool1000_artifact") or _truthy(index_manifest, "pool1000_ready"):
        blockers.append(_blocker("POOL1000_OUTPUT_FORBIDDEN", _pick(index_manifest, ["pool1000_artifact", "pool1000_ready"])))
    if _truthy(index_manifest, "candidate_generation_executed") and not index_manifest.get("candidate_output_manifest"):
        blockers.append(_blocker("PARTIAL_OUTPUT_REJECTED", {"candidate_generation_executed": True, "candidate_output_manifest": None}))
    return {
        "status": "PASS" if not blockers else "BLOCKED",
        "index_scope": index_scope,
        "index_scope_diagnostic_only": index_scope_diagnostic_only,
        "declared_input_count": len(declared_inputs),
        "leakage_audit": leakage_audit,
        "blockers": blockers,
    }


def build_data_foundation_audit(clean_manifest: dict[str, Any], lightweight_views_manifest: dict[str, Any]) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    missing_clean_fields = sorted(field for field in REQUIRED_CLEAN_MANIFEST_FIELDS if field not in clean_manifest)
    split_paths = clean_manifest.get("split_paths") if isinstance(clean_manifest.get("split_paths"), dict) else {}
    train_split = split_paths.get("train")
    valid_split = split_paths.get("valid")
    test_split = split_paths.get("test")
    outputs = lightweight_views_manifest.get("outputs") if isinstance(lightweight_views_manifest.get("outputs"), dict) else {}
    missing_lightweight_outputs = sorted(REQUIRED_LIGHTWEIGHT_OUTPUTS - set(outputs))
    if missing_clean_fields:
        blockers.append(_blocker("MISSING_CLEAN_MANIFEST_FIELD", {"fields": missing_clean_fields}))
    if not train_split:
        blockers.append(_blocker("MISSING_TRAIN_SPLIT", {"split_paths": split_paths}))
    if missing_lightweight_outputs:
        blockers.append(_blocker("MISSING_LIGHTWEIGHT_VIEW_OUTPUT", {"outputs": missing_lightweight_outputs}))
    allowed_inputs = [
        clean_manifest.get("train_user_sequences_path"),
        train_split,
        clean_manifest.get("canonical_items_path"),
        *outputs.values(),
    ]
    evaluation_only_inputs = [valid_split, test_split]
    leakage_audit = no_holdout_leakage_audit(allowed_inputs, GENERATION_OPERATIONS)
    blockers.extend(leakage_audit["blockers"])
    return {
        "status": "PASS" if not blockers else "BLOCKED",
        "clean_manifest_schema_version": clean_manifest.get("schema_version"),
        "lightweight_views_mode": lightweight_views_manifest.get("mode"),
        "allowed_candidate_generation_inputs": [str(item) for item in allowed_inputs if item],
        "evaluation_only_inputs": [str(item) for item in evaluation_only_inputs if item],
        "forbidden_input_filenames": sorted(FORBIDDEN_INPUT_FILENAMES),
        "train_split_path": train_split,
        "canonical_items_path": clean_manifest.get("canonical_items_path"),
        "lightweight_outputs": outputs,
        "skipped_lightweight_outputs": lightweight_views_manifest.get("skipped_outputs", []),
        "leakage_audit": leakage_audit,
        "blockers": blockers,
    }


def no_holdout_leakage_audit(inputs: Any, operations: set[str] | list[str] | tuple[str, ...]) -> dict[str, Any]:
    operation_set = {str(operation) for operation in operations}
    input_paths = [str(item) for item in _as_list(inputs) if item]
    forbidden_matches = [path for path in input_paths if _is_forbidden_input(path)]
    is_generation_operation = bool(operation_set & LEAKAGE_SENSITIVE_OPERATIONS)
    blockers = []
    if forbidden_matches and is_generation_operation:
        blockers.append(_blocker("HOLDOUT_LEAKAGE_FORBIDDEN", {"inputs": sorted(forbidden_matches), "operations": sorted(operation_set)}))
    return {
        "status": "PASS" if not blockers else "BLOCKED",
        "operations": sorted(operation_set),
        "input_count": len(input_paths),
        "forbidden_matches": sorted(forbidden_matches),
        "candidate_generation_uses_holdout": bool(forbidden_matches and is_generation_operation),
        "blockers": blockers,
    }


def representative_probe_boundary(method_contract: dict[str, Any], index_manifest: dict[str, Any]) -> dict[str, Any]:
    payload = {**index_manifest, **method_contract}
    matched_markers = {
        key: payload.get(key)
        for key, expected in REPRESENTATIVE_PROBE_MARKERS.items()
        if payload.get(key) == expected
    }
    index_scope = payload.get("index_scope")
    if index_scope != "FULL_DERIVED_INDEX":
        matched_markers["index_scope"] = index_scope
    diagnostic_only = bool(matched_markers)
    return {
        "status": DIAGNOSTIC_ONLY if diagnostic_only else "PASS",
        "diagnostic_only": diagnostic_only,
        "matched_markers": matched_markers,
        "required_full_index_scope": "FULL_DERIVED_INDEX",
    }


def reject_partial_outputs(observed_outputs: dict[str, Any]) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    generated = bool(observed_outputs.get("candidate_generation_executed"))
    output_paths = _as_list(observed_outputs.get("output_paths") or observed_outputs.get("candidate_outputs"))
    pool1000_outputs = [str(path) for path in output_paths if "pool1000" in str(path).lower()]
    missing_declared_outputs = [str(path) for path in output_paths if path and observed_outputs.get("check_files_exist") and not Path(str(path)).exists()]
    if generated and not output_paths:
        blockers.append(_blocker("PARTIAL_OUTPUT_REJECTED", {"candidate_generation_executed": generated, "output_paths": []}))
    if pool1000_outputs:
        blockers.append(_blocker("POOL1000_OUTPUT_FORBIDDEN", {"output_paths": sorted(pool1000_outputs)}))
    if missing_declared_outputs:
        blockers.append(_blocker("PARTIAL_OUTPUT_REJECTED", {"missing_outputs": sorted(missing_declared_outputs)}))
    return {
        "status": "PASS" if not blockers else "BLOCKED",
        "candidate_generation_executed": generated,
        "output_paths": [str(path) for path in output_paths],
        "blockers": blockers,
    }


def build_canonical_source_registry(sources: Any | None = None, aliases: dict[str, str] | None = None) -> dict[str, Any]:
    required_sources = sorted(canonicalize_source_set(sources or CANONICAL_SOURCES))
    return {
        "schema_version": "canonical_source_registry_v5",
        "required_sources": required_sources,
        "final_source_whitelist": sorted(FINAL_SOURCE_WHITELIST),
        "aliases": dict(sorted((aliases or SOURCE_ALIASES).items())),
        "group_expansions": {key: sorted(value) for key, value in GROUP_SOURCE_EXPANSIONS.items()},
        "forbidden_final_source_labels": sorted(FORBIDDEN_SOURCE_LABELS),
        "readiness_statuses": sorted(READINESS_STATUSES),
    }


def validate_canonical_source_registry(registry: dict[str, Any]) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    required_sources = set(canonicalize_source_set(registry.get("required_sources") or registry.get("sources") or []))
    final_whitelist = set(canonicalize_source_set(registry.get("final_source_whitelist") or registry.get("whitelist") or required_sources))
    aliases = registry.get("aliases") if isinstance(registry.get("aliases"), dict) else {}
    missing_sources = sorted(CANONICAL_SOURCES - required_sources)
    unknown_sources = sorted(required_sources - CANONICAL_SOURCES)
    missing_aliases = sorted(alias for alias in ("youtube_dnn", "two_tower_youtube_dnn", "co_visit") if aliases.get(alias) != SOURCE_ALIASES[alias])
    forbidden_final_labels = sorted(label for label in FORBIDDEN_SOURCE_LABELS if label in final_whitelist)
    if missing_sources:
        blockers.append(_blocker("MISSING_CANONICAL_SOURCE", {"sources": missing_sources}))
    if unknown_sources:
        blockers.append(_blocker("UNKNOWN_SOURCE_LABEL", {"sources": unknown_sources}))
    if missing_aliases:
        blockers.append(_blocker("MISSING_SOURCE_ALIAS", {"aliases": missing_aliases}))
    if forbidden_final_labels:
        blockers.append(_blocker("FORBIDDEN_FINAL_SOURCE_LABEL", {"sources": forbidden_final_labels}))
    return {
        "status": "PASS" if not blockers else "BLOCKED",
        "required_sources": sorted(required_sources),
        "final_source_whitelist": sorted(final_whitelist),
        "missing_aliases": missing_aliases,
        "blockers": blockers,
    }


def validate_per_source_readiness(readiness_contracts: dict[str, Any], registry: dict[str, Any]) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    required_sources = sorted(canonicalize_source_set(registry.get("required_sources") or CANONICAL_SOURCES))
    status_by_source: dict[str, str | None] = {}
    index_status_by_source: dict[str, str | None] = {}
    diagnostic_output_status_by_source: dict[str, str | None] = {}
    full_output_status_by_source: dict[str, str | None] = {}
    unknown_sources: set[str] = set()
    for raw_source, contract in readiness_contracts.items():
        source = canonicalize_source_label(raw_source)
        if source not in CANONICAL_SOURCES:
            unknown_sources.add(source)
            continue
        status = _readiness_status(contract)
        raw_label = str(raw_source).strip().lower().replace("-", "_")
        if source == "two_tower" and raw_label != "two_tower" and status == READY:
            blockers.append(_blocker("TWO_TOWER_CANONICAL_SOURCE_REQUIRED", {"source_name": raw_source, "canonical_source": source}))
        index_status = _source_index_status(contract)
        diagnostic_output_status = _source_diagnostic_output_status(contract)
        full_output_status = _source_full_output_status(contract)
        status_by_source[source] = status
        index_status_by_source[source] = index_status
        diagnostic_output_status_by_source[source] = diagnostic_output_status
        full_output_status_by_source[source] = full_output_status
        if status not in READINESS_STATUSES:
            blockers.append(_blocker("UNKNOWN_READINESS_STATUS", {"source": source, "status": status}))
        if index_status and index_status not in INDEX_STATUSES:
            blockers.append(_blocker("UNKNOWN_INDEX_STATUS", {"source": source, "status": index_status}))
        if diagnostic_output_status and diagnostic_output_status not in OUTPUT_STATUSES:
            blockers.append(_blocker("UNKNOWN_DIAGNOSTIC_OUTPUT_STATUS", {"source": source, "status": diagnostic_output_status}))
        if full_output_status and full_output_status not in OUTPUT_STATUSES:
            blockers.append(_blocker("UNKNOWN_FULL_OUTPUT_STATUS", {"source": source, "status": full_output_status}))
        if status == READY:
            if _manifest_missing(contract) or not contract.get("index_manifest_sha256") or not contract.get("output_manifest_sha256") or not contract.get("manifest_path"):
                blockers.append(_blocker("READY_MANIFEST_MISSING", {"source": source}))
            if index_status != INDEX_READY:
                blockers.append(_blocker("READY_INDEX_NOT_READY", {"source": source, "index_status": index_status}))
            if full_output_status != FULL_OUTPUT_READY:
                code = "DIAGNOSTIC_OUTPUT_NOT_FULL_READY" if diagnostic_output_status == DIAGNOSTIC_OUTPUT_READY else "READY_FULL_OUTPUT_NOT_READY"
                blockers.append(_blocker(code, {"source": source, "diagnostic_output_status": diagnostic_output_status, "full_output_status": full_output_status}))
    for source in required_sources:
        status = status_by_source.get(source)
        if status != READY:
            diagnostics.append(_diagnostic("REQUIRED_SOURCE_NOT_READY", {"source": source, "status": status}))
    if unknown_sources:
        blockers.append(_blocker("UNKNOWN_SOURCE_LABEL", {"sources": sorted(unknown_sources)}))
    return {
        "status": "PASS" if not blockers else "BLOCKED",
        "ready_sources": sorted(source for source, status in status_by_source.items() if status == READY),
        "status_by_source": status_by_source,
        "index_status_by_source": index_status_by_source,
        "diagnostic_output_status_by_source": diagnostic_output_status_by_source,
        "full_output_status_by_source": full_output_status_by_source,
        "blockers": blockers,
        "diagnostics": diagnostics,
    }


def validate_route_input_manifest(route_input_manifest: dict[str, Any]) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    flattened = list(_walk_manifest(route_input_manifest))
    paths = [value for key, value in flattened if _looks_like_path_key(key) or _looks_like_path_value(value)]
    forbidden_inference = [value for _, value in flattened if any(token in str(value).replace("-", "_").lower() for token in ROUTE_INFERENCE_TOKENS)]
    pool1000_values = [
        value
        for key, value in flattened
        if ("pool1000" in key.lower() and bool(value)) or "pool1000" in str(value).lower()
    ]
    ranking_replacements = [key for key, value in flattened if key.lower() in {"ranking_input_replacement", "promote_to_ranking_input", "ranking_replacement", "promotion"} and bool(value)]
    non_whitelist_exclusions = _as_list(route_input_manifest.get("exclusions") or route_input_manifest.get("excluded_sources"))
    forbidden_inputs = [path for path in paths if _is_forbidden_input(str(path))]
    if forbidden_inference:
        blockers.append(_blocker("ROUTE_INPUT_INFERENCE_FORBIDDEN", {"values": sorted(map(str, forbidden_inference))}))
    if pool1000_values:
        blockers.append(_blocker("POOL1000_OUTPUT_FORBIDDEN", {"values": sorted(map(str, pool1000_values))}))
    if ranking_replacements:
        blockers.append(_blocker("RANKING_INPUT_REPLACEMENT_FORBIDDEN", {"fields": sorted(ranking_replacements)}))
    if non_whitelist_exclusions:
        blockers.append(_blocker("NON_WHITELIST_EXCLUSION_FORBIDDEN", {"exclusions": sorted(map(str, non_whitelist_exclusions))}))
    if forbidden_inputs:
        blockers.append(_blocker("HOLDOUT_LEAKAGE_FORBIDDEN", {"inputs": sorted(map(str, forbidden_inputs)), "operations": sorted(LEAKAGE_SENSITIVE_OPERATIONS)}))
    return {
        "status": "PASS" if not blockers else "BLOCKED",
        "declared_path_count": len(paths),
        "blockers": blockers,
    }


def validate_source_budget_contract(source_budget_contract: dict[str, Any]) -> dict[str, Any]:
    diagnostics: list[dict[str, Any]] = []
    budget_frozen = bool(source_budget_contract.get("budget_frozen") or source_budget_contract.get("frozen"))
    train_only = bool(source_budget_contract.get("train_only") or source_budget_contract.get("budget_train_only"))
    if not budget_frozen or not train_only:
        diagnostics.append(_diagnostic("BUDGET_NOT_FROZEN_TRAIN_ONLY", {"budget_frozen": budget_frozen, "train_only": train_only}))
    return {
        "status": "PASS" if not diagnostics else DIAGNOSTIC_ONLY_PARTIAL,
        "budget_frozen": budget_frozen,
        "train_only": train_only,
        "diagnostics": diagnostics,
    }


def validate_per_source_outputs(output_manifests: dict[str, Any], readiness_contracts: dict[str, Any]) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    sha_mismatches: list[dict[str, Any]] = []
    for raw_source, readiness_contract in readiness_contracts.items():
        source = canonicalize_source_label(raw_source)
        if _readiness_status(readiness_contract) != READY:
            continue
        manifest = output_manifests.get(raw_source) or output_manifests.get(source)
        if not isinstance(manifest, dict):
            blockers.append(_blocker("READY_MANIFEST_MISSING", {"source": source}))
            continue
        expected_sha = readiness_contract.get("output_manifest_sha256") or readiness_contract.get("manifest_sha256")
        actual_sha = manifest.get("sha256") or manifest.get("manifest_sha256")
        if expected_sha and actual_sha and str(expected_sha) != str(actual_sha):
            sha_mismatches.append({"source": source, "expected": str(expected_sha), "actual": str(actual_sha)})
        final_sources = canonicalize_source_set(manifest.get("final_sources") or manifest.get("sources") or manifest.get("source"))
        forbidden_sources = sorted(final_sources - FINAL_SOURCE_WHITELIST)
        if forbidden_sources:
            blockers.append(_blocker("FINAL_SOURCE_NOT_WHITELISTED", {"source": source, "final_sources": forbidden_sources}))
    if sha_mismatches:
        blockers.append(_blocker("SOURCE_OUTPUT_SHA_MISMATCH", {"mismatches": sha_mismatches}))
    return {
        "status": "PASS" if not blockers else "BLOCKED",
        "blockers": blockers,
    }


def validate_full_derived_index_manifests(index_manifests: dict[str, Any], readiness_contracts: dict[str, Any]) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    index_status_by_source: dict[str, str | None] = {}
    unknown_sources: set[str] = set()
    readiness_by_source = {canonicalize_source_label(source): contract for source, contract in readiness_contracts.items()}
    for raw_source, manifest in index_manifests.items():
        source = canonicalize_source_label(raw_source)
        if source not in CANONICAL_SOURCES:
            unknown_sources.add(source)
            continue
        if not isinstance(manifest, dict):
            blockers.append(_blocker("FULL_INDEX_MANIFEST_MISSING", {"source": source}))
            continue
        status = _source_index_status(manifest)
        index_status_by_source[source] = status
        manifest_source = canonicalize_source_label(manifest.get("source") or manifest.get("canonical_source") or source)
        readiness_contract = readiness_by_source.get(source, {})
        readiness_status = _readiness_status(readiness_contract)
        expected_sha = readiness_contract.get("index_manifest_sha256") if isinstance(readiness_contract, dict) else None
        actual_sha = manifest.get("sha256") or manifest.get("manifest_sha256") or manifest.get("index_manifest_sha256")
        if status == INDEX_READY and readiness_status != READY:
            diagnostics.append(_diagnostic("INDEX_READY_SOURCE_NOT_READY", {"source": source, "source_status": readiness_status}))
            if source == "two_tower":
                diagnostics.append(_diagnostic("TWO_TOWER_INDEX_READY_SOURCE_NOT_READY", {"source_status": readiness_status}))
        if status == INDEX_READY and manifest_source != source:
            blockers.append(_blocker("FULL_INDEX_SOURCE_MISMATCH", {"source": source, "manifest_source": manifest_source}))
        if status == INDEX_READY and manifest.get("index_scope") not in (None, "FULL_DERIVED_INDEX"):
            blockers.append(_blocker("FULL_INDEX_SCOPE_MISMATCH", {"source": source, "index_scope": manifest.get("index_scope")}))
        if status == INDEX_READY and source == "swing_recall" and _is_swing_source_index_manifest(manifest):
            blockers.extend(_validate_swing_full_derived_index_manifest(manifest))
        if expected_sha and actual_sha and str(expected_sha) != str(actual_sha):
            blockers.append(_blocker("SOURCE_INDEX_SHA_MISMATCH", {"source": source, "expected": str(expected_sha), "actual": str(actual_sha)}))
    for source, readiness_contract in readiness_by_source.items():
        if _readiness_status(readiness_contract) == READY and _source_index_status(readiness_contract) == INDEX_READY and source not in index_status_by_source:
            blockers.append(_blocker("FULL_INDEX_MANIFEST_MISSING", {"source": source}))
    if unknown_sources:
        blockers.append(_blocker("UNKNOWN_SOURCE_LABEL", {"sources": sorted(unknown_sources)}))
    return {
        "status": "PASS" if not blockers and not diagnostics else ("BLOCKED" if blockers else DIAGNOSTIC_ONLY_PARTIAL),
        "index_status_by_source": index_status_by_source,
        "blockers": blockers,
        "diagnostics": diagnostics,
    }


def _is_swing_source_index_manifest(manifest: dict[str, Any]) -> bool:
    return bool(
        manifest.get("schema_version") == "full_train_swing_sidecar_v1"
        or manifest.get("input_contract")
        or manifest.get("lifecycle_stage")
        or manifest.get("provenance")
        or manifest.get("partial_invalidation_keys")
    )



def _validate_swing_full_derived_index_manifest(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    if manifest.get("schema_version") != "full_train_swing_sidecar_v1":
        blockers.append(_blocker("SWING_SOURCE_INDEX_SCHEMA_VERSION_MISMATCH", {"schema_version": manifest.get("schema_version")}))
    if manifest.get("status") != "PASS":
        blockers.append(_blocker("SWING_SOURCE_INDEX_STATUS_NOT_PASS", {"status": manifest.get("status")}))
    if manifest.get("source_status") == "TARGET_SLICE_DIAGNOSTIC":
        blockers.append(_blocker("SWING_TARGET_SLICE_DIAGNOSTIC_FORBIDDEN_AS_FULL_INDEX", {"source_status": manifest.get("source_status")}))
    if manifest.get("train_only") is not True:
        blockers.append(_blocker("SWING_SOURCE_INDEX_TRAIN_ONLY_REQUIRED", {"train_only": manifest.get("train_only")}))
    if manifest.get("lifecycle_stage") != "builder_complete":
        blockers.append(_blocker("SWING_SOURCE_INDEX_LIFECYCLE_STAGE_INVALID", {"lifecycle_stage": manifest.get("lifecycle_stage")}))
    for field in ("candidate_generation_allowed", "ranking_input_replacement_allowed", "ranking_replacement_allowed", "promotion_allowed", "pool1000_allowed", "agent_allowed", "serving_allowed"):
        if manifest.get(field) is True:
            blockers.append(_blocker("SWING_SOURCE_INDEX_PERMISSION_FORBIDDEN", {"field": field, "value": manifest.get(field)}))
    input_contract = manifest.get("input_contract")
    if not isinstance(input_contract, dict):
        blockers.append(_blocker("SWING_SOURCE_INDEX_INPUT_CONTRACT_MISSING", {"input_contract_type": type(input_contract).__name__}))
        input_contract = {}
    train_path = str(input_contract.get("train_user_sequences_path") or manifest.get("train_user_sequences_path") or "")
    declared_inputs = [str(item) for item in _as_list(input_contract.get("declared_inputs")) if item]
    if input_contract.get("allowed_inputs") != ["clean_manifest.train_user_sequences_path"]:
        blockers.append(_blocker("SWING_SOURCE_INDEX_TRAIN_PROVENANCE_REQUIRED", {"allowed_inputs": input_contract.get("allowed_inputs")}))
    if not train_path or train_path.replace("\\", "/").rsplit("/", 1)[-1] != "user_sequences.train.jsonl" or declared_inputs != [train_path]:
        blockers.append(_blocker("SWING_SOURCE_INDEX_TRAIN_PROVENANCE_REQUIRED", {"train_user_sequences_path": train_path, "declared_inputs": declared_inputs}))
    for value in [manifest.get("clean_manifest_path"), manifest.get("train_user_sequences_path"), input_contract.get("clean_manifest_path"), input_contract.get("train_user_sequences_path"), *declared_inputs]:
        if _is_forbidden_swing_artifact_value(value):
            blockers.append(_blocker("SWING_SOURCE_INDEX_FORBIDDEN_PROVENANCE", {"value": str(value)}))
    provenance = manifest.get("provenance") if isinstance(manifest.get("provenance"), dict) else {}
    train_signature = provenance.get("train_user_sequences_signature") if isinstance(provenance.get("train_user_sequences_signature"), dict) else {}
    clean_signature = provenance.get("clean_manifest_signature") if isinstance(provenance.get("clean_manifest_signature"), dict) else {}
    if not train_signature.get("sha256") or not clean_signature.get("sha256"):
        blockers.append(_blocker("SWING_SOURCE_INDEX_PROVENANCE_SIGNATURE_MISSING", {"provenance_keys": sorted(provenance)}))
    if manifest.get("partial_invalidation_keys") != ["provenance.clean_manifest_signature.sha256", "provenance.train_user_sequences_signature.sha256", "parameters"]:
        blockers.append(_blocker("SWING_SOURCE_INDEX_PARTIAL_INVALIDATION_CONTRACT_MISSING", {"partial_invalidation_keys": manifest.get("partial_invalidation_keys")}))
    artifacts = manifest.get("required_artifacts") if isinstance(manifest.get("required_artifacts"), dict) else {}
    edges_path = artifacts.get("swing_recall_edges")
    if edges_path and _is_forbidden_swing_edges_artifact_path(edges_path):
        blockers.append(_blocker("SWING_SOURCE_INDEX_EDGES_ARTIFACT_FORBIDDEN", {"swing_recall_edges": str(edges_path)}))
    return blockers


def _is_forbidden_swing_artifact_value(value: Any) -> bool:
    normalized = str(value).replace("\\", "/").lower()
    forbidden_tokens = (
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
    )
    return any(token in normalized for token in forbidden_tokens)


def _is_forbidden_swing_edges_artifact_path(value: Any) -> bool:
    normalized = str(value).replace("\\", "/").lower()
    parts = [part for part in normalized.split("/") if part]
    forbidden_parts = {"all_window", "holdout", "label", "labels", "test", "valid"}
    return normalized.startswith("/") or ":" in normalized or ".." in parts or bool(set(parts) & forbidden_parts) or normalized.rsplit("/", 1)[-1] != "swing_recall_edges.jsonl" or _is_forbidden_swing_artifact_value(value)



def validate_two_tower_full_clean_artifact(
    *,
    source_manifest: dict[str, Any],
    index_manifest: dict[str, Any],
    output_manifest: dict[str, Any],
) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    payloads = [source_manifest, index_manifest, output_manifest]
    ready = any(_readiness_status(payload) == READY for payload in payloads)
    combined = _merge_manifest_payloads(index_manifest, output_manifest, source_manifest)
    if not ready:
        return {
            "status": DIAGNOSTIC_ONLY_PARTIAL,
            "ready": False,
            "blockers": [],
            "diagnostics": [_diagnostic("TWO_TOWER_FULL_CLEAN_ARTIFACT_DEFERRED", {})],
        }

    missing_fields = sorted(field for field in REQUIRED_TWO_TOWER_FULL_CLEAN_FIELDS if not combined.get(field))
    if missing_fields:
        blockers.append(_blocker("TWO_TOWER_FULL_CLEAN_FIELD_MISSING", {"fields": missing_fields}))
    if str(combined.get("source_name") or "") not in {"two_tower", "two_tower_youtube_dnn"} or combined.get("canonical_source") != "two_tower":
        blockers.append(_blocker("TWO_TOWER_CANONICAL_SOURCE_REQUIRED", {"source_name": combined.get("source_name"), "canonical_source": combined.get("canonical_source")}))
    if combined.get("index_scope") != "FULL_DERIVED_INDEX":
        blockers.append(_blocker("TWO_TOWER_FULL_INDEX_SCOPE_REQUIRED", {"index_scope": combined.get("index_scope")}))
    for field in ("item_embedding_row_count", "recall_index_row_count"):
        if not _positive_int(combined.get(field)):
            blockers.append(_blocker("TWO_TOWER_ROW_COUNT_REQUIRED", {"field": field, "value": combined.get(field)}))
    if "user_embedding_row_count" in combined and combined.get("user_embedding_row_count") is not None and not _positive_int(combined.get("user_embedding_row_count")):
        blockers.append(_blocker("TWO_TOWER_ROW_COUNT_REQUIRED", {"field": "user_embedding_row_count", "value": combined.get("user_embedding_row_count")}))
    if not combined.get("user_embedding_row_count") and not combined.get("user_embedding_row_count_note"):
        diagnostics.append(_diagnostic("TWO_TOWER_USER_EMBEDDING_ROW_COUNT_UNSPECIFIED", {}))
    forbidden_values = [
        value
        for payload in payloads
        for key, value in _walk_manifest(payload)
        if _is_forbidden_two_tower_artifact_value(value) and not _is_allowed_two_tower_artifact_label(key, value)
    ]
    if forbidden_values:
        blockers.append(_blocker("TWO_TOWER_FORBIDDEN_ARTIFACT_SCOPE", {"values": sorted(map(str, forbidden_values))}))
    leakage_audit = no_holdout_leakage_audit(_collect_manifest_inputs(combined), LEAKAGE_SENSITIVE_OPERATIONS)
    blockers.extend(leakage_audit["blockers"])
    return {
        "status": "PASS" if not blockers and not diagnostics else ("BLOCKED" if blockers else DIAGNOSTIC_ONLY_PARTIAL),
        "ready": True,
        "canonical_source": combined.get("canonical_source"),
        "source_name": combined.get("source_name"),
        "index_scope": combined.get("index_scope"),
        "leakage_audit": leakage_audit,
        "blockers": blockers,
        "diagnostics": diagnostics,
    }



def validate_merged_pool500_manifest(
    *,
    eligible_user_manifest: dict[str, Any],
    source_registry: dict[str, Any],
    per_source_readiness_contracts: dict[str, Any],
    merged_pool500_manifest: dict[str, Any],
    merged_rows: list[dict[str, Any]],
    underfilled_threshold: int,
) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    ready_sources = {
        canonicalize_source_label(source)
        for source, contract in per_source_readiness_contracts.items()
        if _readiness_status(contract) == READY
    }
    required_sources = set(canonicalize_source_set(source_registry.get("required_sources") or CANONICAL_SOURCES))
    eligible_hash = _extract_user_hash(eligible_user_manifest)
    merged_hash = _extract_user_hash(merged_pool500_manifest)
    if eligible_hash and merged_hash and eligible_hash != merged_hash:
        blockers.append(_blocker("USER_HASH_MISMATCH", {"eligible_user_hash": eligible_hash, "merged_user_hash": merged_hash}))
    if not _lineage_complete(merged_pool500_manifest):
        diagnostics.append(_diagnostic("LINEAGE_INCOMPLETE", {"lineage": merged_pool500_manifest.get("lineage")}))
    underfilled_count = int(merged_pool500_manifest.get("underfilled_user_count") or 0)
    if underfilled_count > underfilled_threshold:
        diagnostics.append(_diagnostic("UNDERFILLED_THRESHOLD_EXCEEDED", {"underfilled_user_count": underfilled_count, "threshold": underfilled_threshold}))
    row_audit = validate_merged_rows_schema(merged_rows, ready_sources)
    blockers.extend(row_audit["blockers"])
    if not required_sources <= ready_sources:
        diagnostics.append(_diagnostic("REQUIRED_READY_SET_INCOMPLETE", {"missing_ready_sources": sorted(required_sources - ready_sources)}))
    return {
        "status": "PASS" if not blockers and not diagnostics else ("BLOCKED" if blockers else DIAGNOSTIC_ONLY_PARTIAL),
        "underfilled_user_count": underfilled_count,
        "row_audit": row_audit,
        "blockers": blockers,
        "diagnostics": diagnostics,
    }


def validate_merged_rows_schema(merged_rows: list[dict[str, Any]], ready_sources: set[str]) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    seen_user_items: set[tuple[str, str]] = set()
    per_user_counts: dict[str, int] = {}
    for index, row in enumerate(merged_rows):
        missing_fields = sorted(REQUIRED_JSONL_ROW_FIELDS - set(row))
        if missing_fields:
            blockers.append(_blocker("JSONL_SCHEMA_CORRUPT", {"row_index": index, "missing_fields": missing_fields}))
            continue
        user_id = str(row.get("user_id"))
        item_id = str(row.get("item_id"))
        source = canonicalize_source_label(row.get("source"))
        key = (user_id, item_id)
        if key in seen_user_items:
            blockers.append(_blocker("MERGED_POOL500_DEDUPE_VIOLATION", {"row_index": index, "user_id": user_id, "item_id": item_id}))
        seen_user_items.add(key)
        per_user_counts[user_id] = per_user_counts.get(user_id, 0) + 1
        if per_user_counts[user_id] > 500:
            blockers.append(_blocker("MERGED_POOL500_USER_LIMIT_EXCEEDED", {"user_id": user_id, "count": per_user_counts[user_id]}))
        if source not in ready_sources:
            blockers.append(_blocker("MERGED_ROW_SOURCE_NOT_READY", {"row_index": index, "source": source}))
        if not _finite_number(row.get("score")) or not isinstance(row.get("rank"), int) or row.get("rank") < 1 or not isinstance(row.get("metadata"), dict):
            blockers.append(_blocker("JSONL_SCHEMA_CORRUPT", {"row_index": index, "score": row.get("score"), "rank": row.get("rank"), "metadata_type": type(row.get("metadata")).__name__}))
    return {
        "status": "PASS" if not blockers else "BLOCKED",
        "row_count": len(merged_rows),
        "user_count": len(per_user_counts),
        "blockers": blockers,
    }


def validate_artifact_level_leakage(
    *,
    artifacts: dict[str, Any] | list[Any] | tuple[Any, ...],
    candidate_rows: list[dict[str, Any]] | None = None,
    train_item_ids: set[str] | list[str] | tuple[str, ...] | None = None,
) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    flattened = list(_walk_manifest(artifacts))
    candidate_artifacts = _candidate_artifact_payloads(artifacts)
    for label, payload in candidate_artifacts:
        missing_fields = sorted(field for field in REQUIRED_CANDIDATE_ARTIFACT_FIELDS if field not in payload)
        if missing_fields:
            blockers.append(_blocker("CANDIDATE_ARTIFACT_FIELD_MISSING", {"artifact": label, "fields": missing_fields}))
        blockers.extend(_artifact_role_permission_blockers(label, payload))
        read_files = _as_list(payload.get("read_files"))
        forbidden_read_files = [str(path) for path in read_files if _is_forbidden_candidate_read_file(str(path))]
        if forbidden_read_files:
            blockers.append(_blocker("CANDIDATE_READ_FILES_FORBIDDEN", {"artifact": label, "read_files": sorted(forbidden_read_files)}))

    serving_allowed_false = [
        key
        for key, value in flattened
        if key.lower().endswith("serving_allowed")
        and value is not True
        and "swing_recall" not in key.lower()
    ]
    if serving_allowed_false:
        blockers.append(_blocker("SERVING_ALLOWED_REQUIRED", {"fields": sorted(serving_allowed_false)}))
    forbidden_modes = [
        {"field": key, "value": str(value)}
        for key, value in flattened
        if _is_forbidden_serving_candidate_source(key, value)
    ]
    if forbidden_modes:
        blockers.append(_blocker("SERVING_CANDIDATE_SOURCE_FORBIDDEN", {"matches": forbidden_modes}))

    train_items = {str(item) for item in _as_list(train_item_ids) if str(item)} if train_item_ids is not None else None
    if train_items is not None:
        candidate_items = {str(row.get("item_id") or row.get("parent_asin")) for row in candidate_rows or [] if row.get("item_id") or row.get("parent_asin")}
        unknown_items = sorted(candidate_items - train_items)
        if unknown_items:
            blockers.append(_blocker("CANDIDATE_ITEM_OUTSIDE_TRAIN_SET", {"item_ids": unknown_items[:20], "count": len(unknown_items)}))
    return {
        "status": "PASS" if not blockers else "BLOCKED",
        "candidate_artifact_count": len(candidate_artifacts),
        "train_item_set_checked": train_items is not None,
        "blockers": blockers,
    }


def validate_marker_isolation(*payloads: dict[str, Any]) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    for payload in payloads:
        for key, value in _walk_manifest(payload):
            normalized_value = str(value).lower()
            if any(token in normalized_value for token in FORBIDDEN_FINAL_ARTIFACT_TOKENS):
                blockers.append(_blocker("FINAL_ARTIFACT_MARKER_FORBIDDEN", {"field": key, "value": str(value)}))
            if key.lower() in {"diagnostic_marker", "marker", "marker_scope"} and value:
                diagnostics.append(_diagnostic("MARKER_ISOLATION_REQUIRED", {"field": key, "value": str(value)}))
    return {
        "status": "PASS" if not blockers and not diagnostics else ("BLOCKED" if blockers else DIAGNOSTIC_ONLY_PARTIAL),
        "blockers": blockers,
        "diagnostics": diagnostics,
    }


def canonical_manifest_sha256(payload: Any) -> str:
    canonical_payload = _canonicalize_manifest_payload(payload)
    encoded = json.dumps(canonical_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def canonical_user_set_hash(user_ids: Any) -> str:
    users = sorted({str(user_id) for user_id in _as_list(user_ids) if str(user_id)})
    payload = "\n".join(users)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def load_json_manifest(path: str | Path) -> dict[str, Any]:
    return read_json(path)


def _collect_declared_inputs(method_contract: dict[str, Any], index_manifest: dict[str, Any]) -> list[str]:
    inputs: list[str] = []
    for payload in (method_contract, index_manifest):
        for key in ("inputs", "input_paths", "source_files", "train_inputs", "index_inputs", "model_inputs"):
            inputs.extend(str(item) for item in _as_list(payload.get(key)) if item)
    return inputs


def _is_negative_audit_input_evidence(key: str, value: Any) -> bool:
    normalized_key = key.lower()
    normalized_value = str(value).replace("\\", "/")
    return (
        ".forbidden_files_not_read" in f".{normalized_key}"
        or ".forbidden_manifest_inputs" in f".{normalized_key}"
        or normalized_value == "no_holdout_audit.json"
    )


def _collect_manifest_inputs(*payloads: dict[str, Any]) -> list[str]:
    inputs: list[str] = []
    for payload in payloads:
        for key, value in _walk_manifest(payload):
            if _is_negative_audit_input_evidence(key, value):
                continue
            if _looks_like_path_key(key) or _looks_like_path_value(value):
                inputs.append(str(value))
    return inputs


def _source_labels(contract: dict[str, Any]) -> list[str]:
    for key in ("sources", "enabled_sources", "source_set", "canonical_sources"):
        value = contract.get(key)
        values = list(value) if isinstance(value, dict) else _as_list(value)
        if values:
            return [str(item).strip().lower().replace("-", "_") for item in values if str(item).strip()]
    return []


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, dict):
        return list(value.values())
    if isinstance(value, (list, tuple, set)):
        return list(value)
    return [value]


def _merge_manifest_payloads(*payloads: dict[str, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for payload in payloads:
        if isinstance(payload, dict):
            merged.update(payload)
    return merged


def _positive_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _is_forbidden_two_tower_artifact_value(value: Any) -> bool:
    normalized = str(value).replace("\\", "/").lower()
    return any(token in normalized for token in FORBIDDEN_TWO_TOWER_ARTIFACT_TOKENS)


def _is_allowed_two_tower_artifact_label(key: str, value: Any) -> bool:
    if not isinstance(value, str) or _looks_like_path_value(value):
        return False
    leaf_key = key.rsplit(".", 1)[-1].lower()
    normalized = value.strip().lower().replace("-", "_")
    return leaf_key in {"source_name", "variant", "model_type"} and normalized in {
        "two_tower_youtube_dnn",
        "youtube_dnn",
        "youtube_dnn_two_tower_v1",
    }



def _is_forbidden_input(path: str) -> bool:
    normalized = path.replace("\\", "/").lower()
    filename = normalized.rsplit("/", 1)[-1]
    return filename in FORBIDDEN_INPUT_FILENAMES or any(token in normalized for token in FORBIDDEN_INPUT_TOKENS)


def _candidate_artifact_payloads(value: Any, prefix: str = "") -> list[tuple[str, dict[str, Any]]]:
    payloads: list[tuple[str, dict[str, Any]]] = []
    if isinstance(value, dict):
        if _is_candidate_artifact(value, prefix):
            payloads.append((prefix or "artifact", value))
        for key, item in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            payloads.extend(_candidate_artifact_payloads(item, path))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            payloads.extend(_candidate_artifact_payloads(item, f"{prefix}[{index}]"))
    return payloads


def _is_candidate_artifact(payload: dict[str, Any], prefix: str = "") -> bool:
    if "artifact_role" not in payload and _is_full_derived_source_index_manifest(payload):
        return bool(
            payload.get("candidate_generation_allowed") is True
            or payload.get("candidate_source") is True
            or prefix.rsplit(".", 1)[-1] == "candidate_source"
        )
    return bool(
        "artifact_role" in payload
        or "read_files" in payload
        or payload.get("candidate_generation_allowed") is True
        or payload.get("layer") == "method_dataset"
        or payload.get("candidate_source") is True
        or prefix.rsplit(".", 1)[-1] == "candidate_source"
    )


def _is_full_derived_source_index_manifest(payload: dict[str, Any]) -> bool:
    source = canonicalize_source_label(payload.get("source") or payload.get("canonical_source") or "")
    return bool(
        source in CANONICAL_SOURCES
        and payload.get("index_scope") == "FULL_DERIVED_INDEX"
        and (payload.get("index_status") in INDEX_STATUSES or payload.get("schema_version") == "full_train_swing_sidecar_v1")
    )


def _artifact_role_permission_blockers(label: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    role = payload.get("artifact_role") or payload.get("knowledge_base_role")
    if role not in ALLOWED_ARTIFACT_ROLES:
        blockers.append(_blocker("ARTIFACT_ROLE_NOT_AUTHORIZED", {"artifact": label, "artifact_role": role}))
        return blockers

    candidate_generation_allowed = payload.get("candidate_generation_allowed") is True
    ranking_replacement_allowed = payload.get("ranking_input_replacement_allowed") is True or payload.get("ranking_replacement_allowed") is True
    promotion_allowed = payload.get("promotion_allowed") is True

    if role in {"rag_evidence", "diagnostic_only"}:
        if payload.get("candidate_scoped") is not True:
            blockers.append(_blocker("ARTIFACT_ROLE_PERMISSION_FORBIDDEN", {"artifact": label, "artifact_role": role, "field": "candidate_scoped", "value": payload.get("candidate_scoped")}))
        for field in ("candidate_generation_allowed", "ranking_input_replacement_allowed", "ranking_replacement_allowed", "promotion_allowed"):
            if payload.get(field) is True:
                blockers.append(_blocker("ARTIFACT_ROLE_PERMISSION_FORBIDDEN", {"artifact": label, "artifact_role": role, "field": field, "value": payload.get(field)}))
    elif role == "recall_candidate_source":
        if not candidate_generation_allowed:
            blockers.append(_blocker("RECALL_CANDIDATE_SOURCE_REQUIRES_EXPLICIT_GENERATION", {"artifact": label, "candidate_generation_allowed": payload.get("candidate_generation_allowed")}))
        if ranking_replacement_allowed or promotion_allowed:
            for field in ("ranking_input_replacement_allowed", "ranking_replacement_allowed", "promotion_allowed"):
                if payload.get(field) is True:
                    blockers.append(_blocker("ARTIFACT_ROLE_PERMISSION_FORBIDDEN", {"artifact": label, "artifact_role": role, "field": field, "value": payload.get(field)}))
    return blockers


def _is_forbidden_candidate_read_file(path: str) -> bool:
    normalized = "/" + path.replace("\\", "/").lower()
    filename = normalized.rsplit("/", 1)[-1]
    return filename in FORBIDDEN_INPUT_FILENAMES or any(token in normalized for token in FORBIDDEN_CANDIDATE_READ_TOKENS)


def _is_forbidden_serving_candidate_source(key: str, value: Any) -> bool:
    leaf_key = key.rsplit(".", 1)[-1].lower()
    normalized_value = str(value).strip().lower().replace("-", "_")
    if leaf_key in {"candidate_source_role", "source_role", "data_role"} and normalized_value in {"evaluation_only", "valid_test", "display_only"}:
        return True
    if leaf_key in {"item_universe", "item_universe_scope", "candidate_item_universe"}:
        return normalized_value in FORBIDDEN_SERVING_ITEM_UNIVERSE_TOKENS
    return normalized_value in {"evaluation_only", "valid_test"} and "candidate" in key.lower()


def _truthy(payload: dict[str, Any], key: str) -> bool:
    return bool(payload.get(key))


def _pick(payload: dict[str, Any], keys: list[str]) -> dict[str, Any]:
    return {key: payload.get(key) for key in keys if key in payload}


def _read_optional_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        return read_json(path)
    except Exception:
        return {}


def _blocker(code: str, evidence: dict[str, Any]) -> dict[str, Any]:
    return {"code": code, "severity": "blocker", "evidence": evidence}


def _diagnostic(code: str, evidence: dict[str, Any]) -> dict[str, Any]:
    return {"code": code, "severity": "diagnostic", "evidence": evidence}


def _readiness_status(contract: Any) -> str | None:
    if isinstance(contract, str):
        return contract
    if not isinstance(contract, dict):
        return None
    status = contract.get("readiness") or contract.get("status") or contract.get("decision")
    return str(status) if status is not None else None


def _manifest_missing(contract: Any) -> bool:
    if not isinstance(contract, dict):
        return True
    if contract.get("manifest_missing") or contract.get("missing_manifest"):
        return True
    return not any(contract.get(key) for key in ("manifest", "manifest_path", "output_manifest", "output_manifest_path", "manifest_sha256", "output_manifest_sha256"))


def _source_index_status(contract: Any) -> str | None:
    if not isinstance(contract, dict):
        return None
    status = contract.get("index_status") or contract.get("index_readiness")
    if status is not None:
        return str(status)
    if _readiness_status(contract) == READY and not ("full_output_status" in contract or "diagnostic_output_status" in contract):
        return INDEX_READY
    return None


def _source_diagnostic_output_status(contract: Any) -> str | None:
    if not isinstance(contract, dict):
        return None
    status = contract.get("diagnostic_output_status") or contract.get("diagnostic_status")
    return str(status) if status is not None else None


def _source_full_output_status(contract: Any) -> str | None:
    if not isinstance(contract, dict):
        return None
    status = contract.get("full_output_status") or contract.get("output_status")
    if status is not None:
        return str(status)
    if _readiness_status(contract) == READY and not ("index_status" in contract or "diagnostic_output_status" in contract):
        return FULL_OUTPUT_READY
    return None


def _extract_user_hash(manifest: dict[str, Any]) -> str | None:
    for key in ("eligible_user_hash", "user_hash", "canonical_user_set_hash", "eligible_user_set_hash"):
        if manifest.get(key):
            return str(manifest[key])
    users = manifest.get("eligible_user_ids") or manifest.get("user_ids")
    if users:
        return canonical_user_set_hash(users)
    return None


def _lineage_complete(manifest: dict[str, Any]) -> bool:
    lineage = manifest.get("lineage")
    if isinstance(lineage, dict):
        return bool(lineage.get("source_manifests") or lineage.get("parents"))
    return bool(lineage)


def _finite_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def _walk_manifest(payload: Any, prefix: str = "") -> list[tuple[str, Any]]:
    items: list[tuple[str, Any]] = []
    if isinstance(payload, dict):
        for key, value in payload.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            items.extend(_walk_manifest(value, path))
    elif isinstance(payload, list):
        for index, value in enumerate(payload):
            items.extend(_walk_manifest(value, f"{prefix}[{index}]"))
    else:
        items.append((prefix, payload))
    return items


def _looks_like_path_key(key: str) -> bool:
    normalized = key.lower()
    return normalized.endswith("path") or normalized.endswith("paths") or normalized.endswith("file") or normalized.endswith("files") or "input" in normalized


def _looks_like_path_value(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    normalized = value.replace("\\", "/")
    return "/" in normalized or normalized.endswith((".json", ".jsonl", ".parquet", ".pkl", ".npy", ".npz"))


def _canonicalize_manifest_payload(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _canonicalize_manifest_payload(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_canonicalize_manifest_payload(item) for item in value]
    if isinstance(value, tuple):
        return [_canonicalize_manifest_payload(item) for item in value]
    if isinstance(value, set):
        return sorted(_canonicalize_manifest_payload(item) for item in value)
    if isinstance(value, Path):
        return str(value).replace("\\", "/")
    if isinstance(value, str):
        return value.replace("\\", "/")
    return value
