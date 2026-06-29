from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from math import log2
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rs_core.common.io import iter_jsonl, write_json
from rs_core.common.runtime import enforce_project_venv
from rs_core.online.ranking.ltr import (
    build_ltr_feature_contract_gate_summary,
    build_ltr_leakage_gate_summary,
    extract_ltr_features,
    train_lightgbm_lambdamart,
    train_pairwise_perceptron,
    train_pointwise_logistic,
    validate_ltr_feature_contract_gate,
    validate_ltr_leakage_gate,
)
from rs_core.online.ranking import rank_candidates
from rs_core.common.recsys_types import MergedCandidate
from rs_core.workflow.pool500_ranking_adapter import adapt_pool500_rows_to_candidates
from rs_core.workflow.pool500_shadow_ranking import build_pool500_fixed_ranking_comparison_configs

SCHEMA_VERSION = "pool500_learned_ranking_challenger_report_v1"
PASS = "PASS"
STOP = "STOP"
DEFAULT_TOP_KS = (10, 20)
DEFAULT_OUTPUT_DIR = ROOT / "outputs" / "ranking" / "pool500_learned_challenger_smoke"
DEFAULT_MODEL_CONFIG = {"epochs": 5, "learning_rate": 0.05, "negative_sample_per_positive": 20, "margin": 1.0, "fallback_model_kind": "pairwise"}
DEFAULT_GATE_CONFIG = {
    "min_eval_positive_users": 30,
    "min_eval_segments": 2,
    "min_positive_coverage": 0.01,
    "min_candidate_hit_rate_at_20": 0.01,
    "max_fallback_exposure_topk_ratio": 0.5,
    "max_metadata_missing_rate": 0.01,
    "max_category_missing_rate": 0.05,
    "max_top_category_ratio": 0.95,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate frozen learned-ranking gate eligibility against a fixed pool500 comparison report.")
    parser.add_argument("--fixed-comparison-report", required=True)
    parser.add_argument("--expected-fixed-comparison-report-sha256", required=True)
    parser.add_argument("--rule-diagnostics-plateau-evidence", action="store_true")
    parser.add_argument("--pool500-candidates")
    parser.add_argument("--train-label-artifact")
    parser.add_argument("--eval-label-artifact")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--skip-venv-check", action="store_true")
    return parser.parse_args()


def run_pool500_learned_ranking_challenger(
    *,
    fixed_comparison_report_path: Path | None = None,
    expected_fixed_comparison_report_sha256: str | None = None,
    rule_diagnostics_plateau_evidence: bool | None = None,
    pool500_candidates_path: Path | None = None,
    train_label_artifact_path: Path | None = None,
    eval_label_artifact_path: Path | None = None,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    enforce_venv: bool = True,
) -> dict[str, Any]:
    if enforce_venv:
        enforce_project_venv(ROOT)
    output_dir = output_dir.resolve()

    blockers: list[dict[str, Any]] = []
    fixed_report_gate = _fixed_comparison_report_gate(fixed_comparison_report_path, expected_fixed_comparison_report_sha256)
    fixed_report = fixed_report_gate.get("report") if fixed_report_gate.get("status") == PASS else {}
    blockers.extend(fixed_report_gate.get("blockers", []))

    label_metric_gate = _label_metric_eligibility_gate(fixed_report)
    plateau_gate = _rule_plateau_gate(rule_diagnostics_plateau_evidence)
    feature_contract_gate, leakage_gate, train_label_split_gate, training_sample_summary, input_blockers = _frozen_ltr_input_gates(pool500_candidates_path, train_label_artifact_path)
    blockers.extend(input_blockers)
    for gate, code in (
        (label_metric_gate, "POOL500_LEARNED_CHALLENGER_LABEL_METRIC_INELIGIBLE"),
        (plateau_gate, "POOL500_LEARNED_CHALLENGER_RULE_PLATEAU_EVIDENCE_MISSING"),
        (feature_contract_gate, "POOL500_LEARNED_CHALLENGER_FEATURE_CONTRACT_NOT_PASS"),
        (leakage_gate, "POOL500_LEARNED_CHALLENGER_LEAKAGE_GATE_NOT_PASS"),
    ):
        if gate.get("status") != PASS:
            blockers.append(_blocker(code, gate))

    would_be_eligible = not blockers
    learned_ranking_gate = {
        "label_comparable_required": True,
        "feature_contract_gate_required": True,
        "leakage_gate_required": True,
        "rule_diagnostics_plateau_required": True,
        "current_phase_training_enabled": False,
        "would_be_eligible": would_be_eligible,
        "recommendation": "future_stage_training_review_only" if would_be_eligible else "keep_frozen_until_all_gates_pass",
        "fixed_comparison_report_gate": {key: value for key, value in fixed_report_gate.items() if key != "report"},
        "label_metric_eligibility_gate": label_metric_gate,
        "rule_diagnostics_plateau_gate": plateau_gate,
        "feature_contract_gate": feature_contract_gate,
        "leakage_gate": leakage_gate,
    }
    promotion_gate = {
        "decision": "FROZEN_WOULD_BE_ELIGIBLE" if would_be_eligible else "FROZEN_INELIGIBLE",
        "promotion_readiness": "not_allowed_in_current_phase",
        "blockers": blockers,
    }
    report = {
        "schema_version": SCHEMA_VERSION,
        "status": PASS if fixed_report_gate.get("status") == PASS else STOP,
        "decision": promotion_gate["decision"],
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "report_semantics": "frozen learned-ranking gate eligibility contract",
        "diagnostic_only": True,
        "candidate_generation_allowed": False,
        "ranking_input_replacement_allowed": False,
        "ranking_replacement_allowed": False,
        "promotion_allowed": False,
        "promotion_readiness": promotion_gate["promotion_readiness"],
        "current_phase_training_enabled": False,
        "would_be_eligible": would_be_eligible,
        "model": None,
        "pool500_candidates_path": str(pool500_candidates_path) if pool500_candidates_path else None,
        "train_label_artifact_path": str(train_label_artifact_path) if train_label_artifact_path else None,
        "eval_label_artifact_path": str(eval_label_artifact_path) if eval_label_artifact_path else None,
        "fixed_comparison_report_path": str(fixed_comparison_report_path) if fixed_comparison_report_path else None,
        "expected_fixed_comparison_report_sha256": expected_fixed_comparison_report_sha256,
        "actual_fixed_comparison_report_sha256": fixed_report_gate.get("actual_sha256"),
        "fixed_comparison_report_summary": fixed_report_gate.get("report_summary", {}),
        "training_sample_summary": training_sample_summary,
        "train_label_split_gate": train_label_split_gate,
        "feature_contract_gate": feature_contract_gate,
        "leakage_gate": leakage_gate,
        "learned_ranking_gate": learned_ranking_gate,
        "promotion_gate": promotion_gate,
        "blockers": blockers,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "comparison.json"
    md_path = output_dir / "comparison.md"
    report["output_paths"] = {"comparison_json": str(json_path), "comparison_md": str(md_path)}
    write_json(json_path, report)
    md_path.write_text(_comparison_markdown(report), encoding="utf-8")
    return report


def _fixed_comparison_report_gate(report_path: Path | None, expected_sha256: str | None) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    if report_path is None:
        blockers.append(_blocker("POOL500_LEARNED_CHALLENGER_FIXED_REPORT_PATH_REQUIRED", {}))
    if not expected_sha256:
        blockers.append(_blocker("POOL500_LEARNED_CHALLENGER_FIXED_REPORT_HASH_REQUIRED", {}))
    if blockers:
        return {"status": STOP, "blockers": blockers}
    assert report_path is not None
    actual_sha256 = _sha256_file(report_path)
    if actual_sha256 != expected_sha256:
        return {
            "status": STOP,
            "actual_sha256": actual_sha256,
            "expected_sha256": expected_sha256,
            "blockers": [_blocker("POOL500_LEARNED_CHALLENGER_FIXED_REPORT_HASH_MISMATCH", {"path": str(report_path), "expected_sha256": expected_sha256, "actual_sha256": actual_sha256})],
        }
    report = json.loads(report_path.read_text(encoding="utf-8"))
    return {
        "status": PASS,
        "path": str(report_path),
        "actual_sha256": actual_sha256,
        "expected_sha256": expected_sha256,
        "report": report,
        "report_summary": {
            "schema_version": report.get("schema_version"),
            "label_metric_eligibility": report.get("label_metric_eligibility"),
            "label_metric_definition_version": report.get("label_metric_definition_version"),
            "promotion_readiness": report.get("promotion_readiness"),
        },
        "blockers": [],
    }


def _label_metric_eligibility_gate(fixed_report: Any) -> dict[str, Any]:
    eligible = isinstance(fixed_report, dict) and fixed_report.get("label_metric_eligibility") is True
    return {
        "status": PASS if eligible else STOP,
        "label_metric_eligibility": fixed_report.get("label_metric_eligibility") if isinstance(fixed_report, dict) else None,
        "label_ineligible_reason": fixed_report.get("label_ineligible_reason") if isinstance(fixed_report, dict) else "fixed_comparison_report_unavailable",
    }


def _rule_plateau_gate(evidence: bool | None) -> dict[str, Any]:
    return {"status": PASS if evidence is True else STOP, "rule_diagnostics_plateau_evidence": evidence is True}


def _frozen_ltr_input_gates(pool500_candidates_path: Path | None, train_label_artifact_path: Path | None) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    blockers: list[dict[str, Any]] = []
    missing_inputs = []
    if pool500_candidates_path is None:
        missing_inputs.append("pool500_candidates_path")
    if train_label_artifact_path is None:
        missing_inputs.append("train_label_artifact_path")
    if missing_inputs:
        gate = {"status": STOP, "reasons": ["missing_ltr_gate_inputs"], "missing_inputs": missing_inputs}
        return gate, gate, {"status": STOP, "reasons": ["missing_train_label_artifact_path"]}, _training_sample_summary([]), blockers

    candidate_rows = list(iter_jsonl(pool500_candidates_path))
    adapter_result = adapt_pool500_rows_to_candidates(candidate_rows)
    candidates_by_user = adapter_result.get("candidates_by_user", {}) if adapter_result.get("status") == PASS else {}
    blockers.extend(adapter_result.get("blockers", []))
    train_labels = _load_label_artifact(train_label_artifact_path)
    if train_labels.get("status") != PASS:
        blockers.append(_blocker("POOL500_LEARNED_CHALLENGER_TRAIN_LABEL_ARTIFACT_INVALID", {"path": train_labels.get("path"), "blockers": train_labels.get("blockers", [])}))
    train_label_split_gate = _train_label_split_gate(train_labels)
    train_rows = _build_training_rows(candidates_by_user, train_labels["positive_pairs"])
    feature_contract_gate = build_ltr_feature_contract_gate_summary(train_rows)
    leakage_gate = build_ltr_leakage_gate_summary(train_rows, label_source="train_label_artifact", training_split=train_label_split_gate["training_split_for_leakage_gate"])
    try:
        validate_ltr_feature_contract_gate(train_rows)
    except ValueError:
        pass
    try:
        validate_ltr_leakage_gate(train_rows, label_source="train_label_artifact", training_split=train_label_split_gate["training_split_for_leakage_gate"])
    except ValueError:
        pass
    return feature_contract_gate, leakage_gate, train_label_split_gate, _training_sample_summary(train_rows), blockers


def _load_label_artifact(path: Path) -> dict[str, Any]:
    label_pairs: set[tuple[str, str]] = set()
    positive_pairs: set[tuple[str, str]] = set()
    positive_by_user: dict[str, set[str]] = {}
    label_split_counts: Counter[str] = Counter()
    positive_split_counts: Counter[str] = Counter()
    blockers: list[dict[str, Any]] = []
    row_count = 0
    labeled_row_count = 0
    positive_count = 0
    schema_versions: set[str] = set()
    join_keys: set[str] = set()
    for row in iter_jsonl(path):
        row_count += 1
        if row.get("schema_version") is not None:
            schema_versions.add(str(row.get("schema_version")))
        user_id = str(row.get("user_id") or "")
        item_id = str(row.get("parent_asin") or row.get("item_id") or "")
        if row.get("parent_asin") is not None:
            join_keys.add("user_id,parent_asin")
        elif row.get("item_id") is not None:
            join_keys.add("user_id,item_id")
        if not user_id or not item_id:
            blockers.append(_blocker("POOL500_LEARNED_CHALLENGER_LABEL_JOIN_KEY_INVALID", {"path": str(path), "row_number": row_count, "user_id": user_id, "item_id": item_id}))
            continue
        split = str(row.get("split") or row.get("label_split") or "unknown")
        labeled_row_count += 1
        label_split_counts[split] += 1
        label_pairs.add((user_id, item_id))
        try:
            positive = _label_positive(row)
        except ValueError as exc:
            blockers.append(_blocker("POOL500_LEARNED_CHALLENGER_LABEL_VALUE_INVALID", {"path": str(path), "row_number": row_count, "error": str(exc)}))
            continue
        if not positive:
            continue
        positive_count += 1
        positive_split_counts[split] += 1
        positive_pairs.add((user_id, item_id))
        positive_by_user.setdefault(user_id, set()).add(item_id)
    unsupported_schema_versions = sorted(version for version in schema_versions if version != "pool500_label_artifact_v1")
    if unsupported_schema_versions:
        blockers.append(_blocker("POOL500_LEARNED_CHALLENGER_LABEL_SCHEMA_INVALID", {"path": str(path), "schema_versions": unsupported_schema_versions}))
    if row_count == 0:
        blockers.append(_blocker("POOL500_LEARNED_CHALLENGER_LABEL_SCHEMA_INVALID", {"path": str(path), "reason": "empty_label_artifact"}))
    if len(join_keys) > 1:
        blockers.append(_blocker("POOL500_LEARNED_CHALLENGER_LABEL_JOIN_KEY_INVALID", {"path": str(path), "join_keys": sorted(join_keys)}))
    return {
        "path": str(path),
        "status": PASS if not blockers else STOP,
        "blockers": blockers,
        "row_count": row_count,
        "labeled_row_count": labeled_row_count,
        "label_pairs": label_pairs,
        "label_split_counts": dict(sorted(label_split_counts.items())),
        "positive_count": positive_count,
        "positive_pairs": positive_pairs,
        "positive_by_user": positive_by_user,
        "positive_user_count": len(positive_by_user),
        "positive_split_counts": dict(sorted(positive_split_counts.items())),
        "positive_segment_count": len(positive_split_counts),
    }


def _label_positive(row: dict[str, Any]) -> bool:
    for field in ("label_binary", "label", "holdout_hit", "is_hit", "clicked", "purchased"):
        if field in row:
            return _strict_positive_value(row.get(field))
    if "rating" in row:
        return float(row.get("rating") or 0.0) > 0.0
    return False


def _strict_positive_value(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return float(value) > 0.0
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "y", "positive"}:
            return True
        if normalized in {"0", "false", "no", "n", "negative", ""}:
            return False
        raise ValueError(f"Unsupported label value: {value!r}")
    return bool(value)


def _train_label_split_gate(train_labels: dict[str, Any]) -> dict[str, Any]:
    forbidden_splits = sorted(split for split in train_labels["label_split_counts"] if split in {"valid", "test", "holdout"})
    return {
        "status": STOP if forbidden_splits else PASS,
        "training_split_for_leakage_gate": forbidden_splits[0] if forbidden_splits else "train",
        "label_split_counts": train_labels["label_split_counts"],
        "positive_split_counts": train_labels["positive_split_counts"],
        "forbidden_training_splits": forbidden_splits,
        "reasons": ["forbidden_training_split"] if forbidden_splits else [],
    }



def _label_separation_gate(train_path: Path, eval_path: Path, train_labels: dict[str, Any], eval_labels: dict[str, Any]) -> dict[str, Any]:
    train_positive_pairs = set(train_labels["positive_pairs"])
    eval_positive_pairs = set(eval_labels["positive_pairs"])
    train_label_pairs = set(train_labels["label_pairs"])
    eval_label_pairs = set(eval_labels["label_pairs"])
    overlapping_positive_pairs = train_positive_pairs & eval_positive_pairs
    overlapping_label_pairs = train_label_pairs & eval_label_pairs
    same_path = train_path.resolve() == eval_path.resolve()
    reasons: list[str] = []
    if same_path:
        reasons.append("same_train_eval_label_artifact_path")
    if overlapping_positive_pairs:
        reasons.append("overlapping_positive_pairs")
    if overlapping_label_pairs:
        reasons.append("overlapping_label_pairs")
    return {
        "status": STOP if reasons else PASS,
        "train_label_artifact_path": str(train_path),
        "eval_label_artifact_path": str(eval_path),
        "same_path": same_path,
        "train_labeled_pair_count": len(train_label_pairs),
        "eval_labeled_pair_count": len(eval_label_pairs),
        "train_positive_pair_count": len(train_positive_pairs),
        "eval_positive_pair_count": len(eval_positive_pairs),
        "train_positive_user_count": train_labels["positive_user_count"],
        "eval_positive_user_count": eval_labels["positive_user_count"],
        "train_label_split_counts": train_labels["label_split_counts"],
        "eval_label_split_counts": eval_labels["label_split_counts"],
        "train_positive_split_counts": train_labels["positive_split_counts"],
        "eval_positive_split_counts": eval_labels["positive_split_counts"],
        "overlapping_labeled_pair_count": len(overlapping_label_pairs),
        "overlapping_labeled_user_count": len({user_id for user_id, _ in overlapping_label_pairs}),
        "overlapping_positive_pair_count": len(overlapping_positive_pairs),
        "overlapping_positive_user_count": len({user_id for user_id, _ in overlapping_positive_pairs}),
        "reasons": reasons,
    }


def _build_training_rows(candidates_by_user: dict[str, list[MergedCandidate]], positive_pairs: set[tuple[str, str]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for user_id, candidates in sorted(candidates_by_user.items()):
        for candidate in candidates:
            rows.append(
                {
                    "user_id": user_id,
                    "parent_asin": candidate.item_id,
                    "label": 1 if (user_id, candidate.item_id) in positive_pairs else 0,
                    "features": extract_ltr_features(candidate, {"include_ranking_v2": True}),
                }
            )
    return rows


def _training_rows_usable(rows: list[dict[str, Any]]) -> bool:
    labels = {row.get("label") for row in rows}
    positive_users = {row["user_id"] for row in rows if row.get("label") == 1}
    return labels == {0, 1} and bool(positive_users)


def _train_ltr_model(rows: list[dict[str, Any]], model_kind: str, config: dict[str, Any]) -> dict[str, Any]:
    if model_kind in {"auto", "lightgbm_lambdamart"}:
        lightgbm_model = train_lightgbm_lambdamart(rows, config.get("lightgbm", config))
        if lightgbm_model.get("training", {}).get("status") == "trained":
            lightgbm_model["selection"] = {"requested_model_kind": model_kind, "selected_model_kind": "lightgbm_lambdamart", "fallback_used": False}
            return lightgbm_model
        if model_kind == "lightgbm_lambdamart" and not config.get("fallback_when_lightgbm_unavailable", True):
            lightgbm_model["selection"] = {"requested_model_kind": model_kind, "selected_model_kind": None, "fallback_used": False}
            return lightgbm_model
        fallback_kind = str(config.get("fallback_model_kind", "pairwise"))
        fallback_model = _train_ltr_model(rows, fallback_kind, config)
        fallback_model["selection"] = {
            "requested_model_kind": model_kind,
            "selected_model_kind": fallback_kind,
            "fallback_used": True,
            "fallback_reason": lightgbm_model.get("training", {}),
        }
        return fallback_model
    if model_kind == "pointwise":
        model = train_pointwise_logistic(rows, config)
        model["selection"] = {"requested_model_kind": model_kind, "selected_model_kind": "pointwise", "fallback_used": False}
        return model
    model = train_pairwise_perceptron(rows, config)
    model["selection"] = {"requested_model_kind": model_kind, "selected_model_kind": "pairwise", "fallback_used": False}
    return model


def _trained_ltr_model(model: dict[str, Any] | None) -> bool:
    if not isinstance(model, dict) or not model.get("model_type"):
        return False
    if model.get("model_type") == "lightgbm_lambdamart_ltr_v1":
        return model.get("training", {}).get("status") == "trained" and bool(model.get("booster_model"))
    if model.get("model_type") in {"pairwise_perceptron_ltr_v1", "pointwise_logistic_ltr_v1"}:
        return isinstance(model.get("training"), dict)
    return False


def _ltr_challenger_eligibility(model: dict[str, Any] | None) -> dict[str, Any]:
    training = model.get("training", {}) if isinstance(model, dict) else {}
    positive_rows = int(training.get("positive_rows", 0) or 0) if isinstance(training, dict) else 0
    positive_users = int(training.get("positive_users", 0) or 0) if isinstance(training, dict) else 0
    min_positive_rows = 5
    min_positive_users = 2
    enabled = _trained_ltr_model(model) and positive_rows >= min_positive_rows and positive_users >= min_positive_users
    return {
        "enabled": enabled,
        "positive_rows": positive_rows,
        "positive_users": positive_users,
        "min_positive_rows": min_positive_rows,
        "min_positive_users": min_positive_users,
        "reason": "trained_ltr_model" if enabled else "underpowered_ltr_training_labels",
    }


def _coarse_only_config(base_config: dict[str, Any]) -> dict[str, Any]:
    config = dict(base_config)
    config["coarse_top_n"] = 200
    config["coarse_ranking"] = _pool500_coarse_ranking_policy()
    config["normalized_additive_ranking"] = {"enabled": False}
    config["ltr_model"] = {"enabled": False}
    config["policy_rerank_guard"] = {"enabled": False}
    config["challenger_role"] = "coarse_only_frozen_pool_diagnostic"
    return config


def _challenger_config(model: dict[str, Any] | None) -> dict[str, Any]:
    config = build_pool500_fixed_ranking_comparison_configs()["B0"]
    config["coarse_top_n"] = 200
    config["coarse_ranking"] = _pool500_coarse_ranking_policy()
    config["normalized_additive_ranking"] = {
        "enabled": True,
        "weights": {
            "source_signal": 0.2,
            "item_feature": 0.2,
            "freshness_quality": 0.1,
            "near_miss_tiebreak_strength": 0.05,
        },
    }
    config["source_aware_fusion"] = {
        "enabled": True,
        "itemcf_source_boost": 0.05,
        "itemcf_multi_source_boost": 0.05,
        "two_tower_source_boost": 0.04,
        "two_tower_multi_source_boost": 0.06,
        "two_tower_itemcf_source_boost": 0.08,
        "two_tower_semantic_source_boost": 0.08,
        "two_tower_only_penalty": 0.03,
        "semantic_only_penalty": 0.02,
        "popular_only_penalty": 0.04,
    }
    ltr_eligibility = _ltr_challenger_eligibility(model)
    config["ltr_model"] = {
        "enabled": ltr_eligibility["enabled"],
        "model": model or {},
        "features": {"include_ranking_v2": True},
        "score_scale": 1.0,
        "eligibility": ltr_eligibility,
    }
    config["policy_rerank_guard"] = {
        "enabled": True,
        "max_fallback_topk_ratio": 0.5,
        "max_repaired_topk_ratio": 0.5,
        "max_metadata_missing_topk_ratio": 0.5,
        "max_category_missing_topk_ratio": 0.5,
        "max_per_source_topk_ratio": 0.5,
        "max_per_category_topk_ratio": 0.95,
        "max_abs_rank_movement": 100,
    }
    config["challenger_role"] = "coarse_fine_policy_rerank_frozen_pool_challenger"
    return config


def _pool500_coarse_ranking_policy() -> dict[str, Any]:
    return {
        "source_score_calibration": {
            "popular": {"scale": 0.85},
            "category": {"scale": 1.0},
            "semantic": {"scale": 1.05},
            "semantic_title_category_expansion": {"scale": 1.0},
            "itemcf_weak": {"scale": 1.0},
            "itemcf_strong": {"scale": 1.1},
            "two_tower": {"scale": 1.08},
            "usercf_recall": {"scale": 1.0},
            "swing_recall": {"scale": 1.0},
            "co_visit_fallback_repair": {"scale": 0.7},
        },
        "source_prior": {
            "itemcf_strong": 0.03,
            "semantic": 0.02,
            "two_tower": 0.02,
            "co_visit_fallback_repair": -0.05,
        },
        "reciprocal_rank_fusion": {"enabled": True, "k": 60.0, "weight": 1.0},
        "multi_source_boost": 0.03,
    }


def _rank_all(candidates_by_user: dict[str, list[MergedCandidate]], config: dict[str, Any], top_k: int) -> dict[str, list[dict[str, Any]]]:
    return {user_id: rank_candidates(user_id, candidates, config, top_k=top_k).items for user_id, candidates in sorted(candidates_by_user.items())}


def _metrics_at_ks(ranking: dict[str, list[dict[str, Any]]], positive_by_user: dict[str, set[str]], top_ks: tuple[int, ...]) -> dict[str, Any]:
    metrics: dict[str, Any] = {"positive_user_count": len(positive_by_user)}
    for k in top_ks:
        hits = 0
        recall_sum = 0.0
        ndcg_sum = 0.0
        mrr_sum = 0.0
        map_sum = 0.0
        for user_id, positives in positive_by_user.items():
            ranked = [str(item.get("parent_asin")) for item in ranking.get(user_id, [])[:k]]
            hit_positions = [index + 1 for index, item_id in enumerate(ranked) if item_id in positives]
            if hit_positions:
                hits += 1
                mrr_sum += 1.0 / hit_positions[0]
            recall_sum += len(hit_positions) / len(positives) if positives else 0.0
            dcg = sum(1.0 / log2(position + 1) for position in hit_positions)
            ideal_dcg = sum(1.0 / log2(index + 2) for index in range(min(len(positives), k)))
            ndcg_sum += dcg / ideal_dcg if ideal_dcg else 0.0
            precision_sum = 0.0
            seen_hits = 0
            for position, item_id in enumerate(ranked, start=1):
                if item_id in positives:
                    seen_hits += 1
                    precision_sum += seen_hits / position
            map_sum += precision_sum / min(len(positives), k) if positives else 0.0
        denominator = len(positive_by_user) or 1
        metrics[f"hit_at_{k}"] = round(hits / denominator, 6)
        metrics[f"recall_at_{k}"] = round(recall_sum / denominator, 6)
        metrics[f"ndcg_at_{k}"] = round(ndcg_sum / denominator, 6)
        metrics[f"mrr_at_{k}"] = round(mrr_sum / denominator, 6)
        metrics[f"map_at_{k}"] = round(map_sum / denominator, 6)
    return metrics


def _empty_metrics(top_ks: tuple[int, ...]) -> dict[str, Any]:
    metrics: dict[str, Any] = {"positive_user_count": 0}
    for k in top_ks:
        for name in ("hit", "recall", "ndcg", "mrr", "map"):
            metrics[f"{name}_at_{k}"] = 0.0
    return metrics


def _metric_delta(baseline: dict[str, Any], challenger: dict[str, Any]) -> dict[str, float]:
    return {key: round(float(challenger.get(key, 0.0)) - float(value), 6) for key, value in baseline.items() if key != "positive_user_count"}


def _stage_contract() -> dict[str, Any]:
    return {
        "coarse": {
            "input": "frozen_pool500_candidates_from_adapter",
            "uses_labels": False,
            "output_fields": ["coarse_score", "coarse_rank", "coarse_components", "score_trace"],
            "method": "source_score_calibration_source_prior_rrf_multi_source_boost_coarse_topN",
        },
        "fine": {
            "input": "coarse_ranked_candidates",
            "uses_labels": False,
            "output_fields": ["fine_score", "item_features", "score_components", "score_trace"],
            "method": "normalized_additive_and_explainable_item_feature_scoring",
        },
        "rerank": {
            "input": "fine_ranked_candidates",
            "uses_labels": False,
            "output_fields": ["ltr_score", "rerank_score", "final_score", "rank_movement", "rerank_events", "score_trace"],
            "method": "lightgbm_lambdamart_preferred_ltr_with_pairwise_pointwise_fallback_plus_policy_guards",
        },
    }


def _stage_summaries(ranking: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    items = [item for rows in ranking.values() for item in rows]
    stage_counts = Counter(stage.get("stage") for item in items for stage in item.get("score_trace", []) if isinstance(stage, dict))
    movement = [int((item.get("rank_movement") or {}).get("coarse_to_final", 0)) for item in items]
    policy_events = [event for item in items for event in item.get("rerank_events", []) if isinstance(event, dict) and event.get("type") == "policy_rerank_guard"]
    return {
        "ranked_item_count": len(items),
        "stage_trace_counts": dict(sorted(stage_counts.items())),
        "stage_trace_complete_item_count": sum(1 for item in items if {stage.get("stage") for stage in item.get("score_trace", []) if isinstance(stage, dict)} >= {"coarse", "fine", "rerank"}),
        "average_coarse_to_final_rank_movement": round(sum(movement) / len(movement), 6) if movement else 0.0,
        "policy_rerank_guard_event_count": len(policy_events),
        "policy_rerank_guard_rules": dict(sorted(Counter(str(event.get("rule")) for event in policy_events).items())),
    }


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _label_coverage(candidates_by_user: dict[str, list[MergedCandidate]], labels: dict[str, Any]) -> dict[str, Any]:
    candidate_pairs = {(user_id, candidate.item_id) for user_id, candidates in candidates_by_user.items() for candidate in candidates}
    candidate_users = set(candidates_by_user)
    positives = set(labels["positive_pairs"])
    label_users = set(labels["positive_by_user"])
    hit_pairs = candidate_pairs & positives
    missing_reason_counts = Counter()
    for user_id, item_id in positives:
        if user_id not in candidate_users:
            missing_reason_counts["user_missing"] += 1
        elif (user_id, item_id) not in candidate_pairs:
            missing_reason_counts["item_not_in_candidate"] += 1
        else:
            missing_reason_counts["hit"] += 1
    return {
        "candidate_users": len(candidate_users),
        "candidate_pairs": len(candidate_pairs),
        "label_positive_users": len(label_users),
        "label_positive_pairs": len(positives),
        "positive_overlap_count": len(hit_pairs),
        "positive_overlap_user_count": len({user_id for user_id, _ in hit_pairs}),
        "positive_coverage": round(len(hit_pairs) / len(positives), 6) if positives else 0.0,
        "user_coverage": round(len(candidate_users & label_users) / len(label_users), 6) if label_users else 0.0,
        "candidate_hit_rate_at_20": _candidate_hit_rate_at_k(candidates_by_user, labels["positive_by_user"], 20),
        "missing_reason_counts": dict(sorted(missing_reason_counts.items())),
    }


def _candidate_hit_rate_at_k(candidates_by_user: dict[str, list[MergedCandidate]], positive_by_user: dict[str, set[str]], k: int) -> float:
    hits = 0
    for user_id, positives in positive_by_user.items():
        top_items = {candidate.item_id for candidate in candidates_by_user.get(user_id, [])[:k]}
        if top_items & positives:
            hits += 1
    return round(hits / len(positive_by_user), 6) if positive_by_user else 0.0


def _quality_metrics(candidates_by_user: dict[str, list[MergedCandidate]], ranking: dict[str, list[dict[str, Any]]], top_k: int) -> dict[str, Any]:
    candidates = [candidate for user_candidates in candidates_by_user.values() for candidate in user_candidates]
    top_items = [item for items in ranking.values() for item in items[:top_k]]
    categories = [candidate.category for candidate in candidates if candidate.category]
    source_counts = Counter(source for item in top_items for source in item.get("sources", []))
    fallback_count = sum(1 for item in top_items if _item_fallback_or_repaired(item))
    return {
        "fallback_exposure_topk_ratio": round(fallback_count / len(top_items), 6) if top_items else 0.0,
        "metadata_missing_rate": round(sum(1 for candidate in candidates if not candidate.metadata) / len(candidates), 6) if candidates else 0.0,
        "category_missing_rate": round(sum(1 for candidate in candidates if not candidate.category) / len(candidates), 6) if candidates else 0.0,
        "top_category_ratio": round(max(Counter(categories).values(), default=0) / len(candidates), 6) if candidates else 0.0,
        "top_source_concentration": round(max(source_counts.values(), default=0) / sum(source_counts.values()), 6) if source_counts else 0.0,
        "topk_source_mix": {source: round(count / sum(source_counts.values()), 6) for source, count in sorted(source_counts.items())} if source_counts else {},
    }


def _item_fallback_or_repaired(item: dict[str, Any]) -> bool:
    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    sources = {str(source) for source in item.get("sources", [])}
    if "co_visit_fallback_repair" in sources:
        return True
    return any(value and any(token in str(key).lower() for token in ("fallback", "repair", "repaired")) for key, value in metadata.items())


def _frozen_candidate_equality(candidate_rows: list[dict[str, Any]], candidates_by_user: dict[str, list[MergedCandidate]], baseline: dict[str, list[dict[str, Any]]], challenger: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    candidate_pairs_by_user = {user_id: {candidate.item_id for candidate in candidates} for user_id, candidates in candidates_by_user.items()}
    baseline_pairs_by_user = {user_id: {str(item.get("parent_asin")) for item in items if item.get("parent_asin")} for user_id, items in baseline.items()}
    challenger_pairs_by_user = {user_id: {str(item.get("parent_asin")) for item in items if item.get("parent_asin")} for user_id, items in challenger.items()}
    user_ids = sorted(set(candidate_pairs_by_user) | set(baseline_pairs_by_user) | set(challenger_pairs_by_user))
    mismatches: list[dict[str, Any]] = []
    baseline_extra_count = 0
    challenger_extra_count = 0
    symmetric_diff_count = 0
    for user_id in user_ids:
        candidate_pairs = candidate_pairs_by_user.get(user_id, set())
        baseline_pairs = baseline_pairs_by_user.get(user_id, set())
        challenger_pairs = challenger_pairs_by_user.get(user_id, set())
        baseline_extra = baseline_pairs - candidate_pairs
        challenger_extra = challenger_pairs - candidate_pairs
        baseline_extra_count += len(baseline_extra)
        challenger_extra_count += len(challenger_extra)
        symmetric_diff_count += len(baseline_pairs ^ challenger_pairs)
        if baseline_extra or challenger_extra:
            mismatches.append(
                {
                    "user_id": user_id,
                    "candidate_count": len(candidate_pairs),
                    "baseline_ranked_count": len(baseline_pairs),
                    "challenger_ranked_count": len(challenger_pairs),
                    "baseline_not_in_candidate": sorted(baseline_extra),
                    "challenger_not_in_candidate": sorted(challenger_extra),
                    "baseline_challenger_symmetric_diff": sorted(baseline_pairs ^ challenger_pairs),
                }
            )
    return {
        "status": PASS if not mismatches else STOP,
        "candidate_row_count": len(candidate_rows),
        "candidate_pair_count": sum(len(pairs) for pairs in candidate_pairs_by_user.values()),
        "baseline_ranked_pair_count": sum(len(pairs) for pairs in baseline_pairs_by_user.values()),
        "challenger_ranked_pair_count": sum(len(pairs) for pairs in challenger_pairs_by_user.values()),
        "baseline_extra_pair_count": baseline_extra_count,
        "challenger_extra_pair_count": challenger_extra_count,
        "baseline_challenger_diff_pair_count": symmetric_diff_count,
        "mismatch_user_count": len(mismatches),
        "mismatches": mismatches[:20],
    }


def _promotion_gate(
    *,
    model: dict[str, Any] | None,
    adapter_result: dict[str, Any],
    train_rows: list[dict[str, Any]],
    train_labels: dict[str, Any],
    eval_labels: dict[str, Any],
    label_coverage: dict[str, Any],
    feature_contract_gate: dict[str, Any],
    leakage_gate: dict[str, Any],
    label_separation: dict[str, Any],
    train_label_split_gate: dict[str, Any],
    frozen_equality: dict[str, Any],
    quality: dict[str, Any],
    metrics: dict[str, Any],
    top_ks: tuple[int, ...],
    gate_config: dict[str, Any],
) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    if adapter_result.get("status") != PASS:
        blockers.append(_blocker("POOL500_LEARNED_CHALLENGER_ADAPTER_NOT_PASS", {"status": adapter_result.get("status")}))
    if train_labels.get("status") != PASS:
        blockers.append(_blocker("POOL500_LEARNED_CHALLENGER_TRAIN_LABEL_ARTIFACT_INVALID", {"path": train_labels.get("path"), "blockers": train_labels.get("blockers", [])}))
    if eval_labels.get("status") != PASS:
        blockers.append(_blocker("POOL500_LEARNED_CHALLENGER_EVAL_LABEL_ARTIFACT_INVALID", {"path": eval_labels.get("path"), "blockers": eval_labels.get("blockers", [])}))
    if not _trained_ltr_model(model):
        blockers.append(_blocker("POOL500_LEARNED_CHALLENGER_MODEL_NOT_TRAINED", {**_training_sample_summary(train_rows), "model_training": model.get("training") if isinstance(model, dict) else None, "model_selection": model.get("selection") if isinstance(model, dict) else None}))
    if isinstance(model, dict) and model.get("selection", {}).get("fallback_used"):
        blockers.append(_blocker("POOL500_LEARNED_CHALLENGER_LIGHTGBM_FALLBACK_DIAGNOSTIC_ONLY", {"model_selection": model.get("selection")}))
    if feature_contract_gate.get("status") != PASS:
        blockers.append(_blocker("POOL500_LEARNED_CHALLENGER_FEATURE_CONTRACT_NOT_PASS", feature_contract_gate))
    if leakage_gate.get("status") != PASS:
        blockers.append(_blocker("POOL500_LEARNED_CHALLENGER_LEAKAGE_GATE_NOT_PASS", leakage_gate))
    if label_separation.get("status") != PASS:
        blockers.append(_blocker("POOL500_LEARNED_CHALLENGER_LABEL_SEPARATION_NOT_PASS", label_separation))
    if train_label_split_gate.get("status") != PASS:
        blockers.append(_blocker("POOL500_LEARNED_CHALLENGER_TRAIN_LABEL_SPLIT_NOT_PASS", train_label_split_gate))
    if frozen_equality.get("status") != PASS:
        blockers.append(_blocker("POOL500_LEARNED_CHALLENGER_FROZEN_EQUALITY_NOT_PASS", frozen_equality))
    if eval_labels["positive_user_count"] < int(gate_config["min_eval_positive_users"]):
        blockers.append(_blocker("POOL500_LEARNED_CHALLENGER_UNDERPOWERED_POSITIVE_USERS", {"positive_user_count": eval_labels["positive_user_count"], "required": gate_config["min_eval_positive_users"]}))
    if eval_labels["positive_segment_count"] < int(gate_config["min_eval_segments"]):
        blockers.append(_blocker("POOL500_LEARNED_CHALLENGER_SEGMENTS_INSUFFICIENT", {"positive_segment_count": eval_labels["positive_segment_count"], "required": gate_config["min_eval_segments"], "positive_split_counts": eval_labels["positive_split_counts"]}))
    missing_eval_splits = sorted(split for split in ("valid", "test") if int(eval_labels["positive_split_counts"].get(split, 0)) <= 0)
    if missing_eval_splits:
        blockers.append(_blocker("POOL500_LEARNED_CHALLENGER_VALID_TEST_POSITIVES_REQUIRED", {"missing_eval_splits": missing_eval_splits, "positive_split_counts": eval_labels["positive_split_counts"]}))
    if label_coverage["positive_coverage"] < float(gate_config["min_positive_coverage"]):
        blockers.append(_blocker("POOL500_LEARNED_CHALLENGER_LABEL_COVERAGE_INSUFFICIENT", {"positive_coverage": label_coverage["positive_coverage"], "required": gate_config["min_positive_coverage"], "missing_reason_counts": label_coverage["missing_reason_counts"]}))
    if label_coverage["candidate_hit_rate_at_20"] < float(gate_config["min_candidate_hit_rate_at_20"]):
        blockers.append(_blocker("POOL500_LEARNED_CHALLENGER_CANDIDATE_HIT_INSUFFICIENT", {"candidate_hit_rate_at_20": label_coverage["candidate_hit_rate_at_20"], "required": gate_config["min_candidate_hit_rate_at_20"]}))
    for field, threshold_key in (
        ("fallback_exposure_topk_ratio", "max_fallback_exposure_topk_ratio"),
        ("metadata_missing_rate", "max_metadata_missing_rate"),
        ("category_missing_rate", "max_category_missing_rate"),
        ("top_category_ratio", "max_top_category_ratio"),
    ):
        if float(quality.get(field, 0.0)) > float(gate_config[threshold_key]):
            blockers.append(_blocker("POOL500_LEARNED_CHALLENGER_QUALITY_GUARD_NOT_PASS", {"field": field, "value": quality.get(field), "threshold": gate_config[threshold_key]}))
    primary_k = max(top_ks)
    primary_delta = metrics["delta"].get(f"ndcg_at_{primary_k}", 0.0)
    primary_mrr_delta = metrics["delta"].get(f"mrr_at_{primary_k}", 0.0)
    if primary_delta <= 0.0:
        blockers.append(_blocker("POOL500_LEARNED_CHALLENGER_NO_PRIMARY_METRIC_LIFT", {"metric": f"ndcg_at_{primary_k}", "delta": primary_delta}))
    if primary_mrr_delta < 0.0:
        blockers.append(_blocker("POOL500_LEARNED_CHALLENGER_PRIMARY_MRR_REGRESSION", {"metric": f"mrr_at_{primary_k}", "delta": primary_mrr_delta}))
    if blockers:
        return {"decision": "NO_PROMOTE", "promotion_readiness": "diagnostic_only_no_promote", "blockers": blockers}
    return {"decision": "PROMOTE_PROPOSAL", "promotion_readiness": "offline_promotion_proposal_requires_human_review", "blockers": []}


def _training_sample_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    positives = [row for row in rows if row.get("label") == 1]
    return {
        "rows": len(rows),
        "positive_rows": len(positives),
        "negative_rows": len(rows) - len(positives),
        "users": len({row.get("user_id") for row in rows}),
        "positive_users": len({row.get("user_id") for row in positives}),
    }


def _comparison_markdown(report: dict[str, Any]) -> str:
    blockers = report["promotion_gate"]["blockers"]
    blocker_lines = "\n".join(f"- {blocker['code']}: {blocker['evidence']}" for blocker in blockers) or "- 无"
    gate = report["learned_ranking_gate"]
    gate_lines = "\n".join(
        [
            f"- fixed_report_gate: {gate['fixed_comparison_report_gate'].get('status')}",
            f"- label_metric_eligibility_gate: {gate['label_metric_eligibility_gate'].get('status')}",
            f"- rule_diagnostics_plateau_gate: {gate['rule_diagnostics_plateau_gate'].get('status')}",
            f"- feature_contract_gate: {gate['feature_contract_gate'].get('status')}",
            f"- leakage_gate: {gate['leakage_gate'].get('status')}",
        ]
    )
    return "\n".join(
        [
            "# Pool500 learned ranking frozen gate report",
            "",
            f"- 决策：{report['decision']} / {report['promotion_readiness']}",
            f"- would_be_eligible：{report['would_be_eligible']}",
            f"- current_phase_training_enabled：{report['current_phase_training_enabled']}",
            f"- fixed comparison report：{report['fixed_comparison_report_path']}",
            "",
            "## Gate status",
            gate_lines,
            "",
            "## Blockers",
            blocker_lines,
            "",
            "## Boundary",
            "该报告只评估后续阶段学习排序是否具备门槛条件；当前阶段冻结训练、晋升和 Agent-ready 产物输出。",
            "",
        ]
    )


def _blocker(code: str, evidence: dict[str, Any]) -> dict[str, Any]:
    return {"code": code, "severity": "blocker", "evidence": evidence}


def main() -> None:
    args = parse_args()
    report = run_pool500_learned_ranking_challenger(
        fixed_comparison_report_path=Path(args.fixed_comparison_report),
        expected_fixed_comparison_report_sha256=args.expected_fixed_comparison_report_sha256,
        rule_diagnostics_plateau_evidence=args.rule_diagnostics_plateau_evidence,
        pool500_candidates_path=Path(args.pool500_candidates) if args.pool500_candidates else None,
        train_label_artifact_path=Path(args.train_label_artifact) if args.train_label_artifact else None,
        eval_label_artifact_path=Path(args.eval_label_artifact) if args.eval_label_artifact else None,
        output_dir=Path(args.output_dir),
        enforce_venv=not args.skip_venv_check,
    )
    print(json.dumps({"decision": report["decision"], "would_be_eligible": report["would_be_eligible"], "output_paths": report["output_paths"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
