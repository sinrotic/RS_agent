from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from rs_core.common.recsys_types import MergedCandidate

SOURCE_NAMES = ("popular", "itemcf_weak", "itemcf_strong", "category", "semantic", "semantic_title_category_expansion", "usercf_recall", "swing_recall", "two_tower", "co_visit_fallback_repair")
LEAKAGE_GATE_SCHEMA_VERSION = "ranking_feature_leakage_gate_v1"
FEATURE_CONTRACT_GATE_SCHEMA_VERSION = "ranking_feature_contract_gate_v1"
FORBIDDEN_FEATURE_NAME_TOKENS = ("target", "label", "holdout", "future")
FORBIDDEN_LABEL_SOURCES = {"valid_test_holdout", "valid_holdout", "test_holdout", "holdout"}
FORBIDDEN_TRAINING_SPLITS = {"valid", "test", "holdout"}
ALLOWED_EXACT_FEATURE_NAMES = {
    "multi_source",
    "itemcf_source",
    "itemcf_multi_source",
    "two_tower_source",
    "two_tower_only",
    "two_tower_multi_source",
    "two_tower_itemcf_source",
    "two_tower_semantic_source",
    "semantic_only",
    "popular_only",
    "source_count",
    "semantic_itemcf_source",
    "itemcf_semantic_source",
    "itemcf_two_tower_source",
    "two_tower_semantic_itemcf_source",
    "itemcf_two_tower_semantic_source",
    "recent_pop_score",
    "verified_pop_score",
    "time_decay_pop_score",
    "semantic_seed_rank",
    "two_tower_seed_rank",
    "two_tower_overlap",
    "average_rating",
    "rating_number",
    "source_rank_min",
    "source_rank_mean",
    "source_rank_reciprocal_max",
    "category_known",
    "metadata_present",
    "fallback_indicator",
    "repaired_indicator",
    "fallback_or_repaired_indicator",
    "source_diversity_count",
    "source_diversity_entropy",
    "category_source_diversity",
    "quality_score",
    "freshness_score",
}
ALLOWED_FEATURE_PREFIXES = (
    "has_",
    "score_",
    "source_score_",
    "candidate_rank",
    "source_rank_",
)


def build_ltr_leakage_gate_summary(
    rows: list[dict[str, Any]],
    *,
    label_source: str = "leave_one_positive_out_train",
    training_split: str = "train",
) -> dict[str, Any]:
    forbidden_feature_names = sorted(
        {
            name
            for row in rows
            for name in (row.get("features") or {})
            if _is_forbidden_feature_name(str(name))
        }
    )
    reasons: list[str] = []
    if forbidden_feature_names:
        reasons.append("forbidden_feature_names")
    if label_source in FORBIDDEN_LABEL_SOURCES:
        reasons.append("forbidden_label_source")
    if training_split in FORBIDDEN_TRAINING_SPLITS:
        reasons.append("forbidden_training_split")
    return {
        "schema_version": LEAKAGE_GATE_SCHEMA_VERSION,
        "status": "REJECT" if reasons else "PASS",
        "label_source": label_source,
        "training_split": training_split,
        "checked_rows": len(rows),
        "forbidden_feature_name_tokens": list(FORBIDDEN_FEATURE_NAME_TOKENS),
        "forbidden_feature_names": forbidden_feature_names,
        "reasons": reasons,
    }


def validate_ltr_leakage_gate(
    rows: list[dict[str, Any]],
    *,
    label_source: str = "leave_one_positive_out_train",
    training_split: str = "train",
) -> dict[str, Any]:
    summary = build_ltr_leakage_gate_summary(rows, label_source=label_source, training_split=training_split)
    if summary["status"] != "PASS":
        raise ValueError(f"LTR leakage gate rejected training data: {summary['reasons']}")
    return summary


def build_ltr_feature_contract_gate_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    feature_names = sorted({str(name) for row in rows for name in (row.get("features") or {})})
    forbidden_feature_names = [name for name in feature_names if _is_forbidden_feature_name(name)]
    unknown_feature_names = [name for name in feature_names if not _is_allowed_contract_feature_name(name)]
    reasons: list[str] = []
    if forbidden_feature_names:
        reasons.append("forbidden_feature_names")
    if unknown_feature_names:
        reasons.append("unknown_feature_names")
    return {
        "schema_version": FEATURE_CONTRACT_GATE_SCHEMA_VERSION,
        "status": "REJECT" if reasons else "PASS",
        "checked_rows": len(rows),
        "checked_feature_count": len(feature_names),
        "allowed_exact_feature_names": sorted(ALLOWED_EXACT_FEATURE_NAMES),
        "allowed_feature_prefixes": list(ALLOWED_FEATURE_PREFIXES),
        "forbidden_feature_names": forbidden_feature_names,
        "unknown_feature_names": unknown_feature_names,
        "reasons": reasons,
    }


def validate_ltr_feature_contract_gate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    summary = build_ltr_feature_contract_gate_summary(rows)
    if summary["status"] != "PASS":
        raise ValueError(f"LTR feature contract gate rejected training data: {summary['reasons']}")
    return summary


def _is_forbidden_feature_name(name: str) -> bool:
    normalized = name.lower()
    return any(token in normalized for token in FORBIDDEN_FEATURE_NAME_TOKENS)


def _is_allowed_contract_feature_name(name: str) -> bool:
    return name in ALLOWED_EXACT_FEATURE_NAMES or any(name.startswith(prefix) for prefix in ALLOWED_FEATURE_PREFIXES)


def extract_ltr_features(candidate: MergedCandidate, config: dict[str, Any] | None = None) -> dict[str, float]:
    config = config or {}
    source_set = {source for source in candidate.sources if not source.startswith("feedback_")}
    itemcf_sources = {"itemcf_weak", "itemcf_strong"}
    features: dict[str, float] = {}
    for source in SOURCE_NAMES:
        features[f"has_{source}"] = float(source in source_set)
        features[f"score_{source}"] = float(candidate.source_scores.get(source, 0.0) or 0.0)
    features["multi_source"] = float(len(source_set) >= 2)
    features["itemcf_source"] = float(bool(source_set & itemcf_sources))
    features["itemcf_multi_source"] = float(bool(source_set & itemcf_sources) and len(source_set) >= 2)
    features["two_tower_source"] = float("two_tower" in source_set)
    features["two_tower_only"] = float(source_set == {"two_tower"})
    features["two_tower_multi_source"] = float("two_tower" in source_set and len(source_set) >= 2)
    features["two_tower_itemcf_source"] = float("two_tower" in source_set and bool(source_set & itemcf_sources))
    features["two_tower_semantic_source"] = float("two_tower" in source_set and "semantic" in source_set)
    features["semantic_only"] = float(source_set == {"semantic"})
    features["popular_only"] = float(source_set == {"popular"})
    if config.get("include_metadata", True):
        features["recent_pop_score"] = _as_float(candidate.metadata.get("recent_pop_score", 0.0))
        features["verified_pop_score"] = _as_float(candidate.metadata.get("verified_pop_score", 0.0))
        features["time_decay_pop_score"] = _as_float(candidate.metadata.get("time_decay_pop_score", 0.0))
    if _ranking_v2_enabled(config):
        features.update(_ranking_v2_features(candidate, source_set, itemcf_sources))
    return features


def score_ltr(features: dict[str, float], weights: dict[str, float], bias: float = 0.0) -> float:
    return float(bias) + sum(float(weights.get(name, 0.0)) * float(value) for name, value in features.items())


def score_ltr_model(features: dict[str, float], model: dict[str, Any]) -> tuple[float, list[dict[str, Any]]]:
    model_type = str(model.get("model_type") or "")
    if model_type == "lightgbm_lambdamart_ltr_v1":
        score, event = _score_lightgbm_lambdamart(features, model)
        return score, [event]
    weights = model.get("weights")
    if not isinstance(weights, dict) or not weights:
        return 0.0, []
    return score_ltr(features, weights, float(model.get("bias", 0.0))), [{"type": "ltr_model", "model_type": model.get("model_type", "unknown")}]


def _score_lightgbm_lambdamart(features: dict[str, float], model: dict[str, Any]) -> tuple[float, dict[str, Any]]:
    try:
        import lightgbm as lgb  # type: ignore[import-not-found]
    except Exception as exc:  # pragma: no cover - depends on optional local dependency
        return 0.0, {"type": "ltr_model_unavailable", "model_type": model.get("model_type"), "dependency": "lightgbm", "reason": type(exc).__name__}
    booster_model = model.get("booster_model")
    feature_names = [str(name) for name in model.get("feature_names", [])]
    if not booster_model or not feature_names:
        return 0.0, {"type": "ltr_model_unavailable", "model_type": model.get("model_type"), "reason": "missing_booster_or_features"}
    booster = lgb.Booster(model_str=str(booster_model))
    vector = [[float(features.get(name, 0.0)) for name in feature_names]]
    prediction = booster.predict(vector)
    return float(prediction[0]), {"type": "ltr_model", "model_type": model.get("model_type"), "dependency": "lightgbm"}


def _ranking_v2_enabled(config: dict[str, Any]) -> bool:
    ranking_v2 = config.get("ranking_v2", {})
    ranking_v2_enabled = isinstance(ranking_v2, dict) and ranking_v2.get("enabled")
    return bool(config.get("include_ranking_v2", False) or config.get("version") == "ltr_v2" or config.get("feature_version") == "ranking_v2" or ranking_v2_enabled)


def _ranking_v2_features(candidate: MergedCandidate, source_set: set[str], itemcf_sources: set[str]) -> dict[str, float]:
    scores = {source: _as_float(candidate.source_scores.get(source, 0.0)) for source in SOURCE_NAMES}
    active_scores = [score for source, score in scores.items() if source in source_set]
    max_score = max(active_scores, default=0.0)
    min_score = min(active_scores, default=0.0)
    semantic_score = scores["semantic"]
    two_tower_score = scores["two_tower"]
    itemcf_score = max(scores["itemcf_weak"], scores["itemcf_strong"])
    best_non_popular_score = max(score for source, score in scores.items() if source != "popular")
    source_count = len(source_set)
    features = {
        "source_count": float(source_count),
        "source_score_sum": sum(active_scores),
        "source_score_max": max_score,
        "source_score_min": min_score,
        "source_score_gap": max_score - min_score,
        "source_score_mean": sum(active_scores) / source_count if source_count else 0.0,
        "semantic_itemcf_source": float("semantic" in source_set and bool(source_set & itemcf_sources)),
        "itemcf_semantic_source": float("semantic" in source_set and bool(source_set & itemcf_sources)),
        "itemcf_two_tower_source": float("two_tower" in source_set and bool(source_set & itemcf_sources)),
        "two_tower_semantic_itemcf_source": float("two_tower" in source_set and "semantic" in source_set and bool(source_set & itemcf_sources)),
        "itemcf_two_tower_semantic_source": float("two_tower" in source_set and "semantic" in source_set and bool(source_set & itemcf_sources)),
        "score_two_tower_semantic_gap": two_tower_score - semantic_score,
        "score_semantic_two_tower_gap": semantic_score - two_tower_score,
        "score_itemcf_semantic_gap": itemcf_score - semantic_score,
        "score_semantic_itemcf_gap": semantic_score - itemcf_score,
        "score_two_tower_itemcf_gap": two_tower_score - itemcf_score,
        "score_itemcf_two_tower_gap": itemcf_score - two_tower_score,
        "score_non_popular_minus_popular": best_non_popular_score - scores["popular"],
        "score_popular_minus_non_popular": scores["popular"] - best_non_popular_score,
        "semantic_seed_rank": _as_float(candidate.metadata.get("semantic_seed_rank", 0.0)),
        "two_tower_seed_rank": _as_float(candidate.metadata.get("two_tower_seed_rank", 0.0)),
        "two_tower_overlap": _as_float(candidate.metadata.get("two_tower_overlap", 0.0)),
        "average_rating": _as_float(candidate.metadata.get("average_rating", candidate.metadata.get("rating", 0.0))),
        "rating_number": _as_float(candidate.metadata.get("rating_number", 0.0)),
        **_pool500_industrial_features(candidate, source_set),
    }
    features["score_two_tower_semantic_ratio"] = _safe_ratio(two_tower_score, semantic_score)
    features["score_semantic_two_tower_ratio"] = _safe_ratio(semantic_score, two_tower_score)
    features["score_itemcf_semantic_ratio"] = _safe_ratio(itemcf_score, semantic_score)
    features["score_semantic_itemcf_ratio"] = _safe_ratio(semantic_score, itemcf_score)
    features["score_non_popular_popular_ratio"] = _safe_ratio(best_non_popular_score, scores["popular"])
    return features


def _pool500_industrial_features(candidate: MergedCandidate, source_set: set[str]) -> dict[str, float]:
    lineage = candidate.metadata.get("pool500_source_lineage")
    lineage_rows = lineage if isinstance(lineage, list) else []
    ranks = [_as_float(row.get("rank")) for row in lineage_rows if isinstance(row, dict) and row.get("rank") not in (None, "")]
    source_count = len(source_set)
    fallback = _metadata_has_marker(candidate.metadata, ("fallback",)) or "co_visit_fallback_repair" in source_set
    repaired = _metadata_has_marker(candidate.metadata, ("repair", "repaired")) or "co_visit_fallback_repair" in source_set
    return {
        "source_rank_min": min(ranks, default=0.0),
        "source_rank_mean": sum(ranks) / len(ranks) if ranks else 0.0,
        "source_rank_reciprocal_max": max((1.0 / rank for rank in ranks if rank > 0), default=0.0),
        "category_known": float(bool(candidate.category or candidate.metadata.get("category"))),
        "metadata_present": float(bool(candidate.metadata)),
        "fallback_indicator": float(fallback),
        "repaired_indicator": float(repaired),
        "fallback_or_repaired_indicator": float(fallback or repaired),
        "source_diversity_count": float(source_count),
        "source_diversity_entropy": _source_entropy(source_set),
        "category_source_diversity": float(bool(candidate.category) and source_count >= 2),
        "quality_score": _quality_feature_value(candidate.metadata),
        "freshness_score": _freshness_feature_value(candidate.metadata),
    }


def _metadata_has_marker(metadata: dict[str, Any], tokens: tuple[str, ...]) -> bool:
    for key, value in metadata.items():
        lowered = str(key).lower()
        if value and any(token in lowered for token in tokens):
            return True
    return False


def _source_entropy(source_set: set[str]) -> float:
    if not source_set:
        return 0.0
    probability = 1.0 / len(source_set)
    return -sum(probability * math.log2(probability) for _ in source_set)


def _quality_feature_value(metadata: dict[str, Any]) -> float:
    for key in ("quality_score", "verified_pop_score", "average_rating", "rating"):
        if metadata.get(key) not in (None, ""):
            return _as_float(metadata.get(key))
    return 0.0


def _freshness_feature_value(metadata: dict[str, Any]) -> float:
    for key in ("freshness_score", "recent_pop_score", "time_decay_pop_score"):
        if metadata.get(key) not in (None, ""):
            return _as_float(metadata.get(key))
    return 0.0


def _safe_ratio(numerator: float, denominator: float) -> float:
    if not denominator:
        return 0.0
    return numerator / denominator


def _as_float(value: Any) -> float:
    if value in (None, ""):
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def train_pairwise_perceptron(rows: list[dict[str, Any]], config: dict[str, Any] | None = None) -> dict[str, Any]:
    config = config or {}
    epochs = int(config.get("epochs", 5))
    learning_rate = float(config.get("learning_rate", 0.05))
    negatives_per_positive = int(config.get("negative_sample_per_positive", 20))
    margin = float(config.get("margin", 1.0))
    weights: dict[str, float] = {name: float(value) for name, value in config.get("initial_weights", {}).items()}
    bias = float(config.get("initial_bias", 0.0))
    grouped = _group_rows_by_user(rows)
    positive_rows = [row for row in rows if row.get("label") == 1]
    update_count = 0
    pair_count = 0
    feature_names = sorted({name for row in rows for name in row["features"]})
    for _ in range(epochs):
        for user_rows in grouped.values():
            positives = [row for row in user_rows if row.get("label") == 1]
            negatives = [row for row in user_rows if row.get("label") != 1]
            if not positives or not negatives:
                continue
            negatives = negatives[:negatives_per_positive]
            for positive in positives:
                for negative in negatives:
                    pair_count += 1
                    pos_score = score_ltr(positive["features"], weights, bias)
                    neg_score = score_ltr(negative["features"], weights, bias)
                    if pos_score <= neg_score + margin:
                        _update_weights(weights, positive["features"], learning_rate)
                        _update_weights(weights, negative["features"], -learning_rate)
                        update_count += 1
    return {
        "model_type": "pairwise_perceptron_ltr_v1",
        "weights": {name: round(weights.get(name, 0.0), 10) for name in feature_names if weights.get(name, 0.0)},
        "bias": round(bias, 10),
        "feature_names": feature_names,
        "training": {
            "rows": len(rows),
            "users": len(grouped),
            "positive_rows": len(positive_rows),
            "positive_users": len({row["user_id"] for row in positive_rows}),
            "epochs": epochs,
            "learning_rate": learning_rate,
            "negative_sample_per_positive": negatives_per_positive,
            "margin": margin,
            "pairs_seen": pair_count,
            "updates": update_count,
        },
    }



def train_pointwise_logistic(rows: list[dict[str, Any]], config: dict[str, Any] | None = None) -> dict[str, Any]:
    config = config or {}
    epochs = int(config.get("epochs", 5))
    learning_rate = float(config.get("learning_rate", 0.05))
    positive_weight = float(config.get("positive_weight", 1.0))
    negative_weight = float(config.get("negative_weight", 1.0))
    weights: dict[str, float] = {name: float(value) for name, value in config.get("initial_weights", {}).items()}
    bias = float(config.get("initial_bias", 0.0))
    feature_names = sorted({name for row in rows for name in row["features"]})
    positive_rows = [row for row in rows if row.get("label") == 1]
    updates = 0
    loss_sum = 0.0
    for _ in range(epochs):
        for row in rows:
            label = 1.0 if row.get("label") == 1 else 0.0
            sample_weight = positive_weight if label else negative_weight
            raw_score = score_ltr(row["features"], weights, bias)
            probability = _sigmoid(raw_score)
            error = (label - probability) * sample_weight
            _update_weights(weights, row["features"], learning_rate * error)
            bias += learning_rate * error
            loss_sum += _logistic_loss(label, probability) * sample_weight
            updates += 1
    return {
        "model_type": "pointwise_logistic_ltr_v1",
        "weights": {name: round(weights.get(name, 0.0), 10) for name in feature_names if weights.get(name, 0.0)},
        "bias": round(bias, 10),
        "feature_names": feature_names,
        "training": {
            "rows": len(rows),
            "positive_rows": len(positive_rows),
            "positive_users": len({row["user_id"] for row in positive_rows}),
            "epochs": epochs,
            "learning_rate": learning_rate,
            "positive_weight": positive_weight,
            "negative_weight": negative_weight,
            "updates": updates,
            "average_loss": round(loss_sum / updates, 10) if updates else 0.0,
        },
    }


def train_lightgbm_lambdamart(rows: list[dict[str, Any]], config: dict[str, Any] | None = None) -> dict[str, Any]:
    config = config or {}
    try:
        import lightgbm as lgb  # type: ignore[import-not-found]
    except Exception as exc:
        return {
            "model_type": "lightgbm_lambdamart_ltr_v1",
            "training": {"status": "dependency_unavailable", "dependency": "lightgbm", "reason": type(exc).__name__},
            "feature_names": sorted({name for row in rows for name in row.get("features", {})}),
        }
    grouped = _group_rows_by_user(rows)
    feature_names = sorted({name for row in rows for name in row.get("features", {})})
    if not feature_names or not grouped:
        return {"model_type": "lightgbm_lambdamart_ltr_v1", "training": {"status": "insufficient_rows"}, "feature_names": feature_names}
    train_rows = [row for user_rows in grouped.values() for row in user_rows]
    positive_rows = [row for row in train_rows if row.get("label") == 1]
    labels = [int(row.get("label") == 1) for row in train_rows]
    if len(set(labels)) < 2:
        return {"model_type": "lightgbm_lambdamart_ltr_v1", "training": {"status": "single_class_labels"}, "feature_names": feature_names}
    group_sizes = [len(user_rows) for user_rows in grouped.values()]
    ranker = lgb.LGBMRanker(
        objective="lambdarank",
        n_estimators=int(config.get("n_estimators", 50)),
        learning_rate=float(config.get("learning_rate", 0.05)),
        num_leaves=int(config.get("num_leaves", 15)),
        min_data_in_leaf=int(config.get("min_data_in_leaf", 1)),
        verbose=-1,
        random_state=int(config.get("random_state", 42)),
    )
    matrix = [[float(row.get("features", {}).get(name, 0.0)) for name in feature_names] for row in train_rows]
    ranker.fit(matrix, labels, group=group_sizes)
    booster = ranker.booster_
    return {
        "model_type": "lightgbm_lambdamart_ltr_v1",
        "feature_names": feature_names,
        "booster_model": booster.model_to_string(),
        "feature_importance": {name: int(value) for name, value in zip(feature_names, booster.feature_importance(), strict=True) if int(value)},
        "training": {
            "status": "trained",
            "dependency": "lightgbm",
            "rows": len(train_rows),
            "users": len(grouped),
            "positive_rows": len(positive_rows),
            "positive_users": len({row["user_id"] for row in positive_rows}),
            "n_estimators": int(config.get("n_estimators", 50)),
            "learning_rate": float(config.get("learning_rate", 0.05)),
        },
    }


def save_ltr_model(model: dict[str, Any], path: str | Path) -> Path:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(model, ensure_ascii=False, indent=2), encoding="utf-8")
    return output_path


def load_ltr_model(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _group_rows_by_user(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(str(row["user_id"]), []).append(row)
    return grouped


def _update_weights(weights: dict[str, float], features: dict[str, float], scale: float) -> None:
    for name, value in features.items():
        if value:
            weights[name] = weights.get(name, 0.0) + scale * float(value)



def _sigmoid(value: float) -> float:
    if value >= 0:
        z = math.exp(-value)
        return 1.0 / (1.0 + z)
    z = math.exp(value)
    return z / (1.0 + z)



def _logistic_loss(label: float, probability: float) -> float:
    probability = min(max(probability, 1e-12), 1.0 - 1e-12)
    return -(label * math.log(probability) + (1.0 - label) * math.log(1.0 - probability))
