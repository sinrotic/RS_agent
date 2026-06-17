from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rs_core.common.io import iter_jsonl, read_json, write_json, write_jsonl
from rs_core.common.runtime import enforce_project_venv
from rs_core.recsys.cold_deepfm import bypass_cold_rank, candidate_count_stats, rank_with_cold, rank_with_deepfm, should_apply_cold, train_cold_ranker, train_deepfm_ranker

PASS = "PASS"
STOP = "STOP"
STOP_FOR_RANKING_EFFECT = "STOP_FOR_RANKING_EFFECT"
SCHEMA_VERSION = "cold_deepfm_offline_train_eval_report_v1"
DEFAULT_OUTPUT_DIR = ROOT / "outputs" / "ranking" / "cold_deepfm_offline_train_eval"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train COLD/DeepFM rankers on train-only rows and evaluate frozen candidate rows.")
    parser.add_argument("--train-dataset", required=True, help="JSONL rows from build_cold_deepfm_ranking_training_dataset.py")
    parser.add_argument("--eval-dataset", required=True, help="JSONL rows from build_pool500_frozen_candidate_eval_dataset.py")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--cold-top-n", type=int, default=200)
    parser.add_argument("--deepfm-top-k", type=int, default=20)
    parser.add_argument("--cold-candidate-threshold", type=int, default=200)
    parser.add_argument("--feature-contract", default="")
    parser.add_argument("--expected-screening-policy", default="")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--skip-venv-check", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    report = run_cold_deepfm_offline_train_eval_from_files(
        train_dataset_path=Path(args.train_dataset),
        eval_dataset_path=Path(args.eval_dataset),
        output_dir=Path(args.output_dir),
        cold_top_n=args.cold_top_n,
        deepfm_top_k=args.deepfm_top_k,
        cold_candidate_threshold=args.cold_candidate_threshold,
        feature_contract_path=Path(args.feature_contract) if args.feature_contract else None,
        expected_screening_policy=args.expected_screening_policy or None,
        overwrite=args.overwrite,
        enforce_venv=not args.skip_venv_check,
    )
    print(json.dumps(report["output_paths"], ensure_ascii=False, indent=2))


def run_cold_deepfm_offline_train_eval_from_files(
    *,
    train_dataset_path: Path,
    eval_dataset_path: Path,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    cold_top_n: int = 200,
    deepfm_top_k: int = 20,
    cold_candidate_threshold: int | None = 200,
    feature_contract_path: Path | None = None,
    expected_screening_policy: str | None = None,
    overwrite: bool = False,
    enforce_venv: bool = True,
) -> dict[str, Any]:
    if enforce_venv:
        enforce_project_venv(ROOT)
    train_dataset_path = train_dataset_path.resolve()
    eval_dataset_path = eval_dataset_path.resolve()
    feature_contract_path = feature_contract_path.resolve() if feature_contract_path else None
    output_dir = output_dir.resolve()
    output_paths = _output_paths(output_dir)
    _precheck(train_dataset_path, eval_dataset_path, output_paths, overwrite, feature_contract_path=feature_contract_path)

    raw_train_rows = list(iter_jsonl(train_dataset_path))
    raw_eval_rows = list(iter_jsonl(eval_dataset_path))
    train_rows = [_model_row(row) for row in raw_train_rows]
    eval_rows = [_model_row(row) for row in raw_eval_rows]
    source_gates = _source_gates(train_dataset_path, eval_dataset_path, raw_eval_rows)
    feature_contract = read_json(feature_contract_path) if feature_contract_path else {}
    feature_contract_gate = _feature_contract_gate(raw_train_rows, raw_eval_rows, source_gates, feature_contract, expected_screening_policy=expected_screening_policy)
    source_gates["feature_contract_gate"] = feature_contract_gate
    candidate_coverage_gate = source_gates.get("candidate_coverage_gate", {})
    ranking_effect_refusal = _ranking_effect_refusal(candidate_coverage_gate)
    ranking_effect_allowed = (
        candidate_coverage_gate.get("status") == PASS
        and source_gates.get("eval_dataset_audit", {}).get("ranking_effect_conclusion_allowed", True)
        and not ranking_effect_refusal
    )

    blockers = []
    if not train_rows:
        blockers.append({"code": "EMPTY_TRAIN_DATASET", "severity": "blocker", "path": str(train_dataset_path)})
    if not eval_rows:
        blockers.append({"code": "EMPTY_EVAL_DATASET", "severity": "blocker", "path": str(eval_dataset_path)})
    if source_gates.get("training_gate_report", {}).get("status") == STOP:
        blockers.append({"code": "TRAINING_DATASET_GATE_NOT_PASS", "severity": "blocker", "evidence": source_gates["training_gate_report"]})
    if source_gates.get("eval_dataset_audit", {}).get("status") == STOP:
        blockers.append({"code": "EVAL_DATASET_GATE_NOT_PASS", "severity": "blocker", "evidence": source_gates["eval_dataset_audit"]})
    if feature_contract_gate.get("status") == STOP:
        blockers.append({"code": "FEATURE_CONTRACT_GATE_NOT_PASS", "severity": "blocker", "evidence": feature_contract_gate})

    apply_cold = _should_apply_cold_for_train_eval(train_rows, eval_rows, cold_candidate_threshold) if train_rows and eval_rows and not blockers else False
    cold_model = train_cold_ranker(train_rows) if apply_cold else None
    cold_train_rank = rank_with_cold(train_rows, cold_model, top_n=cold_top_n) if cold_model else bypass_cold_rank(train_rows, top_n=cold_top_n, cold_candidate_threshold=cold_candidate_threshold)
    cold_eval_rank = rank_with_cold(eval_rows, cold_model, top_n=cold_top_n) if cold_model and eval_rows else bypass_cold_rank(eval_rows, top_n=cold_top_n, cold_candidate_threshold=cold_candidate_threshold)
    deepfm_train_rows = cold_train_rank["kept_rows"] if cold_train_rank else []
    deepfm_eval_rows = cold_eval_rank["kept_rows"] if cold_eval_rank else []
    deepfm_model = train_deepfm_ranker(deepfm_train_rows) if deepfm_train_rows and not blockers else None
    deepfm_eval_rank = rank_with_deepfm(deepfm_eval_rows, deepfm_model, top_k=deepfm_top_k) if deepfm_model and deepfm_eval_rows else None

    final_rows = deepfm_eval_rank["final_rows"] if deepfm_eval_rank else []
    rankings = _public_rankings(deepfm_eval_rank["final_by_user"] if deepfm_eval_rank else {})
    baseline_rows = _baseline_top_k(eval_rows, deepfm_top_k)
    evaluation_metrics = _evaluation_metrics(eval_rows, final_rows, deepfm_top_k)
    baseline_metrics = _evaluation_metrics(eval_rows, baseline_rows, deepfm_top_k)
    comparison = _comparison(evaluation_metrics, baseline_metrics, manifest_strategy="cold_then_deepfm" if apply_cold else "direct_deepfm")
    generated_at = datetime.now(UTC).isoformat()
    manifest = {
        "schema_version": "cold_deepfm_offline_train_eval_manifest_v1",
        "status": PASS if not blockers else STOP,
        "generated_at": generated_at,
        "output_dir": str(output_dir),
        "train_dataset_path": str(train_dataset_path),
        "eval_dataset_path": str(eval_dataset_path),
        "separate_train_eval_inputs": train_dataset_path != eval_dataset_path,
        "cold_top_n": cold_top_n,
        "deepfm_top_k": deepfm_top_k,
        "cold_candidate_threshold": cold_candidate_threshold,
        "ranking_strategy": "cold_then_deepfm" if apply_cold else "direct_deepfm",
        "ranking_effect_conclusion_allowed": bool(ranking_effect_allowed and not blockers),
        "candidate_coverage_hard_gate_status": candidate_coverage_gate.get("status"),
        "feature_contract_gate": feature_contract_gate,
        "output_paths": {name: str(path) for name, path in output_paths.items()},
    }
    report = {
        "schema_version": SCHEMA_VERSION,
        "status": manifest["status"],
        "generated_at": generated_at,
        "train_dataset_path": str(train_dataset_path),
        "eval_dataset_path": str(eval_dataset_path),
        "separate_train_eval_inputs": manifest["separate_train_eval_inputs"],
        "label_used_for": {"train_dataset": "training_only", "eval_dataset": "evaluation_only"},
        "candidate_generation_allowed": False,
        "candidate_label_injection_allowed": False,
        "offline_training_only": True,
        "ranking_replacement_allowed": False,
        "ranking_effect_conclusion_allowed": bool(ranking_effect_allowed and not blockers),
        "ranking_effect_conclusion_refused": bool(ranking_effect_refusal),
        "ranking_effect_refusal": ranking_effect_refusal,
        "cold_top_n": cold_top_n,
        "deepfm_top_k": deepfm_top_k,
        "cold_candidate_threshold": cold_candidate_threshold,
        "ranking_strategy": manifest["ranking_strategy"],
        "source_gates": source_gates,
        "feature_contract_gate": feature_contract_gate,
        "train_summary": _row_summary(train_rows),
        "eval_summary": _row_summary(eval_rows),
        "cold": _cold_summary(cold_model, cold_eval_rank),
        "deepfm": _deepfm_summary(deepfm_model, deepfm_eval_rank),
        "evaluation_metrics": evaluation_metrics,
        "baseline_metrics": baseline_metrics,
        "comparison": comparison,
        "final_rankings": rankings,
        "blockers": blockers,
        "manifest": manifest,
    }
    report["output_paths"] = manifest["output_paths"]
    write_json(output_paths["cold_model"], cold_model or {"status": "SKIPPED", "reason": "candidate_count_within_threshold"})
    write_json(output_paths["deepfm_model"], deepfm_model or {"status": STOP})
    write_json(output_paths["metrics"], evaluation_metrics)
    write_json(output_paths["comparison"], comparison)
    write_json(output_paths["manifest"], manifest)
    write_json(output_paths["report"], report)
    write_jsonl(output_paths["final_rankings"], _ranking_rows(rankings))
    output_paths["markdown"].write_text(_markdown(report), encoding="utf-8")
    return report


def _output_paths(output_dir: Path) -> dict[str, Path]:
    return {
        "manifest": output_dir / "manifest.json",
        "report": output_dir / "offline_train_eval_report.json",
        "cold_model": output_dir / "cold_model.json",
        "deepfm_model": output_dir / "deepfm_model.json",
        "metrics": output_dir / "metrics.json",
        "comparison": output_dir / "comparison.json",
        "final_rankings": output_dir / "final_rankings.jsonl",
        "markdown": output_dir / "offline_train_eval_report.md",
    }


def _precheck(train_dataset_path: Path, eval_dataset_path: Path, output_paths: dict[str, Path], overwrite: bool, *, feature_contract_path: Path | None = None) -> None:
    for path, name in ((train_dataset_path, "train_dataset"), (eval_dataset_path, "eval_dataset")):
        if not path.is_file():
            raise FileNotFoundError(f"{name} path does not exist or is not a file: {path}")
    if feature_contract_path is not None and not feature_contract_path.is_file():
        raise FileNotFoundError(f"feature_contract path does not exist or is not a file: {feature_contract_path}")
    if train_dataset_path == eval_dataset_path:
        raise ValueError("train_dataset and eval_dataset must be separate files")
    if not overwrite:
        existing = [str(path) for path in output_paths.values() if path.exists()]
        if existing:
            raise FileExistsError(f"Output files already exist: {existing}")


def _model_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "user_id": str(row.get("user_id") or ""),
        "item_id": str(row.get("item_id") or row.get("parent_asin") or ""),
        "label": 1 if row.get("label") in (1, True, "1", "true", "True") else 0,
        "features": _features(row),
        "sources": list(row.get("candidate_sources") or row.get("sources") or []),
        "category": str(row.get("category") or ""),
        "candidate_rank": _optional_int(row.get("candidate_rank")),
        "full_label_denominator": _optional_int(row.get("full_label_denominator")),
        "in_candidate_denominator": _optional_int(row.get("in_candidate_denominator")),
    }


def _features(row: dict[str, Any]) -> dict[str, float]:
    raw_features = row.get("features") if isinstance(row.get("features"), dict) else {}
    features = {str(name): float(value) for name, value in raw_features.items() if isinstance(value, (int, float))}
    if features:
        return features
    rank = row.get("candidate_rank")
    if isinstance(rank, (int, float)) and rank > 0:
        features["candidate_rank_inverse"] = round(1.0 / float(rank), 10)
    for source in row.get("candidate_sources") or row.get("sources") or []:
        features[f"source_{source}"] = 1.0
    if not features:
        features["bias"] = 1.0
    return features


def _optional_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _source_gates(train_dataset_path: Path, eval_dataset_path: Path, raw_eval_rows: list[dict[str, Any]]) -> dict[str, Any]:
    train_dir = train_dataset_path.parent
    eval_dir = eval_dataset_path.parent
    candidate_coverage_gate = _read_optional_json(eval_dir / "coverage_gate.json")
    if not candidate_coverage_gate:
        candidate_coverage_gate = _candidate_coverage_gate_from_rows(raw_eval_rows)
    return {
        "training_manifest": _read_optional_json(train_dir / "manifest.json"),
        "training_gate_report": _read_optional_json(train_dir / "gate_report.json"),
        "eval_manifest": _read_optional_json(eval_dir / "manifest.json"),
        "eval_dataset_audit": _read_optional_json(eval_dir / "dataset_audit.json"),
        "candidate_coverage_gate": candidate_coverage_gate,
        "oracle_injection_gate": _read_optional_json(eval_dir / "oracle_injection_gate.json"),
    }


def _feature_contract_gate(
    train_rows: list[dict[str, Any]],
    eval_rows: list[dict[str, Any]],
    source_gates: dict[str, Any],
    feature_contract: dict[str, Any],
    *,
    expected_screening_policy: str | None,
) -> dict[str, Any]:
    if not feature_contract:
        return {"schema_version": "cold_deepfm_runner_feature_contract_gate_v1", "status": PASS, "enabled": False}
    expected_features = set(feature_contract.get("feature_names") or [])
    train_feature_sets = [_row_feature_names(row) for row in train_rows]
    eval_feature_sets = [_row_feature_names(row) for row in eval_rows]
    train_features = set().union(*train_feature_sets) if train_feature_sets else set()
    eval_features = set().union(*eval_feature_sets) if eval_feature_sets else set()
    train_bad_rows = [index for index, names in enumerate(train_feature_sets) if names != expected_features]
    eval_bad_rows = [index for index, names in enumerate(eval_feature_sets) if names != expected_features]
    contract_version = feature_contract.get("feature_version")
    train_versions = {row.get("feature_version") for row in train_rows if row.get("feature_version")}
    eval_versions = {row.get("feature_version") for row in eval_rows if row.get("feature_version")}
    eval_contract_gate = source_gates.get("eval_dataset_audit", {}).get("feature_contract_gate", {})
    reasons = []
    contract_hash = feature_contract.get("feature_contract_hash")
    train_contract_hash = source_gates.get("training_gate_report", {}).get("feature_contract_hash")
    eval_contract_hash = source_gates.get("eval_dataset_audit", {}).get("source_manifest", {}).get("feature_contract_hash")
    if expected_features - train_features:
        reasons.append("train_missing_contract_features")
    if expected_features - eval_features:
        reasons.append("eval_missing_contract_features")
    if train_features - expected_features:
        reasons.append("train_extra_contract_features")
    if eval_features - expected_features:
        reasons.append("eval_extra_contract_features")
    if train_features != eval_features:
        reasons.append("train_eval_feature_set_mismatch")
    if train_bad_rows:
        reasons.append("train_row_feature_set_mismatch")
    if eval_bad_rows:
        reasons.append("eval_row_feature_set_mismatch")
    if contract_version and train_versions and train_versions != {contract_version}:
        reasons.append("train_feature_version_mismatch")
    if contract_version and eval_versions and eval_versions != {contract_version}:
        reasons.append("eval_feature_version_mismatch")
    if expected_screening_policy and expected_screening_policy != feature_contract.get("screening_policy"):
        reasons.append("expected_screening_policy_mismatch")
    if contract_hash and not train_contract_hash:
        reasons.append("missing_train_feature_contract_hash")
    elif contract_hash and train_contract_hash != contract_hash:
        reasons.append("train_feature_contract_hash_mismatch")
    if contract_hash and not eval_contract_hash:
        reasons.append("missing_eval_feature_contract_hash")
    elif contract_hash and eval_contract_hash != contract_hash:
        reasons.append("eval_feature_contract_hash_mismatch")
    if eval_contract_gate and eval_contract_gate.get("status") != PASS:
        reasons.append("eval_feature_contract_gate_not_pass")
    return {
        "schema_version": "cold_deepfm_runner_feature_contract_gate_v1",
        "status": PASS if not reasons else STOP,
        "enabled": True,
        "feature_contract_hash": contract_hash,
        "train_feature_contract_hash": train_contract_hash,
        "eval_feature_contract_hash": eval_contract_hash,
        "contract_feature_version": contract_version,
        "train_feature_versions": sorted(str(value) for value in train_versions),
        "eval_feature_versions": sorted(str(value) for value in eval_versions),
        "contract_screening_policy": feature_contract.get("screening_policy"),
        "expected_screening_policy": expected_screening_policy,
        "missing_train_features": sorted(expected_features - train_features),
        "missing_eval_features": sorted(expected_features - eval_features),
        "extra_train_features": sorted(train_features - expected_features),
        "extra_eval_features": sorted(eval_features - expected_features),
        "train_eval_feature_diff": sorted(train_features ^ eval_features),
        "train_row_feature_set_mismatch_rows": train_bad_rows[:20],
        "eval_row_feature_set_mismatch_rows": eval_bad_rows[:20],
        "eval_audit_contract_gate_status": eval_contract_gate.get("status"),
        "reasons": reasons,
    }


def _row_feature_names(row: dict[str, Any]) -> set[str]:
    features = row.get("features") if isinstance(row.get("features"), dict) else {}
    return {str(name) for name in features}


def _candidate_coverage_gate_from_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    full_values = [_optional_int(row.get("full_label_denominator")) for row in rows]
    in_candidate_values = [_optional_int(row.get("in_candidate_denominator")) for row in rows]
    full_values = [value for value in full_values if value is not None]
    in_candidate_values = [value for value in in_candidate_values if value is not None]
    if not full_values or not in_candidate_values:
        return {
            "schema_version": "inferred_pool500_candidate_coverage_hard_gate_v1",
            "status": STOP_FOR_RANKING_EFFECT,
            "candidate_coverage_hard_gate": STOP_FOR_RANKING_EFFECT,
            "inferred_from_eval_row_denominators": True,
            "coverage_gate_sidecar_missing": True,
            "failure_semantics": "coverage_gate.json sidecar is missing; inferred row denominators are diagnostic only and cannot authorize a ranking-effect conclusion",
        }
    full_label_denominator = max(full_values)
    in_candidate_denominator = max(in_candidate_values)
    return {
        "schema_version": "inferred_pool500_candidate_coverage_hard_gate_v1",
        "status": STOP_FOR_RANKING_EFFECT,
        "candidate_coverage_hard_gate": STOP_FOR_RANKING_EFFECT,
        "inferred_from_eval_row_denominators": True,
        "coverage_gate_sidecar_missing": True,
        "full_label_denominator": full_label_denominator,
        "in_candidate_positives": in_candidate_denominator,
        "in_candidate_denominator": in_candidate_denominator,
        "failure_semantics": "coverage_gate.json sidecar is missing; inferred row denominators are diagnostic only and cannot authorize a ranking-effect conclusion",
    }


def _read_optional_json(path: Path) -> dict[str, Any]:
    return read_json(path) if path.is_file() else {}


def _should_apply_cold_for_train_eval(train_rows: list[dict[str, Any]], eval_rows: list[dict[str, Any]], cold_candidate_threshold: int | None) -> bool:
    if cold_candidate_threshold is None:
        return True
    return max(
        candidate_count_stats(train_rows)["candidate_count_max"],
        candidate_count_stats(eval_rows)["candidate_count_max"],
    ) > int(cold_candidate_threshold)


def _row_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    positive_rows = [row for row in rows if row.get("label") == 1]
    return {
        "rows": len(rows),
        "users": len({row["user_id"] for row in rows}),
        "positive_rows": len(positive_rows),
        "positive_users": len({row["user_id"] for row in positive_rows}),
        "positive_rate": round(len(positive_rows) / len(rows), 8) if rows else 0.0,
        "feature_names": sorted({name for row in rows for name in row.get("features", {})}),
    }


def _cold_summary(model: dict[str, Any] | None, rank: dict[str, Any] | None) -> dict[str, Any]:
    if rank is None:
        return {"status": STOP}
    result = {
        "status": rank.get("status", PASS),
        "applied": bool(rank.get("applied", model is not None)),
        "model_type": model.get("model_type") if model else None,
        "training": model.get("training", {}) if model else {},
        "ranking_strategy": rank.get("ranking_strategy"),
        "reason": rank.get("reason"),
        "cold_candidate_threshold": rank.get("cold_candidate_threshold"),
        "candidate_count_stats": rank.get("candidate_count_stats", {}),
        "top_n": rank["top_n"],
        "eval_rows_before": rank["rows_before"],
        "eval_rows_after": rank["rows_after"],
        "eval_positive_survival_at_top_n": rank["positive_survival_at_top_n"],
    }
    return {key: value for key, value in result.items() if value is not None}


def _deepfm_summary(model: dict[str, Any] | None, rank: dict[str, Any] | None) -> dict[str, Any]:
    if model is None or rank is None:
        return {"status": STOP}
    return {
        "status": PASS,
        "model_type": model.get("model_type"),
        "training": model.get("training", {}),
        "top_k": rank["top_k"],
        "eval_rows_before": rank["rows_before"],
        "eval_rows_after": rank["rows_after"],
        "eval_positive_survival_at_top_k": rank["positive_survival_at_top_k"],
    }


def _baseline_top_k(eval_rows: list[dict[str, Any]], top_k: int) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in eval_rows:
        grouped.setdefault(row["user_id"], []).append(row)
    final_rows = []
    for user_rows in grouped.values():
        user_rows.sort(key=lambda row: (row.get("candidate_rank") if row.get("candidate_rank") is not None else 10**9, str(row["item_id"])))
        final_rows.extend(user_rows[:top_k])
    return final_rows


def _evaluation_metrics(eval_rows: list[dict[str, Any]], final_rows: list[dict[str, Any]], top_k: int) -> dict[str, Any]:
    positives_by_user = Counter(row["user_id"] for row in eval_rows if row.get("label") == 1)
    hits_by_user = Counter(row["user_id"] for row in final_rows if row.get("label") == 1)
    positive_users = len(positives_by_user)
    hit_users = sum(1 for user_id in positives_by_user if hits_by_user[user_id] > 0)
    positives = sum(positives_by_user.values())
    hits = sum(hits_by_user.values())
    return {
        "schema_version": "cold_deepfm_offline_eval_metrics_v1",
        "metric_scope": "frozen_candidate_rows_only",
        "top_k": top_k,
        "positive_users": positive_users,
        "hit_users_at_k": hit_users,
        "hit_user_rate_at_k": round(hit_users / positive_users, 6) if positive_users else 0.0,
        "in_candidate_positives": positives,
        "positive_hits_at_k": hits,
        "in_candidate_positive_recall_at_k": round(hits / positives, 6) if positives else 0.0,
    }


def _comparison(evaluation_metrics: dict[str, Any], baseline_metrics: dict[str, Any], *, manifest_strategy: str = "cold_then_deepfm") -> dict[str, Any]:
    return {
        "schema_version": "cold_deepfm_offline_eval_comparison_v1",
        "metric_scope": "frozen_candidate_rows_only",
        "baseline": "candidate_rank_top_k",
        "model": f"{manifest_strategy}_top_k",
        "baseline_metrics": baseline_metrics,
        "model_metrics": evaluation_metrics,
        "delta_in_candidate_positive_recall_at_k": round(
            evaluation_metrics.get("in_candidate_positive_recall_at_k", 0.0) - baseline_metrics.get("in_candidate_positive_recall_at_k", 0.0),
            6,
        ),
        "delta_hit_user_rate_at_k": round(evaluation_metrics.get("hit_user_rate_at_k", 0.0) - baseline_metrics.get("hit_user_rate_at_k", 0.0), 6),
        "effect_claim_allowed_by_metric_scope": False,
    }


def _ranking_effect_refusal(candidate_coverage_gate: dict[str, Any]) -> dict[str, Any]:
    if candidate_coverage_gate.get("status") != STOP_FOR_RANKING_EFFECT:
        return {}
    return {
        "status": STOP_FOR_RANKING_EFFECT,
        "reason": "candidate coverage hard gate did not pass; metrics are mechanical frozen-candidate diagnostics only",
        "full_label_denominator": candidate_coverage_gate.get("full_label_denominator"),
        "in_candidate_positives": candidate_coverage_gate.get("in_candidate_positives"),
        "user_gate_threshold": candidate_coverage_gate.get("user_gate_threshold"),
        "positive_gate_threshold": candidate_coverage_gate.get("positive_gate_threshold"),
        "inferred_from_eval_row_denominators": candidate_coverage_gate.get("inferred_from_eval_row_denominators", False),
    }


def _public_rankings(final_by_user: dict[str, list[dict[str, Any]]]) -> dict[str, list[dict[str, Any]]]:
    return {
        user_id: [
            {
                "item_id": row["item_id"],
                "rank": index,
                "deepfm_score": row.get("deepfm_score"),
                "label": row.get("label"),
                "sources": row.get("sources", []),
                "category": row.get("category", ""),
            }
            for index, row in enumerate(rows, start=1)
        ]
        for user_id, rows in final_by_user.items()
    }


def _ranking_rows(rankings: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    return [row | {"user_id": user_id} for user_id, rows in rankings.items() for row in rows]


def _markdown(report: dict[str, Any]) -> str:
    refusal = report.get("ranking_effect_refusal") or {}
    lines = [
        "# COLD/DeepFM 离线 train/eval 报告",
        "",
        f"- 状态：{report.get('status')}",
        f"- 训练数据：{report.get('train_dataset_path')}",
        f"- 评估数据：{report.get('eval_dataset_path')}",
        f"- ranking_effect_conclusion_allowed：{report.get('ranking_effect_conclusion_allowed')}",
        f"- 排序策略：{report.get('ranking_strategy')}，cold_candidate_threshold={report.get('cold_candidate_threshold')}",
        f"- eval in-candidate recall@{report.get('deepfm_top_k')}：{report.get('evaluation_metrics', {}).get('in_candidate_positive_recall_at_k')}",
        f"- baseline in-candidate recall@{report.get('deepfm_top_k')}：{report.get('baseline_metrics', {}).get('in_candidate_positive_recall_at_k')}",
    ]
    if refusal:
        lines.append(f"- 排序效果结论拦截：{refusal.get('status')}，{refusal.get('reason')}")
    lines.append("")
    lines.append("该报告显式分离 train/eval 输入；当候选覆盖门为 STOP_FOR_RANKING_EFFECT 时，只保留冻结候选诊断指标，不声明排序效果收益。")
    return "\n".join(lines)


if __name__ == "__main__":
    main()
