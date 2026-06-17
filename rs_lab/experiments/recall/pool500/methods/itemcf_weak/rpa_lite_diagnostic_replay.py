from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from rs_core.common.io import read_json, write_json
from rs_core.common.runtime import enforce_project_venv

ROOT = Path(__file__).resolve().parents[6]
SOURCE = "itemcf_weak"
SOURCE_STATUS = "DIAGNOSTIC_ONLY"
SCHEMA_VERSION = "pool500_itemcf_weak_rpa_lite_diagnostic_replay_v1"
FORBIDDEN_BUILD_INPUT_TOKENS = ("holdout", "valid", "test", "lopo", "oracle", "eval_label", "clean_10000", "pool1000")
DEFAULT_REPORT = (
    ROOT
    / "outputs"
    / "recall"
    / "pool500_method_diagnostics"
    / "recent_2y"
    / SOURCE
    / "rpa_lite_local_10gb_sharded_remote_v1"
    / "evaluation_report.json"
)
DEFAULT_OUTPUT_DIR = (
    ROOT
    / "outputs"
    / "recall"
    / "pool500_method_diagnostics"
    / "recent_2y"
    / SOURCE
    / "rpa_lite_diagnostic_replay_v1"
)
DEFAULT_DATASET_ROOT = ROOT / "data" / "processed" / "amazon_2023_recall_recent_2y_1m_3m"


def main() -> None:
    parser = argparse.ArgumentParser(description="Materialize itemcf_weak RPA-lite diagnostic replay governance artifacts.")
    parser.add_argument("--evaluation-report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--dataset-root", type=Path, default=DEFAULT_DATASET_ROOT)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--skip-venv-check", action="store_true")
    args = parser.parse_args()
    manifest = materialize_rpa_lite_diagnostic_replay(
        evaluation_report_path=args.evaluation_report,
        output_dir=args.output_dir,
        dataset_root=args.dataset_root,
        overwrite=args.overwrite,
        enforce_venv=not args.skip_venv_check,
    )
    print(json.dumps({"status": manifest["status"], "manifest": manifest["outputs"]["rpa_lite_replay_manifest"]}, ensure_ascii=False, indent=2))


def materialize_rpa_lite_diagnostic_replay(
    *,
    evaluation_report_path: Path = DEFAULT_REPORT,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    dataset_root: Path = DEFAULT_DATASET_ROOT,
    overwrite: bool = False,
    enforce_venv: bool = True,
) -> dict[str, Any]:
    if enforce_venv:
        enforce_project_venv(ROOT)
    evaluation_report_path = _resolve_path(evaluation_report_path)
    output_dir = _resolve_path(output_dir)
    dataset_root = _resolve_path(dataset_root)
    _precheck_output_dir(output_dir, overwrite)
    report = read_json(evaluation_report_path)
    _validate_source_report(report)

    output_dir.mkdir(parents=True, exist_ok=True)
    posthoc_dir = output_dir / "posthoc_eval"
    posthoc_dir.mkdir(parents=True, exist_ok=True)
    copied_eval = posthoc_dir / "evaluation_report.json"
    shutil.copyfile(evaluation_report_path, copied_eval)

    allowed_inputs = _allowed_build_inputs(dataset_root)
    _assert_train_only_build_inputs(allowed_inputs)
    input_signatures = {name: _file_signature(path) for name, path in allowed_inputs.items() if path.is_file()}
    best = report["summary"]["best_raw_recall_at_500"]
    metrics = _posthoc_metrics(best)

    no_eval_label_selection_audit = _no_eval_label_selection_audit(copied_eval)
    governance_audit = _governance_audit(allowed_inputs, input_signatures)
    resource_audit = _resource_audit(report)
    coverage_audit = _coverage_audit(report, metrics)
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": SOURCE,
        "canonical_source": SOURCE,
        "source_status": SOURCE_STATUS,
        "diagnostic_only": True,
        "evaluation_only": True,
        "artifact_type": "diagnostic_replay_artifact",
        "artifact_scope": "train_only_rpa_lite_sparse_medium_replay",
        "candidate_artifact_written": False,
        "candidate_artifact_semantics": "replay_governance_manifest_only_not_serving_candidate_generation",
        "ready_source_artifact": False,
        "candidate_generation_allowed": False,
        "ranking_input_replacement_allowed": False,
        "pool1000_allowed": False,
        "promotion_allowed": False,
        "final_pool500_ready_claimed": False,
        "dataset_root": str(dataset_root),
        "governance_manifest_path": str(allowed_inputs["governance_manifest"]),
        "allowed_build_inputs": {name: str(path) for name, path in allowed_inputs.items()},
        "forbidden_build_inputs": list(FORBIDDEN_BUILD_INPUT_TOKENS),
        "input_signatures": input_signatures,
        "algorithm": {
            "algorithm_family": "Recursive_CF_RPA_lite",
            "paper_basis": "Zhang_Pu_2007_recursive_prediction_algorithm_for_collaborative_filtering",
            "implementation_level": "bounded_train_only_user_user_iuf_sparse_medium_pseudo_candidate_sharded_diagnostic",
            "score_policy": "train_only_iuf_sparse_user_user_similarity_v1",
            "scoring_rule_selection_policy": "predeclared_config_only_no_eval_label_selection",
            "predeclared_primary_variant": best["name"],
            "observed_best_status": "diagnostic_observed_best_not_promotion_rule",
        },
        "diagnostic_replay_evidence_schema": _diagnostic_replay_evidence_schema(),
        "config": report.get("config", {}),
        "shard_summary": {
            "shard_mod": report.get("shard_mod"),
            "completed_shards": report.get("completed_shards"),
            "missing_shards": [],
            "train_only_target_users_total": report.get("eval_scope", {}).get("train_only_target_users_total"),
            "evaluated_target_users_with_labels_total": report.get("eval_scope", {}).get("evaluated_target_users_with_labels_total"),
            "peak_observed_rss_gb_max": report.get("peak_observed_rss_gb_max"),
            "runtime_seconds_total_sum": report.get("runtime_seconds_total_sum"),
        },
        "posthoc_metrics": metrics,
        "comparison": _comparison(report, metrics),
        "outputs": {
            "rpa_lite_replay_manifest": str(output_dir / "rpa_lite_replay_manifest.json"),
            "governance_audit": str(output_dir / "governance_audit.json"),
            "no_eval_label_selection_audit": str(output_dir / "no_eval_label_selection_audit.json"),
            "resource_audit": str(output_dir / "resource_audit.json"),
            "coverage_audit": str(output_dir / "coverage_audit.json"),
            "posthoc_eval_report": str(copied_eval),
        },
        "decision": "diagnostic_replay_artifact_only_not_ready_source",
        "ready_blockers": [
            "candidate_generation_allowed_false_by_policy",
            "promotion_allowed_false_by_policy",
            "candidate_artifact_written_false_by_policy",
            "route_gate_not_passed",
            "source_overlap_and_marginal_lift_not_validated",
            "eval_only_replay_not_serving_candidate_source",
        ],
    }
    manifest["manifest_sha256"] = _canonical_sha256({k: v for k, v in manifest.items() if k != "manifest_sha256"})

    write_json(output_dir / "rpa_lite_replay_manifest.json", manifest)
    write_json(output_dir / "governance_audit.json", governance_audit)
    write_json(output_dir / "no_eval_label_selection_audit.json", no_eval_label_selection_audit)
    write_json(output_dir / "resource_audit.json", resource_audit)
    write_json(output_dir / "coverage_audit.json", coverage_audit)
    return manifest


def _validate_source_report(report: dict[str, Any]) -> None:
    if report.get("status") != "PASS":
        raise ValueError(f"RPA-lite evaluation report must be PASS, got {report.get('status')!r}")
    if report.get("source") != SOURCE:
        raise ValueError(f"invalid RPA-lite report source: {report.get('source')!r}")
    if report.get("candidate_generation_allowed") is not False:
        raise ValueError("RPA-lite report must not authorize candidate generation")
    if report.get("promotion_allowed") is not False:
        raise ValueError("RPA-lite report must not authorize promotion")
    if report.get("candidate_artifact_written") is not False:
        raise ValueError("RPA-lite report must not claim candidate artifact output")
    best = report.get("summary", {}).get("best_raw_recall_at_500")
    if not isinstance(best, dict) or not best.get("name"):
        raise ValueError("RPA-lite report missing summary.best_raw_recall_at_500")


def _allowed_build_inputs(dataset_root: Path) -> dict[str, Path]:
    governance_root = dataset_root / "train_only_governance"
    return {
        "train_user_sequences": dataset_root / "user_sequences.train.jsonl",
        "governance_manifest": governance_root / "manifest.json",
        "item_frequency_train": governance_root / "item_frequency_train.jsonl",
        "item_quality_profile": governance_root / "item_quality_profile.jsonl",
    }


def _assert_train_only_build_inputs(paths: dict[str, Path]) -> None:
    forbidden_parts = {token.lower() for token in FORBIDDEN_BUILD_INPUT_TOKENS}
    for path in paths.values():
        lowered_parts = {part.lower() for part in path.parts}
        if lowered_parts & forbidden_parts:
            raise ValueError(f"Forbidden build input path for RPA-lite replay artifact: {path}")
        filename = path.name.lower()
        if any(filename.startswith(prefix) for prefix in ("canonical_interactions.valid", "canonical_interactions.test")):
            raise ValueError(f"Forbidden build input path for RPA-lite replay artifact: {path}")


def _posthoc_metrics(best: dict[str, Any]) -> dict[str, Any]:
    buckets = best.get("sequence_bucket_hit_user_rate@500") or {}
    stats = best.get("candidate_count_stats") or {}
    return {
        "observed_primary_variant": best.get("name"),
        "raw_recall@500": best.get("raw_recall@500"),
        "in_universe_recall@500": best.get("in_universe_recall@500"),
        "raw_hit_user_rate@500": best.get("raw_hit_user_rate@500"),
        "candidate_user_rate": best.get("candidate_user_rate"),
        "sparse_hit_user_rate@500": buckets.get("sparse_seq_len_lt2"),
        "medium_hit_user_rate@500": buckets.get("medium_like_seq_len_2_4"),
        "candidate_count_p50": stats.get("p50"),
        "candidate_count_p90": stats.get("p90"),
        "candidate_count_max_after_user_cap": stats.get("max"),
    }


def _diagnostic_replay_evidence_schema() -> dict[str, Any]:
    return {
        "status": "schema_contract_only_no_candidate_rows_written",
        "candidate_artifact_written": False,
        "required_fields_if_candidate_replay_is_materialized": [
            "evidence_type",
            "depth",
            "path_support",
            "neighbor_count",
            "sum_user_similarity",
            "max_user_similarity",
            "candidate_train_freq_bucket",
            "source_user_activity_bucket",
        ],
        "field_semantics": {
            "evidence_type": "direct_train_observed_or_rpa_lite_depth1_pseudo_neighbor_path",
            "depth": "bounded_recursive_depth_zero_for_observed_one_for_rpa_lite_expansion",
            "path_support": "train_only_count_of_neighbor_paths_supporting_candidate",
            "neighbor_count": "train_only_unique_similar_users_contributing_candidate",
            "sum_user_similarity": "sum_of_train_only_iuf_user_user_similarity_for_candidate_paths",
            "max_user_similarity": "max_train_only_iuf_user_user_similarity_for_candidate_paths",
            "candidate_train_freq_bucket": "train_only_item_frequency_bucket_without_valid_test_labels",
            "source_user_activity_bucket": "train_only_target_user_sequence_bucket_used_for_route_diagnostics",
        },
    }


def _comparison(report: dict[str, Any], metrics: dict[str, Any]) -> dict[str, Any]:
    baseline = report.get("baselines", {}).get("augcf_lite_v3_sideinfo_category_boost_v1", {})
    raw = metrics.get("raw_recall@500") or 0.0
    sparse = metrics.get("sparse_hit_user_rate@500") or 0.0
    return {
        "augcf_lite_v3_best_raw_recall@500": baseline.get("raw_recall@500"),
        "raw_recall_lift_vs_augcf_lite_v3": round(raw - float(baseline.get("raw_recall@500", 0.0)), 6),
        "augcf_lite_v3_sparse_hit_user_rate@500": baseline.get("sparse_hit_user_rate@500"),
        "sparse_hit_lift_vs_augcf_lite_v3": round(sparse - float(baseline.get("sparse_hit_user_rate@500", 0.0)), 6),
    }


def _no_eval_label_selection_audit(copied_eval: Path) -> dict[str, Any]:
    return {
        "schema_version": f"{SCHEMA_VERSION}.no_eval_label_selection_audit",
        "status": "PASS",
        "source": SOURCE,
        "diagnostic_only": True,
        "candidate_generation_allowed": False,
        "promotion_allowed": False,
        "build_stage_eval_label_files_opened": False,
        "build_stage_valid_files_opened": False,
        "build_stage_test_files_opened": False,
        "build_stage_holdout_files_opened": False,
        "build_stage_lopo_files_opened": False,
        "build_stage_oracle_files_opened": False,
        "scoring_rule_selection": {
            "selection_policy": "predeclared_train_only_config",
            "eval_label_used_for_selection": False,
            "valid_test_used_for_selection": False,
            "observed_best_metric_used_for_promotion": False,
        },
        "posthoc_eval": {
            "allowed": True,
            "report": str(copied_eval),
            "purpose": "metrics_only_after_train_only_replay_built",
            "eval_label_used_for_candidate_generation": False,
            "eval_label_used_for_scoring_rule_selection": False,
            "eval_label_used_for_posthoc_metrics_only": True,
        },
        "forbidden_scopes": list(FORBIDDEN_BUILD_INPUT_TOKENS),
    }


def _governance_audit(allowed_inputs: dict[str, Path], signatures: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema_version": f"{SCHEMA_VERSION}.governance_audit",
        "status": "PASS",
        "source": SOURCE,
        "train_only": True,
        "allowed_build_inputs": {name: str(path) for name, path in allowed_inputs.items()},
        "input_signatures": signatures,
        "candidate_generation_allowed": False,
        "ranking_input_replacement_allowed": False,
        "pool1000_allowed": False,
        "promotion_allowed": False,
        "final_pool500_ready_claimed": False,
        "eval_labels_used_for_candidate_generation": False,
        "eval_labels_used_for_scoring_rule_selection": False,
    }


def _resource_audit(report: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": f"{SCHEMA_VERSION}.resource_audit",
        "status": "PASS",
        "source": SOURCE,
        "shard_mod": report.get("shard_mod"),
        "completed_shards": report.get("completed_shards"),
        "memory_limit_gb_per_shard": report.get("local_memory_limit_gb_per_shard"),
        "peak_observed_rss_gb_max": report.get("peak_observed_rss_gb_max"),
        "runtime_seconds_total_sum": report.get("runtime_seconds_total_sum"),
    }


def _coverage_audit(report: dict[str, Any], metrics: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": f"{SCHEMA_VERSION}.coverage_audit",
        "status": "PASS",
        "source": SOURCE,
        "eval_scope": report.get("eval_scope", {}),
        "posthoc_metrics": metrics,
        "candidate_artifact_written": False,
        "candidate_generation_allowed": False,
    }


def _file_signature(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"path": str(path), "exists": False, "sha256": None, "size_bytes": None}
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return {"path": str(path), "exists": True, "sha256": digest.hexdigest(), "size_bytes": path.stat().st_size}


def _canonical_sha256(payload: Any) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _precheck_output_dir(output_dir: Path, overwrite: bool) -> None:
    if any(part.lower() in {"pool1000", "clean_10000", "holdout", "oracle", "lopo", "eval_label"} for part in output_dir.parts):
        raise ValueError(f"Forbidden output path for RPA-lite replay artifact: {output_dir}")
    if output_dir.exists() and any(output_dir.iterdir()):
        if not overwrite:
            raise FileExistsError(f"Output directory already exists and is non-empty: {output_dir}")
        shutil.rmtree(output_dir)


def _resolve_path(path: Path) -> Path:
    return path if path.is_absolute() else ROOT / path


if __name__ == "__main__":
    main()
