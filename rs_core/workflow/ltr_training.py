from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from rs_core.common.config import load_config
from rs_core.common.io import read_jsonl, write_json, write_jsonl
from rs_core.online.recall.candidate_merge import load_category_candidates, load_itemcf_by_source, load_popular_candidates, load_semantic_index
from rs_core.offline.evaluation.ranking import heldout_positives
from rs_core.online.ranking.ltr import extract_ltr_features, save_ltr_model, train_pairwise_perceptron, train_pointwise_logistic, validate_ltr_feature_contract_gate, validate_ltr_leakage_gate
from rs_core.workflow.hybrid_demo import (
    _ensure_inputs,
    _itemcf_seed_items,
    _leave_one_positive_out_sequences,
    _load_item_category,
    _merge_nested,
    _required_paths,
    _resolve_path,
    recommend_for_user,
)


def train_ltr_ranker(
    config_path: str | Path,
    output_dir: str | Path | None = None,
    limit_users: int | None = None,
    config_overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    config = load_config(config_path)
    if config_overrides:
        config = _merge_nested(config, config_overrides)
    training_config = config.get("ltr_training", {})
    clean_dir = _resolve_path(config.get("clean_dir", "data/processed/amazon_2023_recall_clean_smoke_e2e"))
    views_dir = _resolve_path(config.get("views_dir", "data/processed/amazon_2023_recall_views_smoke_e2e"))
    output_path = _resolve_path(output_dir or training_config.get("output_dir", "outputs/training/ltr/ltr_training"))

    paths = _required_paths(clean_dir, views_dir)
    if config.get("semantic_enabled"):
        paths["semantic"] = views_dir / "semantic_recall_inputs.jsonl"
    _ensure_inputs(paths)

    train_sequences = read_jsonl(paths["sequences"])
    if limit_users is not None:
        train_sequences = train_sequences[:limit_users]
    evaluation_mode = str(config.get("evaluation_mode", "valid_test"))
    if evaluation_mode == "leave_one_positive_out":
        train_sequences, holdout, split_stats = _leave_one_positive_out_sequences(train_sequences)
        label_source = "leave_one_positive_out_train"
        training_split = "train"
    elif evaluation_mode == "valid_test":
        holdout = _load_valid_test_holdout(clean_dir)
        split_stats = {"valid_test_holdout_records": len(holdout)}
        label_source = "valid_test_holdout"
        training_split = "train"
    else:
        raise ValueError(f"Unsupported evaluation_mode: {evaluation_mode}")

    itemcf_seed_items = _itemcf_seed_items(train_sequences)
    popular = load_popular_candidates(paths["popular"], limit=int(config.get("popular_fallback_count", 50)))
    itemcf_weak = load_itemcf_by_source(paths["itemcf_weak"], "itemcf_weak", itemcf_seed_items)
    itemcf_strong = load_itemcf_by_source(paths["itemcf_strong"], "itemcf_strong", itemcf_seed_items)
    category_top = load_category_candidates(paths["category_top"])
    item_category = _load_item_category(paths["category_items"])
    semantic_index = load_semantic_index(paths["semantic"], config.get("semantic_text_fields")) if config.get("semantic_enabled") else {}
    candidate_config = _merge_nested(config, {"ltr_model": {"enabled": False}})

    positives = heldout_positives(holdout)
    rows = []
    users_with_positive_candidate = 0
    for sequence in train_sequences:
        user_id = sequence.get("user_id", "")
        targets = positives.get(user_id, set())
        if not targets:
            continue
        result = recommend_for_user(sequence, popular, itemcf_weak, itemcf_strong, category_top, item_category, candidate_config, semantic_index)
        user_rows = []
        for candidate in result.candidates:
            label = int(candidate.item_id in targets)
            user_rows.append(
                {
                    "user_id": user_id,
                    "item_id": candidate.item_id,
                    "label": label,
                    "sources": candidate.sources,
                    "source_scores": candidate.source_scores,
                    "features": extract_ltr_features(candidate, training_config.get("features", {})),
                }
            )
        if any(row["label"] == 1 for row in user_rows):
            users_with_positive_candidate += 1
            rows.extend(user_rows)

    feature_contract_gate = validate_ltr_feature_contract_gate(rows)
    leakage_gate = validate_ltr_leakage_gate(rows, label_source=label_source, training_split=training_split)
    model = _train_ltr_model(rows, training_config)
    model_path = output_path / "ltr_model.json"
    metrics_path = output_path / "ltr_train_metrics.json"
    rows_path = output_path / "ltr_candidate_rows.jsonl"
    save_ltr_model(model, model_path)
    metrics = _training_metrics(rows, model, evaluation_mode, split_stats, users_with_positive_candidate)
    metrics["feature_contract_gate"] = feature_contract_gate
    metrics["leakage_gate"] = leakage_gate
    write_json(metrics_path, metrics)
    if training_config.get("write_candidate_rows", False):
        max_rows = int(training_config.get("max_candidate_rows", 10000))
        write_jsonl(rows_path, rows[:max_rows])
    return {
        "model_path": str(model_path),
        "metrics_path": str(metrics_path),
        "candidate_rows_path": str(rows_path) if training_config.get("write_candidate_rows", False) else None,
        "model": model,
        "metrics": metrics,
    }


def _load_valid_test_holdout(clean_dir: Path) -> list[dict[str, Any]]:
    holdout = []
    for split_name in ("valid", "test"):
        path = clean_dir / f"canonical_interactions.{split_name}.jsonl"
        if path.exists():
            holdout.extend(read_jsonl(path))
    return holdout



def _train_ltr_model(rows: list[dict[str, Any]], training_config: dict[str, Any]) -> dict[str, Any]:
    model_type = str(training_config.get("model_type", "pairwise_perceptron"))
    train_config = training_config.get("train", {})
    if model_type in {"pairwise_perceptron", "pairwise_perceptron_ltr_v1"}:
        return train_pairwise_perceptron(rows, train_config)
    if model_type in {"pointwise_logistic", "pointwise_logistic_ltr_v1", "lr_pointwise"}:
        return train_pointwise_logistic(rows, train_config)
    raise ValueError(f"Unsupported LTR model_type: {model_type}")


def _training_metrics(rows: list[dict[str, Any]], model: dict[str, Any], evaluation_mode: str, split_stats: dict[str, int], users_with_positive_candidate: int) -> dict[str, Any]:
    labels = Counter(row["label"] for row in rows)
    return {
        "evaluation_mode": evaluation_mode,
        "model_type": model.get("model_type", "unknown"),
        "rows": len(rows),
        "positive_rows": labels.get(1, 0),
        "negative_rows": labels.get(0, 0),
        "users_with_positive_candidate": users_with_positive_candidate,
        "feature_count": len(model.get("feature_names", [])),
        "nonzero_weight_count": len(model.get("weights", {})),
        "training": model.get("training", {}),
        **split_stats,
    }
