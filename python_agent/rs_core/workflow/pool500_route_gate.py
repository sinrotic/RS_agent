from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any

ROOT = Path(__file__).resolve().parents[2]

from rs_core.common.config import load_config
from rs_core.common.io import iter_jsonl, read_json, write_json
from rs_core.common.runtime import enforce_project_venv

SCHEMA_VERSION = "p7_full_pool500_route_gate_v1"
ROUTE_PRECHECK_SCHEMA = "P7_ROUTE_PRECHECK"
ROUTE_SIGNATURE_SCHEMA = "full_pool500_route_signature_gate"
DEFAULT_MAIN_ROUTE_DIR = ROOT / "outputs" / "recall" / "phase_1_21_recall_coverage" / "current_main_route_pool200_source_balanced"
DEFAULT_PHASE_CONFIG = ROOT / "configs" / "recall" / "phase_1_21" / "phase_1_21_recall_coverage_pool200_experimental.yaml"
DEFAULT_BASELINE_CONFIG = ROOT / "configs" / "ranking" / "phase_1_15" / "phase_1_15_frozen_youtubednn_pool100.yaml"
DEFAULT_OUTPUT_DIR = ROOT / "outputs" / "recall" / "p7_full_pool500_main_route_continuation" / "route_precheck_gate"
EXPECTED_SOURCES = {
    "popular",
    "category",
    "semantic",
    "semantic_title_category_expansion",
    "itemcf_weak",
    "itemcf_strong",
    "co_visit_fallback_repair",
    "usercf_recall",
    "swing_recall",
    "two_tower",
}
EXPECTED_FILL_ORDER = [
    "semantic_title_category_expansion",
    "co_visit_fallback_repair",
    "usercf_recall",
    "swing_recall",
    "itemcf",
    "category",
    "popular",
]
EXPECTED_ITEMCF_EXPANSION = {"itemcf_weak", "itemcf_strong"}
EXPECTED_HOLDOUT_HASH = "927a452a731c7aac912392526fbb39de48388becb4779c0371e4b447ab6446a2"
REQUIRED_CANDIDATE_QUALITY_FIELDS = {
    "empty_candidate_users_pool500": 0,
    "empty_candidate_rate_pool500": 0.0,
    "fallback_rate_pool500": 0.0,
    "fallback_error_count_pool500": 0,
    "duplicate_user_item_rows_pool500": 0,
}
ALLOWED_POOL500_ROUTE_DIFF_FIELDS = {"candidate_pool_size", "output_root", "output_dir", "run_id", "generated_at", "audit"}


def run_p7_route_gate(
    *,
    main_route_dir: Path = DEFAULT_MAIN_ROUTE_DIR,
    phase_config_path: Path = DEFAULT_PHASE_CONFIG,
    baseline_config_path: Path = DEFAULT_BASELINE_CONFIG,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    candidate_quality_audit_path: Path | None = None,
    pool500_candidates_path: Path | None = None,
    enforce_venv: bool = True,
    overwrite: bool = False,
) -> dict[str, Any]:
    started = perf_counter()
    if enforce_venv:
        enforce_project_venv(ROOT)

    main_route_dir = main_route_dir.resolve()
    phase_config_path = phase_config_path.resolve()
    baseline_config_path = baseline_config_path.resolve()
    output_dir = output_dir.resolve()
    if output_dir.exists() and not overwrite:
        raise FileExistsError(f"Output directory already exists: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)

    route_signature = build_route_signature(main_route_dir, phase_config_path, baseline_config_path)
    route_precheck = build_route_precheck(route_signature)
    final_gate = build_continuation_final_gate(
        route_precheck=route_precheck,
        candidate_quality_audit_path=candidate_quality_audit_path,
        pool500_candidates_path=pool500_candidates_path,
    )

    required_artifacts = {
        "manifest": str(output_dir / "manifest.json"),
        "route_signature": str(output_dir / "route_signature.json"),
        "route_precheck": str(output_dir / "route_precheck.json"),
        "continuation_final_gate": str(output_dir / "continuation_final_gate.json"),
    }
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "status": route_precheck["status"],
        "decision": final_gate["decision"],
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "runtime_seconds": round(perf_counter() - started, 6),
        "scope": "p7_full_pool500_recall_only_route_gate_no_candidate_generation",
        "project_venv_required": enforce_venv,
        "output_dir": str(output_dir),
        "no_full_pool500_executed": True,
        "no_heavy_training_artifacts_created": True,
        "no_pool1000_artifacts_created": True,
        "no_ranking_replacement_artifacts_created": True,
        "required_artifacts": required_artifacts,
    }
    write_json(output_dir / "route_signature.json", route_signature)
    write_json(output_dir / "route_precheck.json", route_precheck)
    write_json(output_dir / "continuation_final_gate.json", final_gate)
    write_json(output_dir / "manifest.json", manifest)
    return manifest


def build_route_signature(main_route_dir: Path, phase_config_path: Path, baseline_config_path: Path) -> dict[str, Any]:
    main_route_dir = main_route_dir.resolve()
    manifest_path = main_route_dir / "manifest.json"
    metrics_path = main_route_dir / "metrics.json"
    frozen_candidates_path = main_route_dir / "frozen_candidates.jsonl"
    manifest = read_json(manifest_path)
    metrics = read_json(metrics_path)
    phase_config = load_config(phase_config_path)
    baseline_config = load_config(baseline_config_path)
    source_counts = dict(metrics.get("recall_source_coverage", {}))
    expected_two_tower_path = _resolve_path(baseline_config.get("two_tower_artifact_path", ""), baseline_config_path.parent)
    two_tower_audit = _two_tower_artifact_audit(expected_two_tower_path)
    route_contract_audit = _route_contract_audit(manifest, metrics, phase_config, baseline_config, phase_config_path, baseline_config_path)
    fill_order = [str(item) for item in phase_config.get("candidate_fill_order", [])]
    return {
        "schema_version": ROUTE_SIGNATURE_SCHEMA,
        "route_authority": "RECALL_METHODS_EXPERIMENT_LOG.md#24 + current_main_route_pool200_source_balanced artifacts",
        "main_route_dir": _path_signature(main_route_dir),
        "authority_artifacts": {
            "route_manifest": _path_signature(manifest_path),
            "route_metrics": _path_signature(metrics_path),
            "pool200_frozen_candidates": _path_signature(frozen_candidates_path),
            "phase_1_21_config": _path_signature(phase_config_path),
            "baseline_config": _path_signature(baseline_config_path),
        },
        "pool200_route": {
            "candidate_pool_size": int(phase_config.get("candidate_pool_size", 0)),
            "source_set": sorted(source_counts),
            "source_counts": source_counts,
            "expected_source_set": sorted(EXPECTED_SOURCES),
            "missing_expected_sources": sorted(EXPECTED_SOURCES - set(source_counts)),
            "unexpected_sources": sorted(set(source_counts) - EXPECTED_SOURCES),
        },
        "intended_pool500_route": {
            "candidate_pool_size": 500,
            "allowed_diff_only": sorted(ALLOWED_POOL500_ROUTE_DIFF_FIELDS),
            "route_diff_status": "OK" if int(phase_config.get("candidate_pool_size", 0)) == 200 else "BLOCKED",
        },
        "strategy_audit": {
            "required_strategy": "balanced_source_budget",
            "actual_strategy": phase_config.get("candidate_pool_strategy"),
            "required_fill_order": EXPECTED_FILL_ORDER,
            "actual_fill_order": fill_order,
            "itemcf_alias_expansion": sorted(_expand_fill_order(fill_order) & EXPECTED_ITEMCF_EXPANSION),
            "candidate_source_minimums": phase_config.get("candidate_source_minimums", {}),
            "candidate_source_maximums": phase_config.get("candidate_source_maximums", {}),
        },
        "two_tower_audit": two_tower_audit,
        "route_contract_audit": route_contract_audit,
        "ranking_isolation_audit": _ranking_isolation_audit(manifest),
    }


def build_route_precheck(route_signature: dict[str, Any]) -> dict[str, Any]:
    blockers = _route_blockers(route_signature)
    status = blockers[0]["code"] if blockers else "PASS"
    return {
        "schema_version": ROUTE_PRECHECK_SCHEMA,
        "status": status,
        "decision": "STOP" if blockers else "PASS_PRECHECK",
        "full_pool500_recall_only_continuation_allowed": not blockers,
        "ranking_input_replacement_allowed": False,
        "pool1000_allowed": False,
        "heavy_model_training_allowed_by_this_gate": False,
        "no_full_pool500_executed": True,
        "no_heavy_training_artifacts_created": True,
        "no_pool1000_artifacts_created": True,
        "no_ranking_replacement_artifacts_created": True,
        "blockers": blockers,
        "route_signature_hash": _stable_hash(route_signature),
        "route_signature_summary": {
            "source_set": route_signature["pool200_route"]["source_set"],
            "candidate_pool_size_diff": "200->500",
            "required_strategy": route_signature["strategy_audit"]["required_strategy"],
            "actual_strategy": route_signature["strategy_audit"]["actual_strategy"],
        },
    }


def build_continuation_final_gate(
    *,
    route_precheck: dict[str, Any],
    candidate_quality_audit_path: Path | None = None,
    pool500_candidates_path: Path | None = None,
) -> dict[str, Any]:
    route_blockers = list(route_precheck.get("blockers", []))
    quality_audit = _candidate_quality_audit(candidate_quality_audit_path, pool500_candidates_path)
    blockers = [*route_blockers, *quality_audit["blockers"]]
    route_passed = route_precheck["status"] == "PASS" and not route_blockers
    if blockers:
        decision = "STOP"
    elif quality_audit["status"] == "NOT_PROVIDED":
        decision = "DIAGNOSTIC_ONLY"
    elif route_passed and quality_audit["status"] == "PASS":
        decision = "PASS_CONTINUATION"
    else:
        decision = "STOP"
    return {
        "schema_version": "p7_continuation_final_gate_v1",
        "status": "PASS" if decision == "PASS_CONTINUATION" else "BLOCKED" if decision == "STOP" else "DIAGNOSTIC_ONLY",
        "decision": decision,
        "decision_matrix": {
            "STOP": "route blocker or candidate quality regression/missing required field",
            "DIAGNOSTIC_ONLY": "route precheck passed but no full pool500 candidate quality audit was provided",
            "PASS_CONTINUATION": "route precheck passed and candidate quality non-regression audit passed",
        },
        "full_pool500_recall_only_continuation_allowed": decision == "PASS_CONTINUATION",
        "ranking_input_replacement_allowed": False,
        "pool1000_allowed": False,
        "heavy_model_training_allowed_by_this_gate": False,
        "no_ranking_replacement_artifacts_created": True,
        "no_pool1000_artifacts_created": True,
        "no_heavy_training_artifacts_created": True,
        "candidate_quality_non_regression_check": quality_audit,
        "blockers": blockers,
    }


def _route_blockers(route_signature: dict[str, Any]) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    pool200 = route_signature["pool200_route"]
    strategy = route_signature["strategy_audit"]
    contract = route_signature["route_contract_audit"]
    ranking = route_signature["ranking_isolation_audit"]
    two_tower = route_signature["two_tower_audit"]
    if pool200["missing_expected_sources"] or pool200["unexpected_sources"]:
        blockers.append(_blocker("BLOCKED_ROUTE_SOURCE_SET", {"pool200_route": pool200}))
    if strategy["actual_strategy"] != strategy["required_strategy"] or strategy["actual_fill_order"] != strategy["required_fill_order"]:
        blockers.append(_blocker("BLOCKED_ROUTE_STRATEGY", {"strategy_audit": strategy}))
    if set(strategy["itemcf_alias_expansion"]) != EXPECTED_ITEMCF_EXPANSION:
        blockers.append(_blocker("BLOCKED_ITEMCF_ALIAS_EXPANSION", {"strategy_audit": strategy}))
    if not two_tower["artifact_exists"] or two_tower["manifest_contract_missing_paths"]:
        blockers.append(_blocker("BLOCKED_TWO_TOWER_ARTIFACT", {"two_tower_audit": two_tower}))
    elif not two_tower["sidecar_schema_valid"]:
        blockers.append(_blocker("BLOCKED_TWO_TOWER_SIDECAR_SCHEMA", {"two_tower_audit": two_tower}))
    elif not two_tower["hash_freshness_pass"]:
        blockers.append(_blocker("BLOCKED_TWO_TOWER_HASH_FRESHNESS", {"two_tower_audit": two_tower}))
    elif int(pool200["source_counts"].get("two_tower", 0)) <= 0:
        blockers.append(_blocker("BLOCKED_TWO_TOWER_ROUTE_ZERO_ROWS", {"two_tower_rows": pool200["source_counts"].get("two_tower", 0)}))
    if not contract["pass"]:
        blockers.append(_blocker("BLOCKED_ROUTE_CONTRACT_AUDIT", {"route_contract_audit": contract}))
    if not ranking["pass"]:
        blockers.append(_blocker("BLOCKED_RANKING_ISOLATION", {"ranking_isolation_audit": ranking}))
    return blockers


def _route_contract_audit(
    manifest: dict[str, Any],
    metrics: dict[str, Any],
    phase_config: dict[str, Any],
    baseline_config: dict[str, Any],
    phase_config_path: Path,
    baseline_config_path: Path,
) -> dict[str, Any]:
    ranking_disabled = manifest.get("ranking_rerank_disabled_checks", {})
    checks = {
        "top_k": baseline_config.get("top_k") == 5,
        "baseline_config": _path_signature(baseline_config_path),
        "phase_1_21_config": _path_signature(phase_config_path),
        "evaluation_mode": manifest.get("evaluation_mode") == "valid_test" and metrics.get("evaluation_mode") == "valid_test",
        "limit_users": manifest.get("limit_users") == 500,
        "users_with_holdout": manifest.get("users_with_holdout") == 138 and metrics.get("users_with_holdout") == 138,
        "holdout_user_ids_hash": manifest.get("holdout_user_ids_hash") == EXPECTED_HOLDOUT_HASH,
        "ranking_rerank_disabled_checks": _all_ranking_disabled(ranking_disabled),
        "no_heavy_training_artifacts_created": True,
        "no_pool1000_artifacts_created": True,
        "no_ranking_replacement_artifacts_created": True,
    }
    pass_checks = all(value is True or isinstance(value, dict) for value in checks.values())
    return {"pass": pass_checks, "checks": checks, "ranking_rerank_disabled_checks": ranking_disabled}


def _ranking_isolation_audit(manifest: dict[str, Any]) -> dict[str, Any]:
    disabled = manifest.get("ranking_rerank_disabled_checks", {})
    return {
        "pass": _all_ranking_disabled(disabled),
        "ranking_rerank_disabled_checks": disabled,
        "pool500_as_ranking_input": False,
        "frozen_pool200_ranking_baseline_replaced": False,
    }


def _two_tower_artifact_audit(artifact_manifest_path: Path) -> dict[str, Any]:
    audit: dict[str, Any] = {
        "artifact_manifest": _path_signature(artifact_manifest_path),
        "artifact_exists": artifact_manifest_path.is_file(),
        "manifest_contract_missing_paths": [],
        "sidecar_schema_valid": False,
        "hash_freshness_pass": False,
        "resolved_contract": {},
    }
    if not artifact_manifest_path.is_file():
        return audit
    manifest = read_json(artifact_manifest_path)
    contract = manifest.get("contract", {})
    missing_paths = []
    resolved_contract = {}
    for name in ("train_config", "model", "item_embeddings", "user_embeddings", "item_id_map", "user_id_map", "train_metrics", "recall_index"):
        path = _resolve_path(contract.get(name, ""), artifact_manifest_path.parent)
        resolved_contract[name] = _path_signature(path)
        if not path.is_file():
            missing_paths.append(name)
    audit["manifest_contract_missing_paths"] = missing_paths
    audit["resolved_contract"] = resolved_contract
    sidecar_manifest_path = artifact_manifest_path.parent / "two_tower_seed_manifest.json"
    sidecar_path = artifact_manifest_path.parent / "two_tower_seed_neighbors.jsonl"
    audit["sidecar_manifest"] = _path_signature(sidecar_manifest_path)
    audit["sidecar"] = _path_signature(sidecar_path)
    if sidecar_manifest_path.is_file():
        sidecar_manifest = read_json(sidecar_manifest_path)
        audit["sidecar_schema_valid"] = sidecar_manifest.get("schema_version") == "two_tower_seed_neighbors_v1" and sidecar_manifest.get("source") == "two_tower_seed"
        audit["sidecar_manifest_hashes"] = {
            "embedding_sha256": sidecar_manifest.get("embedding_sha256"),
            "sidecar_sha256": sidecar_manifest.get("sidecar_sha256"),
            "config_sha256": sidecar_manifest.get("config_sha256"),
        }
        actual_embedding_hash = _sha256_file(artifact_manifest_path.parent / "item_embeddings.jsonl") if (artifact_manifest_path.parent / "item_embeddings.jsonl").is_file() else None
        actual_sidecar_hash = _sha256_file(sidecar_path) if sidecar_path.is_file() else None
        actual_config_hash = _sha256_file(artifact_manifest_path.parent / "train_config.json") if (artifact_manifest_path.parent / "train_config.json").is_file() else None
        audit["actual_hashes"] = {
            "embedding_sha256": actual_embedding_hash,
            "sidecar_sha256": actual_sidecar_hash,
            "config_sha256": actual_config_hash,
        }
        audit["hash_freshness_pass"] = (
            sidecar_manifest.get("embedding_sha256") == actual_embedding_hash
            and sidecar_manifest.get("sidecar_sha256") == actual_sidecar_hash
            and sidecar_manifest.get("config_sha256") == actual_config_hash
        )
    return audit


def _candidate_quality_audit(candidate_quality_audit_path: Path | None, pool500_candidates_path: Path | None) -> dict[str, Any]:
    if candidate_quality_audit_path is None and pool500_candidates_path is None:
        return {"status": "NOT_PROVIDED", "blockers": [], "required_fields": REQUIRED_CANDIDATE_QUALITY_FIELDS}
    audit = read_json(candidate_quality_audit_path) if candidate_quality_audit_path else {}
    blockers = []
    for field, expected in REQUIRED_CANDIDATE_QUALITY_FIELDS.items():
        if field not in audit:
            blockers.append(_blocker("BLOCKED_MISSING_CANDIDATE_QUALITY_AUDIT_FIELD", {"missing_field": field}))
        elif audit[field] != expected:
            blockers.append(_blocker("BLOCKED_CANDIDATE_QUALITY_NON_REGRESSION", {"field": field, "expected": expected, "actual": audit[field]}))
    if pool500_candidates_path is not None:
        duplicate_count = _duplicate_user_item_rows(pool500_candidates_path)
        audit["duplicate_user_item_rows_pool500"] = duplicate_count
        if duplicate_count != 0:
            blockers.append(_blocker("BLOCKED_CANDIDATE_QUALITY_NON_REGRESSION", {"field": "duplicate_user_item_rows_pool500", "expected": 0, "actual": duplicate_count}))
    return {
        "status": "PASS" if not blockers else blockers[0]["code"],
        "blockers": blockers,
        "required_fields": REQUIRED_CANDIDATE_QUALITY_FIELDS,
        "audit": audit,
    }


def _duplicate_user_item_rows(path: Path) -> int:
    counts: Counter[tuple[str, str]] = Counter()
    for row in iter_jsonl(path):
        user_id = str(row.get("user_id", ""))
        item_id = str(row.get("item_id", row.get("parent_asin", "")))
        if user_id and item_id:
            counts[(user_id, item_id)] += 1
    return sum(count - 1 for count in counts.values() if count > 1)


def _all_ranking_disabled(checks: dict[str, Any]) -> bool:
    required_false = ["ltr_model.enabled", "ranking_v2.enabled", "item_feature_rerank.enabled", "source_aware_fusion.enabled"]
    return all(checks.get(key) is False for key in required_false) and checks.get("include_ranking_v2") == "not enabled" and checks.get("version") == '!= "ltr_v2"' and checks.get("feature_version") == '!= "ranking_v2"'


def _expand_fill_order(fill_order: list[str]) -> set[str]:
    expanded = set(fill_order)
    if "itemcf" in expanded:
        expanded.remove("itemcf")
        expanded.update(EXPECTED_ITEMCF_EXPANSION)
    return expanded


def _path_signature(path: Path) -> dict[str, Any]:
    path = path.resolve()
    return {
        "canonical_path": str(path),
        "exists": path.exists(),
        "sha256": _sha256_file(path) if path.is_file() else None,
    }


def _resolve_path(value: Any, relative_to: Path) -> Path:
    path = Path(str(value))
    if path.is_absolute():
        return path.resolve()
    candidate = (ROOT / path).resolve()
    if candidate.exists():
        return candidate
    return (relative_to / path).resolve()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _stable_hash(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _blocker(code: str, evidence: dict[str, Any]) -> dict[str, Any]:
    return {"code": code, "severity": "blocker", "evidence": evidence}


