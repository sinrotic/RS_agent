from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from rs_core.workflow.full_data_pool500_route_gate import canonical_manifest_sha256

VALID_ITEMCF_SOURCES = {"itemcf_weak", "itemcf_strong"}
PER_SOURCE_METRIC_CONTRACT_SCHEMA_VERSION = "pool500_per_source_metric_contract.v1"
IN_UNIVERSE_DENOMINATOR_SCHEMA_VERSION = "in_universe_denominator.v1"
STAGE_GATE_CHECKLIST_SCHEMA_VERSION = "pool500_stage_gate_verifier_checklist.v1"
SUCCESS_CRITERIA_SCHEMA_VERSION = "itemcf_success_criteria.v1"
TEST_ATTEMPT_LEDGER_SCHEMA_VERSION = "itemcf_test_attempt_ledger.v1"
REMOTE_PROVENANCE_SCHEMA_VERSION = "itemcf_remote_provenance_bundle.v1"
POOL_RANKING_FREEZE_SCHEMA_VERSION = "pool200_ranking_freeze_assertions.v1"
EVALUATION_ONLY_BOUNDARY = "只用于评估 denominator 与命中统计，不得作为训练、建边、候选生成或 rerank 输入"
FORBIDDEN_ITEMCF_INPUT_FILENAMES = {
    "canonical_interactions.valid.jsonl",
    "canonical_interactions.test.jsonl",
    "canonical_items.all.jsonl",
    "user_sequences.valid.jsonl",
    "user_sequences.test.jsonl",
    "holdout.jsonl",
}
FORBIDDEN_ITEMCF_INPUT_TOKENS = {
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
}
REQUIRED_PER_SOURCE_METRICS = {
    "candidate_count",
    "unique_item_count",
    "user_coverage",
    "hit_by_k",
    "recall_by_k",
    "source_only_recall_by_k",
    "source_ablation_delta_by_k",
    "overlap_with_other_sources",
}
REQUIRED_STAGE_GATE_CHECKS = {
    "artifact_paths_check",
    "required_fields_check",
    "hash_check",
    "forbidden_input_check",
    "route_ranking_isolation_check",
    "underfill_duplication_source_budget_check",
    "remote_provenance_check",
}
REQUIRED_REMOTE_PROVENANCE_FIELDS = {
    "command",
    "env",
    "git_commit",
    "git_dirty",
    "input_manifest_hash",
    "method_dataset_hash",
    "hostname",
    "resource_audit",
    "output_artifact_hashes",
    "local_revalidation",
}


def build_pool_ranking_freeze_assertions(**overrides: Any) -> dict[str, Any]:
    assertions: dict[str, Any] = {
        "schema_version": POOL_RANKING_FREEZE_SCHEMA_VERSION,
        "candidate_fill_order_changed": False,
        "pool200_authority_changed": False,
        "ranking_baseline_changed": False,
        "ranking_top_k_changed": False,
        "ranking_route_changed": False,
        "ranking_input_replacement": False,
        "new_itemcf_sources_are_source_artifacts_only": True,
    }
    assertions.update(overrides)
    assertions["hash"] = canonical_manifest_sha256({key: value for key, value in assertions.items() if key != "hash"})
    return assertions


def validate_pool_ranking_freeze_assertions(assertions: dict[str, Any]) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    if assertions.get("schema_version") != POOL_RANKING_FREEZE_SCHEMA_VERSION:
        blockers.append(_blocker("POOL_RANKING_FREEZE_SCHEMA_VERSION_MISMATCH", {"schema_version": assertions.get("schema_version")}))
    forbidden_true_fields = (
        "candidate_fill_order_changed",
        "pool200_authority_changed",
        "ranking_baseline_changed",
        "ranking_top_k_changed",
        "ranking_route_changed",
        "ranking_input_replacement",
    )
    for field in forbidden_true_fields:
        if bool(assertions.get(field)):
            blockers.append(_blocker("POOL200_RANKING_FREEZE_VIOLATED", {"field": field, "value": assertions.get(field)}))
    if assertions.get("new_itemcf_sources_are_source_artifacts_only") is not True:
        blockers.append(_blocker("ITEMCF_SOURCE_ARTIFACT_ONLY_ASSERTION_REQUIRED", {"value": assertions.get("new_itemcf_sources_are_source_artifacts_only")}))
    expected_hash = canonical_manifest_sha256({key: value for key, value in assertions.items() if key != "hash"})
    if assertions.get("hash") and assertions.get("hash") != expected_hash:
        blockers.append(_blocker("POOL_RANKING_FREEZE_HASH_MISMATCH", {"expected": expected_hash, "actual": assertions.get("hash")}))
    return _result(blockers, hash=expected_hash)


def reject_forbidden_itemcf_input(path: str | Path) -> None:
    if is_forbidden_itemcf_input(path):
        raise ValueError(f"Forbidden label/eval path for ItemCF formal source: {path}")


def is_forbidden_itemcf_input(path: str | Path) -> bool:
    normalized = "/" + str(path).replace("\\", "/").lower().strip("/")
    filename = normalized.rsplit("/", 1)[-1]
    return filename in FORBIDDEN_ITEMCF_INPUT_FILENAMES or any(token in normalized for token in FORBIDDEN_ITEMCF_INPUT_TOKENS)


def build_per_source_metric_contract(sources: set[str] | list[str] | tuple[str, ...] = tuple(sorted(VALID_ITEMCF_SOURCES))) -> dict[str, Any]:
    source_contract = {
        source: {
            "required_metrics": sorted(REQUIRED_PER_SOURCE_METRICS),
            "evaluation_boundary": "per-source contribution and ablation metrics only; not a training input",
        }
        for source in sorted(str(source) for source in sources)
    }
    return {
        "schema_version": PER_SOURCE_METRIC_CONTRACT_SCHEMA_VERSION,
        "sources": source_contract,
        "raw_and_in_universe_required": True,
        "source_only_and_ablation_required": True,
    }


def validate_per_source_metric_contract(contract: dict[str, Any]) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    if contract.get("schema_version") != PER_SOURCE_METRIC_CONTRACT_SCHEMA_VERSION:
        blockers.append(_blocker("PER_SOURCE_METRIC_SCHEMA_VERSION_MISMATCH", {"schema_version": contract.get("schema_version")}))
    sources = contract.get("sources")
    if not isinstance(sources, dict):
        blockers.append(_blocker("PER_SOURCE_METRIC_SOURCES_REQUIRED", {"type": type(sources).__name__}))
        sources = {}
    missing_sources = sorted(VALID_ITEMCF_SOURCES - set(sources))
    if missing_sources:
        blockers.append(_blocker("ITEMCF_PER_SOURCE_METRICS_MISSING", {"sources": missing_sources}))
    for source, source_contract in sources.items():
        metrics = set(source_contract.get("required_metrics") or []) if isinstance(source_contract, dict) else set()
        missing_metrics = sorted(REQUIRED_PER_SOURCE_METRICS - metrics)
        if missing_metrics:
            blockers.append(_blocker("PER_SOURCE_METRIC_KEYS_MISSING", {"source": source, "metrics": missing_metrics}))
    if contract.get("raw_and_in_universe_required") is not True:
        blockers.append(_blocker("RAW_AND_IN_UNIVERSE_METRICS_REQUIRED", {"value": contract.get("raw_and_in_universe_required")}))
    return _result(blockers)


def build_in_universe_denominator_report(
    *,
    universe_source: str,
    train_item_set_hash: str,
    label_split: str,
    label_total_count: int,
    label_in_universe_count: int,
    metrics_by_k: dict[str, Any],
    source_breakdown: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if label_total_count < 0 or label_in_universe_count < 0 or label_in_universe_count > label_total_count:
        raise ValueError("label counts must be non-negative and in-universe count must not exceed total count")
    label_out_of_universe_count = label_total_count - label_in_universe_count
    return {
        "schema_version": IN_UNIVERSE_DENOMINATOR_SCHEMA_VERSION,
        "evaluation_only": True,
        "evaluation_only_boundary": EVALUATION_ONLY_BOUNDARY,
        "universe_source": universe_source,
        "train_item_set_hash": train_item_set_hash,
        "label_split": label_split,
        "label_total_count": label_total_count,
        "label_in_universe_count": label_in_universe_count,
        "label_out_of_universe_count": label_out_of_universe_count,
        "label_in_universe_ratio": _ratio(label_in_universe_count, label_total_count),
        "metrics_by_k": metrics_by_k,
        "source_breakdown": source_breakdown or {source: {} for source in sorted(VALID_ITEMCF_SOURCES)},
    }


def validate_in_universe_denominator_report(report: dict[str, Any]) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    if report.get("schema_version") != IN_UNIVERSE_DENOMINATOR_SCHEMA_VERSION:
        blockers.append(_blocker("IN_UNIVERSE_SCHEMA_VERSION_MISMATCH", {"schema_version": report.get("schema_version")}))
    if report.get("evaluation_only") is not True:
        blockers.append(_blocker("IN_UNIVERSE_EVALUATION_ONLY_REQUIRED", {"evaluation_only": report.get("evaluation_only")}))
    if report.get("evaluation_only_boundary") != EVALUATION_ONLY_BOUNDARY:
        blockers.append(_blocker("IN_UNIVERSE_BOUNDARY_REQUIRED", {"evaluation_only_boundary": report.get("evaluation_only_boundary")}))
    if report.get("label_split") not in {"valid", "test"}:
        blockers.append(_blocker("IN_UNIVERSE_LABEL_SPLIT_MUST_BE_EVAL", {"label_split": report.get("label_split")}))
    for field in ("universe_source", "train_item_set_hash", "metrics_by_k", "source_breakdown"):
        if field not in report:
            blockers.append(_blocker("IN_UNIVERSE_FIELD_MISSING", {"field": field}))
    total = int(report.get("label_total_count", -1))
    in_universe = int(report.get("label_in_universe_count", -1))
    out_of_universe = int(report.get("label_out_of_universe_count", -1))
    if total < 0 or in_universe < 0 or out_of_universe < 0 or in_universe + out_of_universe != total:
        blockers.append(_blocker("IN_UNIVERSE_LABEL_COUNTS_INVALID", {"total": total, "in_universe": in_universe, "out_of_universe": out_of_universe}))
    metrics_by_k = report.get("metrics_by_k") if isinstance(report.get("metrics_by_k"), dict) else {}
    for k, metrics in metrics_by_k.items():
        missing = [field for field in (f"hit_in_universe@{k}", f"recall_in_universe@{k}", f"raw_hit@{k}", f"raw_recall@{k}") if field not in metrics]
        if missing:
            blockers.append(_blocker("IN_UNIVERSE_METRICS_BY_K_FIELD_MISSING", {"k": k, "fields": missing}))
    return _result(blockers)


def build_stage_gate_verifier_checklist(*, stage: str, artifact_paths: dict[str, str], checks: dict[str, bool], verifier: str | None = None) -> dict[str, Any]:
    pass_fail = "PASS" if all(bool(checks.get(check)) for check in REQUIRED_STAGE_GATE_CHECKS) else "BLOCKED"
    return {
        "schema_version": STAGE_GATE_CHECKLIST_SCHEMA_VERSION,
        "stage": stage,
        "artifact_paths": artifact_paths,
        "checks": {check: bool(checks.get(check)) for check in sorted(REQUIRED_STAGE_GATE_CHECKS)},
        "pass_fail": pass_fail,
        "verifier": verifier,
        "verifier_timestamp": datetime.now(timezone.utc).isoformat(),
    }


def validate_stage_gate_verifier_checklist(checklist: dict[str, Any]) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    if checklist.get("schema_version") != STAGE_GATE_CHECKLIST_SCHEMA_VERSION:
        blockers.append(_blocker("STAGE_GATE_CHECKLIST_SCHEMA_VERSION_MISMATCH", {"schema_version": checklist.get("schema_version")}))
    if not checklist.get("stage"):
        blockers.append(_blocker("STAGE_GATE_STAGE_REQUIRED", {}))
    if not isinstance(checklist.get("artifact_paths"), dict):
        blockers.append(_blocker("STAGE_GATE_ARTIFACT_PATHS_REQUIRED", {"type": type(checklist.get("artifact_paths")).__name__}))
    checks = checklist.get("checks") if isinstance(checklist.get("checks"), dict) else {}
    missing_checks = sorted(REQUIRED_STAGE_GATE_CHECKS - set(checks))
    failed_checks = sorted(check for check, value in checks.items() if value is not True)
    if missing_checks:
        blockers.append(_blocker("STAGE_GATE_CHECKS_MISSING", {"checks": missing_checks}))
    if failed_checks:
        blockers.append(_blocker("STAGE_GATE_CHECKS_FAILED", {"checks": failed_checks}))
    if checklist.get("pass_fail") != "PASS":
        blockers.append(_blocker("STAGE_GATE_PASS_REQUIRED", {"pass_fail": checklist.get("pass_fail")}))
    return _result(blockers)


def validate_success_criteria(criteria: dict[str, Any]) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    if criteria.get("schema_version") != SUCCESS_CRITERIA_SCHEMA_VERSION:
        blockers.append(_blocker("SUCCESS_CRITERIA_SCHEMA_VERSION_MISMATCH", {"schema_version": criteria.get("schema_version")}))
    if criteria.get("frozen_before_test") is not True:
        blockers.append(_blocker("SUCCESS_CRITERIA_MUST_BE_FROZEN_BEFORE_TEST", {"frozen_before_test": criteria.get("frozen_before_test")}))
    for field in ("baseline_config_hash", "chosen_config_hash", "primary_k", "threshold_derivation", "minimum_pass_conditions"):
        if field not in criteria:
            blockers.append(_blocker("SUCCESS_CRITERIA_FIELD_MISSING", {"field": field}))
    threshold_derivation = criteria.get("threshold_derivation") if isinstance(criteria.get("threshold_derivation"), dict) else {}
    if threshold_derivation.get("approved_by_verifier") is not True:
        blockers.append(_blocker("SUCCESS_CRITERIA_VERIFIER_APPROVAL_REQUIRED", {"approved_by_verifier": threshold_derivation.get("approved_by_verifier")}))
    expected_hash = canonical_manifest_sha256({key: value for key, value in criteria.items() if key != "success_criteria_hash"})
    if criteria.get("success_criteria_hash") and criteria.get("success_criteria_hash") != expected_hash:
        blockers.append(_blocker("SUCCESS_CRITERIA_HASH_MISMATCH", {"expected": expected_hash, "actual": criteria.get("success_criteria_hash")}))
    return _result(blockers, success_criteria_hash=expected_hash)


def build_test_attempt_ledger_record(
    *,
    attempt_id: str,
    chosen_config_hash: str,
    success_criteria_hash: str,
    reason_for_attempt: str,
    test_split_hash: str,
    metrics_path: str,
    pass_fail: str,
    whether_test_result_informed_next_cycle: bool = False,
) -> dict[str, Any]:
    return {
        "schema_version": TEST_ATTEMPT_LEDGER_SCHEMA_VERSION,
        "attempt_id": attempt_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "chosen_config_hash": chosen_config_hash,
        "success_criteria_hash": success_criteria_hash,
        "reason_for_attempt": reason_for_attempt,
        "test_split_hash": test_split_hash,
        "metrics_path": metrics_path,
        "pass_fail": pass_fail,
        "whether_test_result_informed_next_cycle": whether_test_result_informed_next_cycle,
    }


def append_test_attempt_ledger_record(ledger_path: Path, record: dict[str, Any]) -> None:
    validation = validate_test_attempt_ledger_record(record)
    if validation["status"] != "PASS":
        raise ValueError(f"invalid test attempt ledger record: {validation['blockers']}")
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    with ledger_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def validate_test_attempt_ledger_record(record: dict[str, Any]) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    if record.get("schema_version") != TEST_ATTEMPT_LEDGER_SCHEMA_VERSION:
        blockers.append(_blocker("TEST_ATTEMPT_LEDGER_SCHEMA_VERSION_MISMATCH", {"schema_version": record.get("schema_version")}))
    for field in ("attempt_id", "timestamp", "chosen_config_hash", "success_criteria_hash", "reason_for_attempt", "test_split_hash", "metrics_path", "pass_fail"):
        if not record.get(field):
            blockers.append(_blocker("TEST_ATTEMPT_LEDGER_FIELD_MISSING", {"field": field}))
    if record.get("pass_fail") not in {"PASS", "FAIL"}:
        blockers.append(_blocker("TEST_ATTEMPT_LEDGER_PASS_FAIL_INVALID", {"pass_fail": record.get("pass_fail")}))
    if record.get("whether_test_result_informed_next_cycle") is not False:
        blockers.append(_blocker("TEST_RESULT_MUST_NOT_INFORM_NEXT_CYCLE", {"value": record.get("whether_test_result_informed_next_cycle")}))
    return _result(blockers)


def validate_remote_provenance_bundle(bundle: dict[str, Any]) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    if bundle.get("schema_version") != REMOTE_PROVENANCE_SCHEMA_VERSION:
        blockers.append(_blocker("REMOTE_PROVENANCE_SCHEMA_VERSION_MISMATCH", {"schema_version": bundle.get("schema_version")}))
    missing_fields = sorted(field for field in REQUIRED_REMOTE_PROVENANCE_FIELDS if field not in bundle)
    if missing_fields:
        blockers.append(_blocker("REMOTE_PROVENANCE_FIELDS_MISSING", {"fields": missing_fields}))
    resource_audit = bundle.get("resource_audit") if isinstance(bundle.get("resource_audit"), dict) else {}
    for field in ("peak_rss", "disk_usage", "runtime_seconds", "shard_count"):
        if field not in resource_audit:
            blockers.append(_blocker("REMOTE_RESOURCE_AUDIT_FIELD_MISSING", {"field": field}))
    local_revalidation = bundle.get("local_revalidation") if isinstance(bundle.get("local_revalidation"), dict) else {}
    for field in ("manifest_gate", "hash_signature", "route_gate_smoke", "per_source_evaluation_smoke"):
        if local_revalidation.get(field) != "PASS":
            blockers.append(_blocker("REMOTE_LOCAL_REVALIDATION_PASS_REQUIRED", {"field": field, "value": local_revalidation.get(field)}))
    return _result(blockers)


def _ratio(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return numerator / denominator


def _result(blockers: list[dict[str, Any]], **extra: Any) -> dict[str, Any]:
    return {"status": "PASS" if not blockers else "BLOCKED", "blockers": blockers, **extra}


def _blocker(code: str, evidence: dict[str, Any]) -> dict[str, Any]:
    return {"code": code, "severity": "blocker", "evidence": evidence}
