from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rs_core.common.io import iter_jsonl, read_json, write_json
from rs_core.common.runtime import enforce_project_venv

SCHEMA_VERSION = "pool500_method_dataset_audit_evidence_v1"
DEFAULT_GOVERNANCE_MANIFEST = ROOT / "outputs" / "recall" / "data_governance" / "train_only_v1" / "manifest.json"
DEFAULT_METHOD_DATASET_ROOT = ROOT / "outputs" / "recall" / "pool500_method_datasets"
DEFAULT_OUTPUT_PATH = DEFAULT_METHOD_DATASET_ROOT / "audit_evidence_v1" / "diagnostic_audit_report.json"
COLLAB_OUTPUT_WHITELIST = {"method_dataset_manifest.json", "method_dataset_rows.jsonl", "README.md", "TODO.md", "migration_punchlist.md"}
TWO_TOWER_OUTPUT_WHITELIST = {"method_dataset_manifest.json", "two_tower_train_samples.jsonl", "negative_item_universe.jsonl", "training_item_universe.jsonl", "leakage_audit.json"}
LEGAL_METHOD_DATASET_SCHEMAS = {
    "pool500_method_dataset_v1",
    "pool500_two_tower_method_dataset_v1",
}
LEGACY_CAPPED_SCHEMAS = {"pool500_capped_unified_train_behavior_dataset_v1", "pool500_capped_method_view_v1"}
FORBIDDEN_SCOPE_TOKENS = {"valid", "validation", "test", "holdout", "lopo", "eval_label", "oracle", "clean_10000", "pool1000"}
FORBIDDEN_FIELDS = {
    "source_index_manifest",
    "source_index_manifest_path",
    "artifact_manifest_path",
    "embedding_path",
    "index_path",
    "candidates",
    "candidates_path",
    "candidate_path",
    "readiness_contract",
    "promotion_manifest",
    "promotion_manifest_path",
    "full_pool500_ready",
    "full_pool500_ready_claimed",
    "ready",
}
ALLOWED_GUARDRAIL_KEYS = {"candidate_generation_allowed", "ranking_input_replacement_allowed", "promotion_allowed", "final_pool500_ready_claimed"}
READY_TEXT = {"ready", "full_ready", "full_pool500_ready", "promotion_ready", "promote_ready"}
TWO_TOWER_REQUIRED_UNIVERSE_KEYS = {
    "training_item_universe",
    "retrieval_item_universe",
    "global_negative_universe",
    "per_user_negative_universe_policy",
    "per_example_negative_universe_policy",
    "eval_target_universe",
    "eligible_target_universe",
}
TWO_TOWER_REQUIRED_STATS = {
    "raw_target_occurrence_count",
    "eligible_target_occurrence_count",
    "excluded_target_occurrence_count",
    "sample_target_items_in_training_universe_count",
    "sample_target_items_missing_training_universe_count",
    "sample_target_items_in_negative_universe_count",
    "sample_target_items_outside_negative_universe_count",
    "used_negative_distinct_item_count",
    "used_negative_item_occurrence_count",
    "used_negative_item_coverage_ratio",
    "negative_item_usage_top1_count",
    "negative_item_usage_top10_share",
    "negative_item_count_mean",
    "negative_item_count_under_requested_count",
    "training_item_universe_target_items_missing_p1_quality",
    "training_item_universe_target_items_missing_frequency",
    "training_item_universe_positive_target_metadata_incomplete_count",
    "retrieval_item_universe_available",
    "retrieval_item_universe_coverage_status",
    "eval_target_universe_available",
    "eval_target_universe_coverage_status",
}
TWO_TOWER_BOUNDARY_RESTRICTED_KEYS = {"label_artifacts", "oracle_artifacts", "diagnostic_oracle_artifacts"}
TWO_TOWER_FORBIDDEN_DATA_USES = {"training", "negative_sampling", "index_build", "official_candidate_generation"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate diagnostic-only pool500 method dataset audit evidence.")
    parser.add_argument("--governance-manifest", default=str(DEFAULT_GOVERNANCE_MANIFEST))
    parser.add_argument("--method-dataset", action="append", default=[])
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT_PATH))
    parser.add_argument("--skip-venv-check", action="store_true")
    return parser.parse_args()


def validate_pool500_method_dataset_audit_evidence(
    *,
    governance_manifest_path: Path = DEFAULT_GOVERNANCE_MANIFEST,
    method_dataset_paths: Iterable[Path] = (),
    output_path: Path | None = DEFAULT_OUTPUT_PATH,
    enforce_venv: bool = True,
) -> dict[str, Any]:
    if enforce_venv:
        enforce_project_venv(ROOT)

    blockers: list[str] = []
    diagnostics: dict[str, Any] = {}
    migration_punchlist: list[str] = []
    governance_manifest_path = Path(governance_manifest_path).resolve()
    diagnostics["requested_governance_manifest_path"] = str(governance_manifest_path)

    audited_manifests = []
    for raw_path in method_dataset_paths:
        audit = _audit_method_dataset_manifest(Path(raw_path).resolve())
        audited_manifests.append(audit)
        blockers.extend(audit["blockers"])
        migration_punchlist.extend(audit["migration_punchlist"])

    if not audited_manifests:
        governance_diagnostics, governance_blockers = _audit_governance(governance_manifest_path)
        diagnostics["p1_governance"] = governance_diagnostics
        blockers.extend(governance_blockers)
        migration_punchlist.append("提供至少一个 P2 method_dataset_manifest.json 路径或其所在目录用于审计。")

    report = {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS" if not blockers else "BLOCKED",
        "diagnostic_only": True,
        "candidate_generation_allowed": False,
        "ranking_input_replacement_allowed": False,
        "promotion_allowed": False,
        "final_pool500_ready_claimed": False,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "governance_manifest_path": str(governance_manifest_path),
        "audited_manifest_count": len(audited_manifests),
        "audited_manifests": audited_manifests,
        "blockers": blockers,
        "diagnostics": diagnostics,
        "migration_punchlist": sorted(set(migration_punchlist)),
    }
    if output_path is not None:
        write_json(output_path, report)
    return report


def _audit_governance(manifest_path: Path) -> tuple[dict[str, Any], list[str]]:
    blockers: list[str] = []
    diagnostics: dict[str, Any] = {"manifest_path": str(manifest_path), "status": "PASS"}
    if not manifest_path.is_file():
        return {**diagnostics, "status": "BLOCKED"}, [f"missing_governance_manifest:{manifest_path}"]

    manifest = read_json(manifest_path)
    diagnostics["schema_version"] = manifest.get("schema_version")
    diagnostics["train_only"] = manifest.get("train_only")
    if manifest.get("schema_version") != "train_only_data_governance_v1":
        blockers.append("p1_governance_schema_version_not_train_only_data_governance_v1")
    if manifest.get("train_only") is not True:
        blockers.append("p1_governance_manifest_not_train_only")

    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, dict):
        return {**diagnostics, "status": "BLOCKED"}, [*blockers, "p1_governance_missing_artifacts"]

    artifact_audits = {}
    for name in ("user_quality_profile", "item_quality_profile", "item_frequency_train"):
        path = _resolve_repo_path(manifest_path, artifacts.get(name)) if artifacts.get(name) else None
        if path is None or not path.is_file():
            blockers.append(f"missing_p1_artifact:{name}")
            artifact_audits[name] = {"status": "BLOCKED", "path": str(path) if path else None}
            continue
        artifact_audits[name] = {"status": "PASS", "path": str(path), "sha256": _file_sha256(path)}

    user_profile = artifact_audits.get("user_quality_profile", {})
    item_profile = artifact_audits.get("item_quality_profile", {})
    item_frequency = artifact_audits.get("item_frequency_train", {})
    if user_profile.get("status") == "PASS":
        missing = _jsonl_missing_field_count(Path(str(user_profile["path"])), "quality_bucket_v2")
        artifact_audits["user_quality_profile"]["missing_quality_bucket_v2_rows"] = missing
        if missing:
            blockers.append("p1_user_quality_profile_missing_quality_bucket_v2")
    if item_profile.get("status") == "PASS":
        missing = _jsonl_missing_field_count(Path(str(item_profile["path"])), "quality_bucket_v2")
        artifact_audits["item_quality_profile"]["missing_quality_bucket_v2_rows"] = missing
        if missing:
            blockers.append("p1_item_quality_profile_missing_quality_bucket_v2")
    if item_frequency.get("status") == "PASS":
        artifact_audits["item_frequency_train"]["row_count"] = _jsonl_row_count(Path(str(item_frequency["path"])))

    diagnostics["artifacts"] = artifact_audits
    diagnostics["status"] = "PASS" if not blockers else "BLOCKED"
    return diagnostics, blockers


def _audit_method_dataset_manifest(path: Path) -> dict[str, Any]:
    manifest_path = path / "method_dataset_manifest.json" if path.is_dir() else path
    audit = {
        "manifest_path": str(manifest_path),
        "status": "PASS",
        "method": None,
        "schema_version": None,
        "train_only": None,
        "blockers": [],
        "diagnostics": {},
        "migration_punchlist": [],
    }
    blockers = audit["blockers"]
    diagnostics = audit["diagnostics"]
    migration_punchlist = audit["migration_punchlist"]
    if not manifest_path.is_file():
        blockers.append(f"missing_method_dataset_manifest:{manifest_path}")
        migration_punchlist.append("补齐 P2 method_dataset_manifest.json；审计器不会用候选/source manifest 替代它。")
        audit["status"] = "BLOCKED"
        return audit

    manifest = read_json(manifest_path)
    schema_version = manifest.get("schema_version")
    method = str(manifest.get("source_method") or manifest.get("method") or manifest_path.parent.name)
    audit["method"] = method
    audit["schema_version"] = schema_version
    audit["train_only"] = manifest.get("train_only")
    diagnostics["manifest_status"] = manifest.get("status")

    if schema_version in LEGACY_CAPPED_SCHEMAS:
        blockers.append(f"legacy_capped_method_dataset_schema_not_allowed_as_p2_main:{schema_version}")
        migration_punchlist.append("废弃 shared capped base；P2 主路改为 governance_train_only → method-specific dataset。")
    elif schema_version not in LEGAL_METHOD_DATASET_SCHEMAS:
        blockers.append(f"unsupported_method_dataset_schema:{schema_version}")
    if manifest.get("train_only") is not True:
        blockers.append(f"method_dataset_not_train_only:{method}")
    if manifest.get("status") == "BLOCKED":
        blockers.append(f"method_dataset_declares_blocked:{method}")
    if manifest.get("candidate_generation_allowed") is not False:
        blockers.append(f"candidate_generation_allowed_not_false:{method}")
    if manifest.get("ranking_input_replacement_allowed") is not False:
        blockers.append(f"ranking_input_replacement_allowed_not_false:{method}")
    if manifest.get("promotion_allowed") is not False:
        blockers.append(f"promotion_allowed_not_false:{method}")
    if manifest.get("final_pool500_ready_claimed") is not False:
        blockers.append(f"final_pool500_ready_claimed_not_false:{method}")

    forbidden_hits = list(_forbidden_payload_hits(manifest, "manifest"))
    if forbidden_hits:
        blockers.append(f"forbidden_ready_or_artifact_semantics:{method}")
        diagnostics["forbidden_payload_hits"] = forbidden_hits
        migration_punchlist.append("移除 READY/FULL_POOL500_READY/promotion/source artifact/candidate 语义，只保留 method_dataset 诊断证据。")

    output_blockers, output_diagnostics = _audit_output_whitelist(manifest_path.parent, schema_version)
    blockers.extend(output_blockers)
    diagnostics["output_whitelist"] = output_diagnostics

    upstream_blockers, upstream_diagnostics, governance_diagnostics = _audit_upstream(manifest)
    blockers.extend(upstream_blockers)
    diagnostics["upstream"] = upstream_diagnostics

    if schema_version == "pool500_method_dataset_v1":
        _audit_collab_v2_dependency(manifest, blockers, diagnostics)
    if schema_version == "pool500_two_tower_method_dataset_v1":
        _audit_two_tower_phase1_manifest_contract(manifest, blockers, diagnostics)
        _audit_two_tower_negative_universe(manifest_path.parent, manifest, governance_diagnostics, blockers, diagnostics)
        _audit_two_tower_training_item_universe(manifest_path.parent, manifest, blockers, diagnostics)
        _audit_two_tower_train_sample_quality(manifest_path.parent, manifest, blockers, diagnostics)

    audit["status"] = "PASS" if not blockers else "BLOCKED"
    return audit


def _audit_output_whitelist(output_dir: Path, schema_version: Any) -> tuple[list[str], dict[str, Any]]:
    if schema_version == "pool500_two_tower_method_dataset_v1":
        whitelist = TWO_TOWER_OUTPUT_WHITELIST
    else:
        whitelist = COLLAB_OUTPUT_WHITELIST
    names = sorted(path.name for path in output_dir.iterdir()) if output_dir.is_dir() else []
    unexpected = [name for name in names if name not in whitelist]
    blockers = [f"non_whitelisted_method_dataset_output:{name}" for name in unexpected]
    return blockers, {"status": "PASS" if not unexpected else "BLOCKED", "files": names, "whitelist": sorted(whitelist), "unexpected": unexpected}


def _audit_upstream(manifest: dict[str, Any]) -> tuple[list[str], dict[str, Any], dict[str, Any]]:
    blockers: list[str] = []
    diagnostics: dict[str, Any] = {}
    governance_diagnostics: dict[str, Any] = {}
    upstream_path = manifest.get("upstream_governance_manifest_path") or manifest.get("governance_manifest_path")
    if not upstream_path:
        return ["method_dataset_missing_governance_manifest_path"], diagnostics, governance_diagnostics
    resolved = Path(str(upstream_path)).resolve()
    diagnostics["governance_manifest_path"] = str(resolved)
    if not resolved.is_file():
        blockers.append("method_dataset_governance_manifest_path_missing")
    else:
        governance_diagnostics, governance_blockers = _audit_governance(resolved)
        blockers.extend(governance_blockers)
        diagnostics["p1_governance"] = governance_diagnostics
    expected_hash = manifest.get("upstream_governance_manifest_hash")
    if expected_hash and resolved.is_file():
        actual_hash = _file_sha256(resolved)
        diagnostics["upstream_governance_manifest_hash"] = actual_hash
        if expected_hash != actual_hash:
            blockers.append("method_dataset_upstream_governance_hash_mismatch")
    return blockers, diagnostics, governance_diagnostics


def _audit_collab_v2_dependency(manifest: dict[str, Any], blockers: list[str], diagnostics: dict[str, Any]) -> None:
    user_policy = str(manifest.get("effective_user_bucket_policy") or "")
    item_policy = str(manifest.get("effective_item_bucket_policy") or "")
    outputs = manifest.get("outputs") if isinstance(manifest.get("outputs"), dict) else {}
    dataset_schema = outputs.get("dataset_schema")
    rows_path = Path(str(outputs.get("dataset_rows_path"))).resolve() if outputs.get("dataset_rows_path") else None
    diagnostics["v2_bucket_dependency"] = {"user_policy": user_policy, "item_policy": item_policy, "dataset_rows_path": str(rows_path) if rows_path else None, "dataset_schema": dataset_schema}
    if "legacy" in user_policy.lower():
        blockers.append(f"method_dataset_missing_user_bucket_v2_dependency:{manifest.get('source_method')}")
    if rows_path and rows_path.is_file():
        if dataset_schema == "itemcf_edge_features_v1":
            _audit_itemcf_edge_rows(rows_path, manifest, blockers, diagnostics)
        elif dataset_schema == "eligible_user_sequence_v1":
            missing_row_bucket_v2 = _jsonl_missing_field_count(rows_path, "user_bucket_v2")
            diagnostics["v2_bucket_dependency"]["missing_user_bucket_v2_rows"] = missing_row_bucket_v2
            if missing_row_bucket_v2:
                blockers.append(f"method_dataset_missing_user_bucket_v2_dependency:{manifest.get('source_method')}")
    if manifest.get("outputs") == {} and manifest.get("status") != "BLOCKED":
        blockers.append(f"empty_outputs_without_blocked_status:{manifest.get('source_method')}")


def _audit_itemcf_edge_rows(rows_path: Path, manifest: dict[str, Any], blockers: list[str], diagnostics: dict[str, Any]) -> None:
    required_fields = {
        "item_i",
        "item_j",
        "src_item_id",
        "dst_item_id",
        "pair_support",
        "cooc_cnt",
        "supporting_user_count",
        "supporting_user_buckets",
        "weighted_cooc",
        "itemcf_score",
        "score_policy",
        "itemcf_score_formula",
        "active_user_penalty_policy",
        "edge_rank",
    }
    missing_counts = {field: _jsonl_missing_field_count(rows_path, field) for field in sorted(required_fields)}
    diagnostics["itemcf_edge_features"] = {"dataset_rows_path": str(rows_path), "required_fields": sorted(required_fields), "missing_field_counts": missing_counts}
    missing_fields = [field for field, count in missing_counts.items() if count]
    if missing_fields:
        blockers.append(f"itemcf_edge_features_missing_required_fields:{manifest.get('source_method')}:{','.join(missing_fields)}")


def _audit_two_tower_phase1_manifest_contract(manifest: dict[str, Any], blockers: list[str], diagnostics: dict[str, Any]) -> None:
    universe_definitions = manifest.get("universe_definitions") if isinstance(manifest.get("universe_definitions"), dict) else {}
    data_usage_boundary = manifest.get("data_usage_boundary") if isinstance(manifest.get("data_usage_boundary"), dict) else {}
    stats = manifest.get("stats") if isinstance(manifest.get("stats"), dict) else {}
    universe_missing = sorted(TWO_TOWER_REQUIRED_UNIVERSE_KEYS - set(universe_definitions))
    stats_missing = sorted(TWO_TOWER_REQUIRED_STATS - set(stats))
    boundary_missing = sorted(TWO_TOWER_BOUNDARY_RESTRICTED_KEYS - set(data_usage_boundary))
    diagnostics["phase1_manifest_contract"] = {
        "universe_missing": universe_missing,
        "stats_missing": stats_missing,
        "boundary_missing": boundary_missing,
        "eval_target_universe_available": manifest.get("eval_target_universe_available"),
        "retrieval_item_universe_available": manifest.get("retrieval_item_universe_available"),
    }
    if universe_missing:
        blockers.append(f"two_tower_phase1_missing_universe_definitions:{','.join(universe_missing)}")
    if stats_missing:
        blockers.append(f"two_tower_phase1_missing_denominator_stats:{','.join(stats_missing)}")
    if boundary_missing:
        blockers.append(f"two_tower_phase1_missing_data_usage_boundary:{','.join(boundary_missing)}")
    if manifest.get("eval_target_universe_available") is not False:
        blockers.append("two_tower_phase1_eval_target_universe_must_be_unavailable")
    if manifest.get("retrieval_item_universe_available") is not False:
        blockers.append("two_tower_phase1_retrieval_item_universe_must_be_unavailable")
    if stats.get("eval_target_universe_available") is not False or stats.get("eval_target_universe_coverage_status") != "phase1_not_built":
        blockers.append("two_tower_phase1_eval_target_coverage_must_be_phase1_not_built")
    if stats.get("retrieval_item_universe_available") is not False or stats.get("retrieval_item_universe_coverage_status") != "phase1_not_built":
        blockers.append("two_tower_phase1_retrieval_coverage_must_be_phase1_not_built")
    for key in ("candidate_generation_allowed", "ranking_input_replacement_allowed", "promotion_allowed", "final_pool500_ready_claimed"):
        if data_usage_boundary.get(key) is not False:
            blockers.append(f"two_tower_phase1_data_usage_boundary_{key}_not_false")
    for key in TWO_TOWER_BOUNDARY_RESTRICTED_KEYS:
        boundary = data_usage_boundary.get(key) if isinstance(data_usage_boundary.get(key), dict) else {}
        forbidden_uses = set(boundary.get("forbidden_uses") or [])
        allowed_uses = set(boundary.get("allowed_uses") or [])
        if not TWO_TOWER_FORBIDDEN_DATA_USES <= forbidden_uses:
            blockers.append(f"two_tower_phase1_data_usage_boundary_missing_forbidden_uses:{key}")
        if allowed_uses - {"diagnostic_eval_only"}:
            blockers.append(f"two_tower_phase1_data_usage_boundary_allows_forbidden_scope:{key}")


def _audit_two_tower_negative_universe(output_dir: Path, manifest: dict[str, Any], governance_diagnostics: dict[str, Any], blockers: list[str], diagnostics: dict[str, Any]) -> None:
    outputs = manifest.get("outputs") if isinstance(manifest.get("outputs"), dict) else {}
    universe_path = Path(str(outputs.get("negative_item_universe") or output_dir / "negative_item_universe.jsonl")).resolve()
    item_quality_path = _artifact_path(governance_diagnostics, "item_quality_profile")
    item_frequency_path = _artifact_path(governance_diagnostics, "item_frequency_train")
    diagnostics["negative_universe_provenance"] = {
        "negative_item_universe_path": str(universe_path),
        "expected_sources": [str(path) for path in (item_quality_path, item_frequency_path) if path is not None],
        "policy": manifest.get("negative_universe_policy"),
    }
    if not universe_path.is_file():
        blockers.append("two_tower_missing_negative_item_universe")
        return
    if item_quality_path is None or item_frequency_path is None:
        blockers.append("two_tower_missing_p1_negative_universe_sources")
        return

    frequency_items = {str(row.get("parent_asin")) for row in iter_jsonl(item_frequency_path) if row.get("parent_asin")}
    quality_items = {str(row.get("parent_asin")) for row in iter_jsonl(item_quality_path) if row.get("parent_asin") and row.get("quality_bucket_v2") == "embedding_ready"}
    universe_rows = list(iter_jsonl(universe_path))
    bad_rows = [row.get("parent_asin") for row in universe_rows if row.get("quality_bucket_v2") != "embedding_ready" or row.get("source_layer") != "p1_governance_train_only" or str(row.get("parent_asin")) not in quality_items or str(row.get("parent_asin")) not in frequency_items]
    diagnostics["negative_universe_provenance"]["row_count"] = len(universe_rows)
    diagnostics["negative_universe_provenance"]["bad_row_count"] = len(bad_rows)
    if bad_rows:
        blockers.append("two_tower_negative_universe_not_provenanced_from_p1_item_quality_and_frequency")


def _audit_two_tower_training_item_universe(output_dir: Path, manifest: dict[str, Any], blockers: list[str], diagnostics: dict[str, Any]) -> None:
    outputs = manifest.get("outputs") if isinstance(manifest.get("outputs"), dict) else {}
    samples_path = Path(str(outputs.get("two_tower_train_samples") or output_dir / "two_tower_train_samples.jsonl")).resolve()
    universe_path = Path(str(outputs.get("training_item_universe") or output_dir / "training_item_universe.jsonl")).resolve()
    diagnostics["training_item_universe"] = {
        "training_item_universe_path": str(universe_path),
        "samples_path": str(samples_path),
        "policy": manifest.get("training_item_universe_policy"),
    }
    if not universe_path.is_file():
        blockers.append("two_tower_missing_training_item_universe")
        return
    if not samples_path.is_file():
        blockers.append("two_tower_missing_train_samples")
        return

    target_items = {str(row.get("target_item")) for row in iter_jsonl(samples_path) if row.get("target_item")}
    target_universe_items = {
        str(row.get("parent_asin"))
        for row in iter_jsonl(universe_path)
        if row.get("parent_asin") and "positive_target" in (row.get("item_roles") or [])
    }
    missing_targets = sorted(target_items - target_universe_items)
    diagnostics["training_item_universe"].update(
        {
            "sample_target_item_count": len(target_items),
            "positive_target_universe_item_count": len(target_universe_items),
            "missing_target_item_count": len(missing_targets),
        }
    )
    if missing_targets:
        blockers.append("two_tower_sample_targets_missing_from_training_item_universe")


def _audit_two_tower_train_sample_quality(output_dir: Path, manifest: dict[str, Any], blockers: list[str], diagnostics: dict[str, Any]) -> None:
    outputs = manifest.get("outputs") if isinstance(manifest.get("outputs"), dict) else {}
    stats = manifest.get("stats") if isinstance(manifest.get("stats"), dict) else {}
    samples_path = Path(str(outputs.get("two_tower_train_samples") or output_dir / "two_tower_train_samples.jsonl")).resolve()
    universe_path = Path(str(outputs.get("negative_item_universe") or output_dir / "negative_item_universe.jsonl")).resolve()
    training_universe_path = Path(str(outputs.get("training_item_universe") or output_dir / "training_item_universe.jsonl")).resolve()
    sample_diagnostics: dict[str, Any] = {
        "samples_path": str(samples_path),
        "negative_item_universe_path": str(universe_path),
        "training_item_universe_path": str(training_universe_path),
    }
    diagnostics["two_tower_train_sample_quality"] = sample_diagnostics
    if not samples_path.is_file():
        blockers.append("two_tower_missing_train_samples")
        return
    if not universe_path.is_file() or not training_universe_path.is_file():
        return

    negative_universe_items = {str(row.get("parent_asin")) for row in iter_jsonl(universe_path) if row.get("parent_asin")}
    training_universe_by_item = {str(row.get("parent_asin")): row for row in iter_jsonl(training_universe_path) if row.get("parent_asin")}
    samples = list(iter_jsonl(samples_path))
    used_negative_counts: Counter[str] = Counter()
    target_items: set[str] = set()
    leakage_count = 0
    duplicate_negative_count = 0
    empty_negative_count = 0
    negative_count_under_requested_count = 0
    requested_negative_ratio = int(stats.get("negative_ratio_requested") or manifest.get("limits", {}).get("negative_ratio") or 0)

    for sample in samples:
        target_item = str(sample.get("target_item") or "")
        history_items = {str(item) for item in sample.get("history_items") or [] if item}
        negatives = [str(item) for item in sample.get("negative_item_ids") or [] if item]
        if target_item:
            target_items.add(target_item)
        if not negatives:
            empty_negative_count += 1
        if requested_negative_ratio and len(negatives) < requested_negative_ratio:
            negative_count_under_requested_count += 1
        if len(negatives) != len(set(negatives)):
            duplicate_negative_count += 1
        if target_item in negatives or bool(history_items & set(negatives)) or any(item not in negative_universe_items for item in negatives):
            leakage_count += 1
        used_negative_counts.update(negatives)

    used_negative_occurrences = sum(used_negative_counts.values())
    top10_occurrences = sum(count for _, count in used_negative_counts.most_common(10))
    recomputed = {
        "train_sample_count": len(samples),
        "sample_target_item_count": len(target_items),
        "used_negative_distinct_item_count": len(used_negative_counts),
        "used_negative_item_occurrence_count": used_negative_occurrences,
        "used_negative_item_coverage_ratio": round(len(used_negative_counts) / used_negative_occurrences, 6) if used_negative_occurrences else 0.0,
        "negative_item_usage_top1_count": used_negative_counts.most_common(1)[0][1] if used_negative_counts else 0,
        "negative_item_usage_top10_share": round(top10_occurrences / used_negative_occurrences, 6) if used_negative_occurrences else 0.0,
        "negative_item_count_mean": round(used_negative_occurrences / len(samples), 6) if samples else 0.0,
        "negative_item_count_under_requested_count": negative_count_under_requested_count,
    }
    expected_min_distinct = min(50, len(negative_universe_items), len(samples))
    positive_target_metadata_incomplete = [
        item_id
        for item_id in sorted(target_items)
        if _positive_target_metadata_incomplete(training_universe_by_item.get(item_id, {}))
    ]
    sample_diagnostics.update(
        {
            "sample_count": len(samples),
            "target_item_count": len(target_items),
            "negative_universe_item_count": len(negative_universe_items),
            "expected_min_distinct_negative_items": expected_min_distinct,
            "recomputed_stats": recomputed,
            "leakage_count": leakage_count,
            "duplicate_negative_sample_count": duplicate_negative_count,
            "empty_negative_sample_count": empty_negative_count,
            "positive_target_metadata_incomplete_count": len(positive_target_metadata_incomplete),
        }
    )

    if not samples or int(stats.get("train_sample_count") or 0) <= 0:
        blockers.append("two_tower_empty_train_samples")
    if not target_items or int(stats.get("sample_target_item_count") or 0) <= 0:
        blockers.append("two_tower_empty_train_samples")
    if empty_negative_count:
        blockers.append("two_tower_empty_train_sample_negatives")
    if leakage_count or duplicate_negative_count:
        blockers.append("two_tower_train_sample_negative_leakage")
    for key, value in recomputed.items():
        if stats.get(key) != value:
            blockers.append("two_tower_negative_usage_stats_mismatch")
            break
    if len(negative_universe_items) >= expected_min_distinct and len(samples) >= expected_min_distinct and len(used_negative_counts) < expected_min_distinct:
        blockers.append("two_tower_used_negative_diversity_below_threshold")
    if stats.get("training_item_universe_target_items_missing_p1_quality") != 0 or stats.get("training_item_universe_target_items_missing_frequency") != 0:
        blockers.append("two_tower_positive_target_p1_quality_or_frequency_missing")
    if stats.get("training_item_universe_positive_target_metadata_incomplete_count") != 0 or positive_target_metadata_incomplete:
        blockers.append("two_tower_positive_target_metadata_incomplete")


def _positive_target_metadata_incomplete(row: dict[str, Any]) -> bool:
    return not row.get("title_clean") or not row.get("item_text") or not (row.get("main_category") or row.get("category"))


def _artifact_path(governance_diagnostics: dict[str, Any], name: str) -> Path | None:
    artifact = governance_diagnostics.get("artifacts", {}).get(name, {})
    if artifact.get("status") != "PASS" or not artifact.get("path"):
        return None
    return Path(str(artifact["path"])).resolve()


def _resolve_repo_path(manifest_path: Path, raw_path: Any) -> Path:
    path = Path(str(raw_path))
    if path.is_absolute():
        return path.resolve()
    root_candidate = (ROOT / path).resolve()
    if root_candidate.exists():
        return root_candidate
    return (manifest_path.parent / path).resolve()


def _forbidden_payload_hits(value: Any, context: str) -> Iterable[str]:
    if isinstance(value, dict):
        for key, nested in value.items():
            key_text = str(key)
            key_context = f"{context}.{key_text}"
            if key_text in FORBIDDEN_FIELDS and key_text not in ALLOWED_GUARDRAIL_KEYS:
                yield key_context
            yield from _forbidden_payload_hits(nested, key_context)
    elif isinstance(value, list):
        if context.endswith(".forbidden_scopes"):
            return
        for index, nested in enumerate(value):
            yield from _forbidden_payload_hits(nested, f"{context}[{index}]")
    elif isinstance(value, (str, Path)):
        lowered = str(value).replace("\\", "/").lower()
        path_parts = {part.lower() for part in Path(str(value)).parts}
        if lowered in READY_TEXT or "full_pool500_ready" in lowered or "promotion_manifest" in lowered or "source_index_manifest" in lowered:
            yield context
        elif path_parts & FORBIDDEN_SCOPE_TOKENS or "eval_label" in lowered or "clean_10000" in lowered:
            yield context


def _jsonl_missing_field_count(path: Path, field: str) -> int:
    return sum(1 for row in iter_jsonl(path) if field not in row)


def _jsonl_row_count(path: Path) -> int:
    return sum(1 for _ in iter_jsonl(path))


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    args = parse_args()
    report = validate_pool500_method_dataset_audit_evidence(
        governance_manifest_path=Path(args.governance_manifest),
        method_dataset_paths=[Path(value) for value in args.method_dataset],
        output_path=Path(args.output),
        enforce_venv=not args.skip_venv_check,
    )
    print(json.dumps({"status": report["status"], "blocker_count": len(report["blockers"]), "output": str(Path(args.output).resolve())}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
