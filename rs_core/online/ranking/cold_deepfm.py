from __future__ import annotations

import math
import random
from collections import Counter
from typing import Any

from rs_core.data.clients import ArtifactClient
from rs_core.online.contracts import RankingRequest, RankingResult, RankingTrace
from rs_core.online.ranking.ltr import (
    extract_ltr_features,
    score_ltr_model,
    train_pointwise_logistic,
    validate_ltr_feature_contract_gate,
    validate_ltr_leakage_gate,
)
from rs_core.common.recsys_types import MergedCandidate

SCHEMA_VERSION = "cold_deepfm_ranking_chain_v1"
COLD_MODEL_TYPE = "cold_pointwise_logistic_ranker_v1"
DEEPFM_MODEL_TYPE = "deepfm_feature_cross_ranker_v1"
PASS = "PASS"
STOP = "STOP"
SKIPPED = "SKIPPED"


def build_cold_deepfm_training_rows(
    candidates_by_user: dict[str, list[MergedCandidate]],
    label_rows: list[dict[str, Any]],
    *,
    feature_config: dict[str, Any] | None = None,
    limit_users: int | None = None,
) -> dict[str, Any]:
    selected_users = list(candidates_by_user)
    if limit_users is not None:
        selected_users = selected_users[: max(0, int(limit_users))]
    selected_user_set = set(selected_users)
    label_by_pair = _label_by_pair(label_rows)
    positive_label_pairs = {pair for pair, label in label_by_pair.items() if label == 1 and pair[0] in selected_user_set}
    candidate_pairs = {
        (str(user_id), str(candidate.item_id))
        for user_id in selected_users
        for candidate in candidates_by_user.get(user_id, [])
    }
    rows: list[dict[str, Any]] = []
    for user_id in selected_users:
        for candidate in candidates_by_user.get(user_id, []):
            item_id = str(candidate.item_id)
            rows.append(
                {
                    "user_id": str(user_id),
                    "item_id": item_id,
                    "label": label_by_pair.get((str(user_id), item_id), 0),
                    "features": extract_ltr_features(candidate, feature_config or {"include_ranking_v2": True}),
                    "candidate": candidate,
                }
            )
    gate_rows = [_public_row(row) for row in rows]
    label_split_gate = _label_split_gate(label_rows)
    feature_contract_gate = validate_ltr_feature_contract_gate(gate_rows) if gate_rows else _empty_gate("feature_contract")
    leakage_gate = validate_ltr_leakage_gate(gate_rows, label_source="pool500_label_artifact", training_split="train") if gate_rows else _empty_gate("leakage")
    positive_candidate_pairs = positive_label_pairs & candidate_pairs
    summary = {
        "schema_version": "cold_deepfm_training_rows_v1",
        "rows": len(rows),
        "users": len(selected_users),
        "candidate_pairs": len(candidate_pairs),
        "label_rows": len(label_rows),
        "positive_label_pairs": len(positive_label_pairs),
        "positive_candidate_pairs": len(positive_candidate_pairs),
        "positive_rows": sum(1 for row in rows if row["label"] == 1),
        "positive_users": len({row["user_id"] for row in rows if row["label"] == 1}),
        "candidate_positive_coverage": round(len(positive_candidate_pairs) / len(positive_label_pairs), 6) if positive_label_pairs else 0.0,
        "feature_config": feature_config or {"include_ranking_v2": True},
    }
    return {
        "schema_version": "cold_deepfm_training_dataset_v1",
        "status": label_split_gate["status"],
        "rows": rows,
        "public_rows": gate_rows,
        "summary": summary,
        "feature_contract_gate": feature_contract_gate,
        "leakage_gate": leakage_gate,
        "label_split_gate": label_split_gate,
    }


def train_cold_ranker(rows: list[dict[str, Any]], config: dict[str, Any] | None = None) -> dict[str, Any]:
    public_rows = [_public_row(row) for row in rows]
    model = train_pointwise_logistic(public_rows, config or {"epochs": 5, "learning_rate": 0.05})
    model["model_type"] = COLD_MODEL_TYPE
    model["role"] = "coarse_rank"
    model["base_model_type"] = "pointwise_logistic_ltr_v1"
    model["diagnostic_only"] = True
    return model


def rank_with_cold(rows: list[dict[str, Any]], model: dict[str, Any], *, top_n: int = 200) -> dict[str, Any]:
    ranked_by_user = _rank_rows(rows, lambda features: score_ltr_model(features, model)[0], score_field="cold_score")
    kept_by_user = {user_id: user_rows[:top_n] for user_id, user_rows in ranked_by_user.items()}
    kept_rows = [row for user_rows in kept_by_user.values() for row in user_rows]
    positive_before = sum(1 for row in rows if row.get("label") == 1)
    positive_after = sum(1 for row in kept_rows if row.get("label") == 1)
    return {
        "schema_version": "cold_rank_result_v1",
        "status": PASS,
        "applied": True,
        "ranking_strategy": "cold_then_deepfm",
        "top_n": top_n,
        "rows_before": len(rows),
        "rows_after": len(kept_rows),
        "positive_before": positive_before,
        "positive_after": positive_after,
        "positive_survival_at_top_n": round(positive_after / positive_before, 6) if positive_before else 0.0,
        "candidate_count_stats": candidate_count_stats(rows),
        "ranked_by_user": ranked_by_user,
        "kept_by_user": kept_by_user,
        "kept_rows": kept_rows,
    }


def should_apply_cold(rows: list[dict[str, Any]], cold_candidate_threshold: int | None) -> bool:
    if cold_candidate_threshold is None:
        return True
    return candidate_count_stats(rows)["candidate_count_max"] > int(cold_candidate_threshold)


def bypass_cold_rank(rows: list[dict[str, Any]], *, top_n: int = 200, cold_candidate_threshold: int | None = 200) -> dict[str, Any]:
    positive_rows = sum(1 for row in rows if row.get("label") == 1)
    return {
        "schema_version": "cold_rank_bypass_result_v1",
        "status": SKIPPED,
        "applied": False,
        "ranking_strategy": "direct_deepfm",
        "reason": "candidate_count_within_threshold",
        "top_n": top_n,
        "cold_candidate_threshold": cold_candidate_threshold,
        "rows_before": len(rows),
        "rows_after": len(rows),
        "positive_before": positive_rows,
        "positive_after": positive_rows,
        "positive_survival_at_top_n": 1.0 if positive_rows else 0.0,
        "candidate_count_stats": candidate_count_stats(rows),
        "kept_rows": rows,
    }


def candidate_count_stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    counts = Counter(str(row.get("user_id") or "") for row in rows)
    values = list(counts.values())
    return {
        "users": len(values),
        "candidate_count_min": min(values, default=0),
        "candidate_count_max": max(values, default=0),
        "candidate_count_avg": round(sum(values) / len(values), 6) if values else 0.0,
    }


def train_deepfm_ranker(rows: list[dict[str, Any]], config: dict[str, Any] | None = None) -> dict[str, Any]:
    config = config or {}
    feature_names = sorted({name for row in rows for name in (row.get("features") or {})})
    if not rows or not feature_names:
        return {"model_type": DEEPFM_MODEL_TYPE, "training": {"status": "insufficient_rows", "rows": len(rows)}, "feature_names": feature_names}
    rng = random.Random(int(config.get("seed", 17)))
    factor_dim = int(config.get("factor_dim", 4))
    hidden_units = int(config.get("hidden_units", 4))
    epochs = int(config.get("epochs", 5))
    learning_rate = float(config.get("learning_rate", 0.01))
    positive_weight = float(config.get("positive_weight", 1.0))
    negative_weight = float(config.get("negative_weight", 1.0))
    linear_weights = {name: 0.0 for name in feature_names}
    fm_factors = {name: [rng.uniform(-0.01, 0.01) for _ in range(factor_dim)] for name in feature_names}
    deep_weights = [[rng.uniform(-0.01, 0.01) for _ in feature_names] for _ in range(hidden_units)]
    deep_bias = [0.0 for _ in range(hidden_units)]
    deep_output = [rng.uniform(-0.01, 0.01) for _ in range(hidden_units)]
    bias = 0.0
    loss_history: list[float] = []
    updates = 0
    for _ in range(epochs):
        epoch_loss = 0.0
        for row in rows:
            vector = _vector(row.get("features") or {}, feature_names)
            label = 1.0 if row.get("label") == 1 else 0.0
            sample_weight = positive_weight if label else negative_weight
            forward = _deepfm_forward(vector, feature_names, linear_weights, fm_factors, deep_weights, deep_bias, deep_output, bias)
            probability = _sigmoid(forward["score"])
            error = (probability - label) * sample_weight
            loss = _logistic_loss(label, probability) * sample_weight
            epoch_loss += loss
            bias -= learning_rate * error
            for name, value in zip(feature_names, vector, strict=True):
                if value == 0.0:
                    continue
                linear_weights[name] -= learning_rate * error * value
            for feature_index, (name, value) in enumerate(zip(feature_names, vector, strict=True)):
                if value == 0.0:
                    continue
                for factor_index in range(factor_dim):
                    gradient = value * (forward["factor_sums"][factor_index] - fm_factors[name][factor_index] * value)
                    fm_factors[name][factor_index] -= learning_rate * error * gradient
                for hidden_index in range(hidden_units):
                    if forward["hidden_pre_activation"][hidden_index] <= 0.0:
                        continue
                    gradient = forward["deep_output_before_update"][hidden_index] * value
                    deep_weights[hidden_index][feature_index] -= learning_rate * error * gradient
            for hidden_index, hidden_value in enumerate(forward["hidden"]):
                deep_output[hidden_index] -= learning_rate * error * hidden_value
                if forward["hidden_pre_activation"][hidden_index] > 0.0:
                    deep_bias[hidden_index] -= learning_rate * error * forward["deep_output_before_update"][hidden_index]
            updates += 1
        loss_history.append(round(epoch_loss / len(rows), 10))
    return {
        "model_type": DEEPFM_MODEL_TYPE,
        "feature_names": feature_names,
        "bias": round(bias, 10),
        "linear_weights": {name: round(value, 10) for name, value in linear_weights.items() if value},
        "fm_factors": {name: [round(value, 10) for value in values] for name, values in fm_factors.items()},
        "deep_weights": [[round(value, 10) for value in values] for values in deep_weights],
        "deep_bias": [round(value, 10) for value in deep_bias],
        "deep_output": [round(value, 10) for value in deep_output],
        "training": {
            "status": "trained",
            "rows": len(rows),
            "positive_rows": sum(1 for row in rows if row.get("label") == 1),
            "positive_users": len({row["user_id"] for row in rows if row.get("label") == 1}),
            "epochs": epochs,
            "learning_rate": learning_rate,
            "factor_dim": factor_dim,
            "hidden_units": hidden_units,
            "updates": updates,
            "loss_history": loss_history,
        },
        "diagnostic_only": True,
    }


def score_deepfm_model(features: dict[str, float], model: dict[str, Any]) -> float:
    feature_names = [str(name) for name in model.get("feature_names", [])]
    linear_weights = {str(name): float(value) for name, value in (model.get("linear_weights") or {}).items()}
    fm_factors = {str(name): [float(value) for value in values] for name, values in (model.get("fm_factors") or {}).items()}
    deep_weights = [[float(value) for value in values] for values in (model.get("deep_weights") or [])]
    deep_bias = [float(value) for value in (model.get("deep_bias") or [])]
    deep_output = [float(value) for value in (model.get("deep_output") or [])]
    vector = _vector(features, feature_names)
    return _deepfm_forward(vector, feature_names, linear_weights, fm_factors, deep_weights, deep_bias, deep_output, float(model.get("bias", 0.0)))["score"]


def rank_with_deepfm(rows: list[dict[str, Any]], model: dict[str, Any], *, top_k: int = 20) -> dict[str, Any]:
    ranked_by_user = _rank_rows(rows, lambda features: score_deepfm_model(features, model), score_field="deepfm_score")
    final_by_user = {user_id: user_rows[:top_k] for user_id, user_rows in ranked_by_user.items()}
    final_rows = [row for user_rows in final_by_user.values() for row in user_rows]
    positive_before = sum(1 for row in rows if row.get("label") == 1)
    positive_after = sum(1 for row in final_rows if row.get("label") == 1)
    return {
        "schema_version": "deepfm_rank_result_v1",
        "top_k": top_k,
        "rows_before": len(rows),
        "rows_after": len(final_rows),
        "positive_before": positive_before,
        "positive_after": positive_after,
        "positive_survival_at_top_k": round(positive_after / positive_before, 6) if positive_before else 0.0,
        "ranked_by_user": ranked_by_user,
        "final_by_user": final_by_user,
        "final_rows": final_rows,
    }


def run_cold_deepfm_chain(
    candidates_by_user: dict[str, list[MergedCandidate]],
    label_rows: list[dict[str, Any]],
    *,
    cold_top_n: int = 200,
    deepfm_top_k: int = 20,
    cold_candidate_threshold: int | None = 200,
    limit_users: int | None = None,
    feature_config: dict[str, Any] | None = None,
    cold_config: dict[str, Any] | None = None,
    deepfm_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    dataset = build_cold_deepfm_training_rows(candidates_by_user, label_rows, feature_config=feature_config, limit_users=limit_users)
    rows = dataset["rows"]
    blockers = [] if rows else [{"code": "COLD_DEEPFM_EMPTY_TRAINING_ROWS", "severity": "blocker"}]
    if dataset.get("label_split_gate", {}).get("status") != PASS:
        blockers.append({"code": "COLD_DEEPFM_LABEL_SPLIT_NOT_TRAIN", "severity": "blocker", "evidence": dataset.get("label_split_gate", {})})
    apply_cold = should_apply_cold(rows, cold_candidate_threshold) if rows and not blockers else False
    cold_model = train_cold_ranker(rows, cold_config) if apply_cold else None
    cold_rank = rank_with_cold(rows, cold_model, top_n=cold_top_n) if cold_model else bypass_cold_rank(rows, top_n=cold_top_n, cold_candidate_threshold=cold_candidate_threshold)
    deepfm_rows = cold_rank["kept_rows"] if cold_rank else []
    deepfm_model = train_deepfm_ranker(deepfm_rows, deepfm_config) if deepfm_rows and not blockers else None
    deepfm_rank = rank_with_deepfm(deepfm_rows, deepfm_model, top_k=deepfm_top_k) if deepfm_model else None
    return {
        "schema_version": SCHEMA_VERSION,
        "status": PASS if not blockers else STOP,
        "diagnostic_only": True,
        "candidate_generation_allowed": False,
        "ranking_input_replacement_allowed": False,
        "ranking_replacement_allowed": False,
        "promotion_allowed": False,
        "ranking_strategy": "cold_then_deepfm" if apply_cold else "direct_deepfm",
        "cold_candidate_threshold": cold_candidate_threshold,
        "blockers": blockers,
        "training_sample_summary": dataset["summary"],
        "feature_contract_gate": dataset["feature_contract_gate"],
        "leakage_gate": dataset["leakage_gate"],
        "label_split_gate": dataset["label_split_gate"],
        "cold": _public_cold_result(cold_model, cold_rank),
        "deepfm": _public_deepfm_result(deepfm_model, deepfm_rank),
        "final_rankings": _public_rankings(deepfm_rank["final_by_user"] if deepfm_rank else {}),
    }


def _label_by_pair(label_rows: list[dict[str, Any]]) -> dict[tuple[str, str], int]:
    labels: dict[tuple[str, str], int] = {}
    for row in label_rows:
        user_id = str(row.get("user_id") or "")
        item_id = str(row.get("parent_asin") or row.get("item_id") or "")
        if not user_id or not item_id:
            continue
        labels[(user_id, item_id)] = 1 if _positive(row) else 0
    return labels


def _label_split_gate(label_rows: list[dict[str, Any]]) -> dict[str, Any]:
    forbidden_splits = {"valid", "test", "holdout"}
    split_counts = Counter(str(row.get("split") or row.get("label_split") or "unknown").lower() for row in label_rows)
    rejected = sorted(split for split in split_counts if split in forbidden_splits)
    return {
        "status": STOP if rejected else PASS,
        "split_counts": dict(sorted(split_counts.items())),
        "rejected_splits": rejected,
        "allowed_training_splits": ["train", "unknown"],
        "reasons": ["non_train_label_split"] if rejected else [],
    }


def _positive(row: dict[str, Any]) -> bool:
    for key in ("label_binary", "label", "clicked", "purchased", "is_hit"):
        if key in row:
            value = row.get(key)
            if isinstance(value, str):
                return value.strip().lower() in {"1", "true", "yes", "positive"}
            return bool(value)
    return False


def _public_row(row: dict[str, Any]) -> dict[str, Any]:
    return {"user_id": row["user_id"], "item_id": row["item_id"], "label": row["label"], "features": dict(row.get("features") or {})}


def _empty_gate(kind: str) -> dict[str, Any]:
    return {"status": PASS, "checked_rows": 0, "reasons": [], "kind": kind}


def _rank_rows(rows: list[dict[str, Any]], scorer: Any, *, score_field: str) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        score = float(scorer(row.get("features") or {}))
        candidate = row.get("candidate")
        sources = row.get("sources") or list(getattr(candidate, "sources", []))
        category = row.get("category") or getattr(candidate, "category", "")
        ranked_row = _public_row(row) | {score_field: score, "sources": list(sources), "category": category, "candidate_rank": row.get("candidate_rank")}
        grouped.setdefault(str(row["user_id"]), []).append(ranked_row)
    for user_rows in grouped.values():
        user_rows.sort(key=lambda row: (-float(row[score_field]), _rank_tiebreaker(row.get("candidate_rank")), str(row["item_id"])))
    return grouped


def _rank_tiebreaker(value: Any) -> int:
    if isinstance(value, bool):
        return 1_000_000_000
    if isinstance(value, int):
        return value if value > 0 else 1_000_000_000
    if isinstance(value, float) and value > 0:
        return int(value)
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return 1_000_000_000


def _vector(features: dict[str, float], feature_names: list[str]) -> list[float]:
    return [_scale_feature_value(float(features.get(name, 0.0) or 0.0)) for name in feature_names]


def _scale_feature_value(value: float) -> float:
    if not math.isfinite(value):
        return 0.0
    if abs(value) <= 10.0:
        return value
    return math.copysign(math.log1p(abs(value)), value)


def _deepfm_forward(
    vector: list[float],
    feature_names: list[str],
    linear_weights: dict[str, float],
    fm_factors: dict[str, list[float]],
    deep_weights: list[list[float]],
    deep_bias: list[float],
    deep_output: list[float],
    bias: float,
) -> dict[str, Any]:
    linear = bias + sum(linear_weights.get(name, 0.0) * value for name, value in zip(feature_names, vector, strict=True))
    factor_dim = len(next(iter(fm_factors.values()), []))
    factor_sums = [0.0 for _ in range(factor_dim)]
    factor_square_sums = [0.0 for _ in range(factor_dim)]
    for name, value in zip(feature_names, vector, strict=True):
        factors = fm_factors.get(name, [0.0 for _ in range(factor_dim)])
        for index, factor in enumerate(factors):
            product = factor * value
            factor_sums[index] += product
            factor_square_sums[index] += product * product
    fm_score = 0.5 * sum(total * total - square for total, square in zip(factor_sums, factor_square_sums, strict=True))
    hidden_pre_activation = [sum(weight * value for weight, value in zip(weights, vector, strict=True)) + deep_bias[index] for index, weights in enumerate(deep_weights)]
    hidden = [max(0.0, value) for value in hidden_pre_activation]
    deep_score = sum(weight * value for weight, value in zip(deep_output, hidden, strict=True))
    return {
        "score": linear + fm_score + deep_score,
        "factor_sums": factor_sums,
        "hidden_pre_activation": hidden_pre_activation,
        "hidden": hidden,
        "deep_output_before_update": list(deep_output),
    }


def _sigmoid(value: float) -> float:
    if value >= 35:
        return 1.0
    if value <= -35:
        return 0.0
    return 1.0 / (1.0 + math.exp(-value))


def _logistic_loss(label: float, probability: float) -> float:
    probability = min(max(probability, 1e-12), 1.0 - 1e-12)
    return -(label * math.log(probability) + (1.0 - label) * math.log(1.0 - probability))


def _public_cold_result(model: dict[str, Any] | None, rank: dict[str, Any] | None) -> dict[str, Any]:
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
        "rows_before": rank["rows_before"],
        "rows_after": rank["rows_after"],
        "positive_survival_at_top_n": rank["positive_survival_at_top_n"],
    }
    return {key: value for key, value in result.items() if value is not None}


def _public_deepfm_result(model: dict[str, Any] | None, rank: dict[str, Any] | None) -> dict[str, Any]:
    if model is None or rank is None:
        return {"status": STOP}
    return {
        "status": PASS,
        "model_type": model.get("model_type"),
        "training": model.get("training", {}),
        "top_k": rank["top_k"],
        "rows_before": rank["rows_before"],
        "rows_after": rank["rows_after"],
        "positive_survival_at_top_k": rank["positive_survival_at_top_k"],
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


def summarize_label_distribution(rows: list[dict[str, Any]]) -> dict[str, Any]:
    counts = Counter(int(row.get("label", 0)) for row in rows)
    return {"positive": counts.get(1, 0), "negative": counts.get(0, 0), "rows": len(rows)}


def rank_with_cold_deepfm_shadow_contract(
    request: RankingRequest | dict[str, Any],
    *,
    artifact_client: ArtifactClient | None = None,
) -> RankingResult:
    """Adapt COLD→DeepFM diagnostics to the online ranking contract without promotion."""

    ranking_request = request if isinstance(request, RankingRequest) else RankingRequest(**dict(request))
    ranked_item_ids = _stable_ranked_item_ids(ranking_request)
    shadow_status = _run_shadow_diagnostic(ranking_request, ranked_item_ids, artifact_client=artifact_client)
    route = "cold_deepfm_diagnostic_no_promotion" if shadow_status == "computed" else "cold_deepfm_diagnostic_skipped_no_promotion"
    return RankingResult(
        ranked_item_ids=ranked_item_ids,
        ranking_trace=RankingTrace(
            ranker="cold_deepfm_shadow_contract",
            returned_count=len(ranked_item_ids),
            route=route,
        ).to_dict(),
    )


def _stable_ranked_item_ids(request: RankingRequest) -> list[str]:
    top_k = max(1, int(request.return_top_k or 20))
    return list(dict.fromkeys(str(item) for item in request.candidate_item_ids if item))[:top_k]


def _run_shadow_diagnostic(
    request: RankingRequest,
    ranked_item_ids: list[str],
    *,
    artifact_client: ArtifactClient | None = None,
) -> str:
    shadow = request.ranking_context.get("cold_deepfm_shadow") if isinstance(request.ranking_context, dict) else None
    if not isinstance(shadow, dict) or not shadow.get("enabled"):
        return "skipped"
    rows = _candidate_feature_rows(shadow, ranked_item_ids)
    if not rows:
        return "skipped"
    try:
        ranked_rows = rows
        cold_model = _shadow_model(shadow, "cold_model", "cold_model_artifact", artifact_client)
        if isinstance(cold_model, dict):
            cold_top_n = int(shadow.get("cold_top_n") or len(rows) or 1)
            ranked_rows = rank_with_cold(rows, cold_model, top_n=cold_top_n).get("kept_rows", rows)
        deepfm_model = _shadow_model(shadow, "deepfm_model", "deepfm_model_artifact", artifact_client)
        if isinstance(deepfm_model, dict):
            rank_with_deepfm(ranked_rows, deepfm_model, top_k=max(1, int(request.return_top_k or 20)))
        return "computed"
    except (OSError, KeyError, TypeError, ValueError, ArithmeticError):
        return "skipped"


def _shadow_model(
    shadow: dict[str, Any],
    inline_key: str,
    artifact_key: str,
    artifact_client: ArtifactClient | None,
) -> dict[str, Any] | None:
    inline_model = shadow.get(inline_key)
    if isinstance(inline_model, dict):
        return inline_model
    artifact_ref = shadow.get(artifact_key)
    if not isinstance(artifact_ref, dict) or artifact_client is None:
        return None
    uri = artifact_ref.get("uri") or artifact_ref.get("path")
    if not uri:
        return None
    artifact_id = str(artifact_ref.get("artifact_id") or artifact_ref.get("id") or inline_key)
    kind = str(artifact_ref.get("kind") or "ranking_model")
    model = artifact_client.read_json_artifact(artifact_id, str(uri), kind=kind)
    return model if isinstance(model, dict) else None


def _candidate_feature_rows(shadow: dict[str, Any], ranked_item_ids: list[str]) -> list[dict[str, Any]]:
    feature_by_item = _feature_by_item_id(shadow.get("candidate_features"))
    user_id = str(shadow.get("user_id") or "online-shadow-user")
    rows: list[dict[str, Any]] = []
    for index, item_id in enumerate(ranked_item_ids, start=1):
        features = feature_by_item.get(item_id)
        if not isinstance(features, dict):
            continue
        rows.append({
            "user_id": user_id,
            "item_id": item_id,
            "label": 0,
            "features": {str(key): float(value) for key, value in features.items() if _is_number(value)},
            "candidate_rank": index,
        })
    return rows


def _feature_by_item_id(raw_features: Any) -> dict[str, dict[str, Any]]:
    if isinstance(raw_features, dict):
        return {str(item_id): features for item_id, features in raw_features.items() if isinstance(features, dict)}
    if isinstance(raw_features, list):
        feature_by_item: dict[str, dict[str, Any]] = {}
        for row in raw_features:
            if not isinstance(row, dict):
                continue
            item_id = str(row.get("item_id") or row.get("parent_asin") or "")
            features = row.get("features")
            if item_id and isinstance(features, dict):
                feature_by_item[item_id] = features
        return feature_by_item
    return {}


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)
