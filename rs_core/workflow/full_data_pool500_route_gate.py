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
READINESS_STATUSES = {READY, BLOCKED, FAILED, DEFERRED, DIAGNOSTIC_ONLY_STATUS, BATCH_SCOPED_DIAGNOSTIC}
INDEX_STATUSES = {INDEX_READY, INDEX_MISSING, BLOCKED, FAILED, DEFERRED, DIAGNOSTIC_ONLY_STATUS}
OUTPUT_STATUSES = {FULL_OUTPUT_READY, DIAGNOSTIC_OUTPUT_READY, OUTPUT_MISSING, BLOCKED, FAILED, DEFERRED, DIAGNOSTIC_ONLY_STATUS}
NON_READY_STATUSES = {BLOCKED, FAILED, DEFERRED, DIAGNOSTIC_ONLY_STATUS, BATCH_SCOPED_DIAGNOSTIC}

FORBIDDEN_FINAL_ARTIFACT_TOKENS = {"legacy", "probe", "custom", "contract"}
FORBIDDEN_INPUT_FILENAMES = {
    "canonical_interactions.valid.jsonl",
    "canonical_interactions.test.jsonl",
    "user_sequences.valid.jsonl",
    "user_sequences.test.jsonl",
    "holdout.jsonl",
}
FORBIDDEN_INPUT_TOKENS = {
    "holdout",
    "future_interactions",
    "future interactions",
    "eval_answers",
    "eval answers",
    "clean_10000",
    "recall_clean_10000",
    "clean_10k",
    "recall_clean_10k",
}
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
    artifact_paths: dict[str, Any] | None = None,
    quality_audit: dict[str, Any] | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    readiness_bundle_result = readiness_bundle_result or {}
    return {
        "schema_version": POOL500_SHADOW_EVIDENCE_SCHEMA_VERSION,
        "evidence_id": evidence_id,
        "shadow_mode": POOL500_SHADOW_MODE,
        "full_pool500_ready_semantics": POOL500_FULL_READY_SEMANTICS,
        "decision": artifact_gate_result.get("decision"),
        "status": artifact_gate_result.get("status"),
        "artifact_gate_schema_version": artifact_gate_result.get("schema_version"),
        "artifact_gate_decision": artifact_gate_result.get("decision"),
        "readiness_bundle_decision": readiness_bundle_result.get("decision"),
        "readiness_bundle_path": readiness_bundle_path,
        "candidate_generation_allowed": False,
        "ranking_replacement_allowed": False,
        "ranking_input_replacement_allowed": False,
        "promotion_allowed": False,
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
        "pool1000_allowed": False,
        "marker_isolation_audit": marker_audit,
        "blockers": blockers,
    }


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
    if combined.get("source_name") != "two_tower" or combined.get("canonical_source") != "two_tower":
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
    forbidden_values = [value for payload in payloads for _, value in _walk_manifest(payload) if _is_forbidden_two_tower_artifact_value(value)]
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


def _collect_manifest_inputs(*payloads: dict[str, Any]) -> list[str]:
    inputs: list[str] = []
    for payload in payloads:
        for key, value in _walk_manifest(payload):
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



def _is_forbidden_input(path: str) -> bool:
    normalized = path.replace("\\", "/").lower()
    filename = normalized.rsplit("/", 1)[-1]
    return filename in FORBIDDEN_INPUT_FILENAMES or any(token in normalized for token in FORBIDDEN_INPUT_TOKENS)


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
