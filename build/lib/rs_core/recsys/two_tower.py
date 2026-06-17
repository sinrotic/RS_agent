from __future__ import annotations

import hashlib
import math
import random
import re
import time
from bisect import bisect_right
from collections import Counter
from contextlib import nullcontext
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Iterable

from rs_core.common.io import read_json, write_json, write_jsonl

DEFAULT_TEXT_FIELDS = ["title_clean", "main_category", "category", "description_text", "features_text", "item_text", "categories_flat"]
DEFAULT_SIDE_FEATURE_FIELDS: list[str] = []
DEFAULT_SEQUENCE_KEYS = ["recent_positive_item_sequence", "recent_strong_positive_item_sequence"]
ProgressCallback = Callable[[str, dict[str, Any]], None]


def train_two_tower_model(
    sequences: list[dict[str, Any]],
    item_records: list[dict[str, Any]],
    config: dict[str, Any] | None = None,
    progress_callback: ProgressCallback | None = None,
) -> dict[str, Any]:
    train_config = _normalized_config(config or {})
    _validate_config(train_config)
    item_by_id = _item_records_by_id(item_records)
    item_ids = sorted(item_by_id)
    if not item_ids:
        raise ValueError("two-tower training requires at least one item record")

    rows = _training_rows(sequences, item_ids, train_config, progress_callback)
    if not rows:
        raise ValueError("two-tower training requires at least one user with positive item history")
    example_age_stats = _attach_example_age_weights(rows, train_config)
    if progress_callback:
        progress_callback("example_age_weights_complete", example_age_stats)

    torch_module = _import_torch()
    if torch_module is not None:
        trained = _train_with_torch(torch_module, sequences, rows, item_by_id, item_ids, train_config, progress_callback)
    else:
        _validate_fallback_compatibility(train_config)
        trained = _train_python_fallback(sequences, rows, item_by_id, item_ids, train_config)
    trained["training_backend"]["example_age_weighting"] = example_age_stats | {"applied_to_loss": trained["training_backend"].get("name") == "pytorch"}

    metrics = _training_metrics(rows, trained["user_embeddings"], trained["item_embeddings"], train_config, trained["training_backend"], trained.get("loss_history", []))
    return {
        "train_config": train_config,
        "model": _model_payload(train_config, item_by_id, metrics, metrics["training_backend"], trained.get("model_parameters", {})),
        "item_embeddings": _embedding_rows(trained["item_embeddings"], item_by_id, "item_id"),
        "user_embeddings": _embedding_rows(trained["user_embeddings"], {}, "user_id"),
        "train_metrics": metrics,
    }


def save_two_tower_artifacts(result: dict[str, Any], output_dir: str | Path) -> dict[str, str]:
    target = Path(output_dir)
    model_path = target / "two_tower_model.json"
    train_config_path = target / "train_config.json"
    item_embeddings_path = target / "item_embeddings.jsonl"
    user_embeddings_path = target / "user_embeddings.jsonl"
    item_id_map_path = target / "item_id_map.json"
    user_id_map_path = target / "user_id_map.json"
    train_metrics_path = target / "train_metrics.json"
    recall_index_path = target / "two_tower_recall_index.jsonl"
    manifest_path = target / "artifact_manifest.json"

    write_json(train_config_path, result["train_config"])
    write_json(model_path, result["model"])
    write_jsonl(item_embeddings_path, result["item_embeddings"])
    write_jsonl(user_embeddings_path, result["user_embeddings"])
    write_json(item_id_map_path, _id_map(result["item_embeddings"], "item_id"))
    write_json(user_id_map_path, _id_map(result["user_embeddings"], "user_id"))
    write_json(train_metrics_path, result["train_metrics"])
    write_jsonl(recall_index_path, _recall_index_rows(result["item_embeddings"]))

    manifest = {
        "artifact_type": "two_tower_training_artifacts_v1",
        "variant": result["train_config"]["variant"],
        "source_name": result["train_config"].get("source_name", "two_tower"),
        "default_enabled": False,
        "contract": {
            "train_config": str(train_config_path),
            "model": str(model_path),
            "item_embeddings": str(item_embeddings_path),
            "user_embeddings": str(user_embeddings_path),
            "item_id_map": str(item_id_map_path),
            "user_id_map": str(user_id_map_path),
            "train_metrics": str(train_metrics_path),
            "recall_index": str(recall_index_path),
            "artifact_manifest": str(manifest_path),
        },
        "metrics": result["train_metrics"],
        "notes": [
            "Two-tower artifacts are side-path training outputs and must remain default-off until strict valid/test and LOPO gates pass.",
            "recall_index stores item vectors for downstream vector-index workers; it is not a semantic token fallback artifact.",
        ],
    }
    write_json(manifest_path, manifest)
    return manifest["contract"]


def load_two_tower_artifact_manifest(path: str | Path) -> dict[str, Any]:
    return read_json(path)


def dot_score(left: list[float], right: list[float]) -> float:
    return sum(a * b for a, b in zip(left, right))


def normalize_vector(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(float(value) * float(value) for value in vector))
    if not norm:
        return vector
    return [round(float(value) / norm, 8) for value in vector]


def _normalized_config(config: dict[str, Any]) -> dict[str, Any]:
    variant = str(config.get("variant", "dssm"))
    if variant == "youtube":
        variant = "youtube_dnn"
    return {
        "variant": variant,
        "source_name": str(config.get("source_name", f"two_tower_{variant}")),
        "backend": str(config.get("backend", "auto")),
        "embedding_dim": int(config.get("embedding_dim", 32)),
        "hidden_dim": int(config.get("hidden_dim", config.get("embedding_dim", 32))),
        "epochs": int(config.get("epochs", 3)),
        "learning_rate": float(config.get("learning_rate", 0.01)),
        "score_temperature": float(config.get("score_temperature", 1.0)),
        "negative_samples": int(config.get("negative_samples", 5)),
        "negative_sampling_power": float(config.get("negative_sampling_power", 0.75)),
        "negative_sampling_version": str(config.get("negative_sampling_version", "v1")),
        "unique_negatives_per_example": _bool_config(config.get("unique_negatives_per_example", False)),
        "dynamic_negative_sampling": _bool_config(config.get("dynamic_negative_sampling", False)),
        "dynamic_negative_sampling_mode": str(config.get("dynamic_negative_sampling_mode", "same_category_popular_tail_global_train_only")),
        "dynamic_same_category_popular_ratio": float(config.get("dynamic_same_category_popular_ratio", 0.5)),
        "dynamic_same_category_tail_ratio": float(config.get("dynamic_same_category_tail_ratio", 0.25)),
        "dynamic_global_random_ratio": float(config.get("dynamic_global_random_ratio", 0.25)),
        "dynamic_negative_resample_each_epoch": _bool_config(config.get("dynamic_negative_resample_each_epoch", True)),
        "use_explicit_negative_item_ids": _bool_config(config.get("use_explicit_negative_item_ids", False)),
        "explicit_negative_weight": float(config.get("explicit_negative_weight", 0.0)),
        "negative_dedup_max_attempts": int(config.get("negative_dedup_max_attempts", 100)),
        "sampled_softmax_candidate_mode": str(config.get("sampled_softmax_candidate_mode", "per_example")),
        "sampled_softmax_correction": str(config.get("sampled_softmax_correction", "none")),
        "sampled_softmax_logq_epsilon": float(config.get("sampled_softmax_logq_epsilon", 1e-12)),
        "batch_size": int(config.get("batch_size", 512)),
        "gradient_accumulation_steps": int(config.get("gradient_accumulation_steps", 1)),
        "mixed_precision": _bool_config(config.get("mixed_precision", False)),
        "max_samples_per_user": int(config.get("max_samples_per_user", 5)),
        "seed": int(config.get("seed", 20260509)),
        "sequence_keys": [str(item) for item in config.get("sequence_keys", DEFAULT_SEQUENCE_KEYS)],
        "text_fields": [str(item) for item in config.get("text_fields", DEFAULT_TEXT_FIELDS)],
        "side_feature_fields": [str(item) for item in config.get("side_feature_fields", DEFAULT_SIDE_FEATURE_FIELDS)],
        "user_history_window": int(config.get("user_history_window", 20)),
        "recency_decay": float(config.get("recency_decay", 0.9)),
        "torch_user_history_weighting": str(config.get("torch_user_history_weighting", "uniform")),
        "example_age_weighting": str(config.get("example_age_weighting", "none")),
        "example_age_half_life_days": float(config.get("example_age_half_life_days", 30.0)),
        "example_age_min_weight": float(config.get("example_age_min_weight", 0.1)),
        "min_user_positives": int(config.get("min_user_positives", 1)),
        "checkpoint_epochs": [int(item) for item in config.get("checkpoint_epochs", [])],
        "checkpoint_output_root": str(config.get("checkpoint_output_root", "")),
    }


def _validate_config(config: dict[str, Any]) -> None:
    candidate_mode = str(config.get("sampled_softmax_candidate_mode", "per_example"))
    if candidate_mode not in {"per_example", "batch_shared"}:
        raise ValueError("sampled_softmax_candidate_mode must be one of: per_example, batch_shared")
    correction = str(config.get("sampled_softmax_correction", "none"))
    if correction not in {"none", "logq"}:
        raise ValueError("sampled_softmax_correction must be one of: none, logq")
    score_temperature = float(config.get("score_temperature", 1.0))
    if not math.isfinite(score_temperature) or score_temperature <= 0.0:
        raise ValueError("score_temperature must be a finite positive number")
    dynamic_negative_sampling = bool(config.get("dynamic_negative_sampling"))
    if dynamic_negative_sampling:
        if str(config.get("dynamic_negative_sampling_mode")) != "same_category_popular_tail_global_train_only":
            raise ValueError("dynamic_negative_sampling_mode must be same_category_popular_tail_global_train_only")
        ratios = [
            float(config.get("dynamic_same_category_popular_ratio", 0.0)),
            float(config.get("dynamic_same_category_tail_ratio", 0.0)),
            float(config.get("dynamic_global_random_ratio", 0.0)),
        ]
        if any(not math.isfinite(value) or value < 0.0 for value in ratios) or sum(ratios) <= 0.0:
            raise ValueError("dynamic negative sampling ratios must be finite non-negative numbers with a positive sum")
        if not bool(config.get("dynamic_negative_resample_each_epoch", True)):
            raise ValueError("dynamic_negative_resample_each_epoch=false is not implemented; dynamic_negative_sampling currently always resamples during training")
        if candidate_mode != "per_example":
            raise ValueError("dynamic_negative_sampling requires sampled_softmax_candidate_mode=per_example")
        if correction == "logq":
            raise ValueError("dynamic_negative_sampling is not supported with sampled_softmax_correction=logq")
    if candidate_mode == "batch_shared" and bool(config.get("use_explicit_negative_item_ids")) and float(config.get("explicit_negative_weight", 0.0)) > 0.0:
        raise ValueError("sampled_softmax_candidate_mode=batch_shared is not supported with explicit negative mixtures")
    if correction == "logq" and bool(config.get("use_explicit_negative_item_ids")) and float(config.get("explicit_negative_weight", 0.0)) > 0.0:
        raise ValueError("sampled_softmax_correction=logq is not supported with explicit negative mixtures; disable explicit negatives or use sampled_softmax_correction=none")


def _validate_fallback_compatibility(config: dict[str, Any]) -> None:
    if str(config.get("sampled_softmax_candidate_mode", "per_example")) != "per_example":
        raise ValueError("sampled_softmax_candidate_mode=batch_shared requires the PyTorch backend")
    if str(config.get("sampled_softmax_correction", "none")) != "none":
        raise ValueError("sampled_softmax_correction requires the PyTorch backend")
    if float(config.get("score_temperature", 1.0)) != 1.0:
        raise ValueError("score_temperature requires the PyTorch backend")
    if bool(config.get("dynamic_negative_sampling")):
        raise ValueError("dynamic_negative_sampling requires the PyTorch backend")
    if str(config.get("example_age_weighting", "none")) != "none":
        raise ValueError("example_age_weighting requires the PyTorch backend")


def _bool_config(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _item_records_by_id(item_records: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for record in item_records:
        item_id = str(record.get("parent_asin") or record.get("item_id") or "")
        if item_id:
            rows[item_id] = dict(record) | {"parent_asin": item_id}
    return rows


def _training_rows(sequences: list[dict[str, Any]], item_ids: list[str], config: dict[str, Any], progress_callback: ProgressCallback | None = None) -> list[dict[str, Any]]:
    item_set = set(item_ids)
    rows = []
    for scanned, sequence in enumerate(sequences, start=1):
        user_id = str(sequence.get("user_id", ""))
        raw_events = _sequence_item_events(sequence, config)
        positive_events = [event for event in raw_events if event["item"] in item_set]
        positives = [event["item"] for event in positive_events]
        positive_timestamps = [event.get("timestamp_ms") for event in positive_events]
        positive_set = set(positives)
        explicit_negatives = [
            item
            for item in dict.fromkeys(str(item) for item in sequence.get("negative_item_ids", []) if item)
            if item in item_set and item not in positive_set
        ]
        if user_id and len(positives) >= int(config["min_user_positives"]):
            rows.append(
                {
                    "user_id": user_id,
                    "positive_items": positives,
                    "positive_timestamps_ms": positive_timestamps,
                    "explicit_negative_items": explicit_negatives,
                    "positive_item_missing_count": max(0, len(raw_events) - len(positives)),
                }
            )
        if progress_callback and scanned % 10000 == 0:
            progress_callback("training_rows", {"scanned_sequences": scanned, "kept_rows": len(rows), "item_count": len(item_ids)})
    if progress_callback:
        progress_callback("training_rows_complete", {"scanned_sequences": len(sequences), "kept_rows": len(rows), "item_count": len(item_ids)})
    return rows


def _sequence_items(sequence: dict[str, Any], config: dict[str, Any]) -> list[str]:
    return [event["item"] for event in _sequence_item_events(sequence, config)]


def _sequence_item_events(sequence: dict[str, Any], config: dict[str, Any]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for key in config["sequence_keys"]:
        events.extend(_sequence_events_for_key(sequence, key))
    if not events:
        events.extend(_sequence_events_for_key(sequence, "recent_item_sequence"))
    if any(event.get("timestamp_ms") is not None for event in events):
        events = sorted(
            enumerate(events),
            key=lambda indexed: (
                indexed[1].get("timestamp_ms") is None,
                indexed[1].get("timestamp_ms") if indexed[1].get("timestamp_ms") is not None else 0,
                indexed[0],
            ),
        )
        events = [event for _, event in events]
    deduped: dict[str, dict[str, Any]] = {}
    for event in reversed(events):
        deduped.setdefault(event["item"], event)
    return list(reversed(list(deduped.values())[: int(config["user_history_window"])]))


def _sequence_events_for_key(sequence: dict[str, Any], key: str) -> list[dict[str, Any]]:
    values = sequence.get(key, [])
    if not isinstance(values, list):
        return []
    timestamps = sequence.get(_timestamp_sequence_key(key), [])
    if not isinstance(timestamps, list):
        timestamps = []
    events = []
    for index, item in enumerate(values):
        item_id = str(item or "")
        if not item_id:
            continue
        timestamp_ms = _coerce_timestamp_ms(timestamps[index]) if index < len(timestamps) else None
        events.append({"item": item_id, "timestamp_ms": timestamp_ms})
    return events


def _timestamp_sequence_key(sequence_key: str) -> str:
    if sequence_key.endswith("_item_sequence"):
        return f"{sequence_key[:-len('_item_sequence')]}_timestamp_sequence"
    if sequence_key.endswith("_sequence"):
        return f"{sequence_key[:-len('_sequence')]}_timestamp_sequence"
    return f"{sequence_key}_timestamp_sequence"


def _coerce_timestamp_ms(value: Any) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        raw = float(value)
        if not math.isfinite(raw) or raw <= 0:
            return None
        return int(raw * 1000) if raw < 10_000_000_000 else int(raw)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return _coerce_timestamp_ms(float(text))
        except ValueError:
            pass
        try:
            normalized = text.replace("Z", "+00:00")
            parsed = datetime.fromisoformat(normalized)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=UTC)
            return int(parsed.timestamp() * 1000)
        except ValueError:
            return None
    return None


def _attach_example_age_weights(rows: list[dict[str, Any]], config: dict[str, Any]) -> dict[str, Any]:
    weighting = str(config.get("example_age_weighting", "none"))
    timestamps = [timestamp for row in rows for timestamp in row.get("positive_timestamps_ms", []) if timestamp]
    reference_timestamp_ms = max(timestamps) if timestamps else None
    missing_count = 0
    weights: list[float] = []
    for row in rows:
        row_weights = []
        for timestamp in row.get("positive_timestamps_ms", []):
            if weighting != "decay" or reference_timestamp_ms is None:
                weight = 1.0
            elif not timestamp:
                missing_count += 1
                weight = 1.0
            else:
                weight = _example_age_weight(timestamp, reference_timestamp_ms, config)
            row_weights.append(weight)
            weights.append(weight)
        row["positive_sample_weights"] = row_weights
    return {
        "weighting": weighting,
        "reference_timestamp_ms": reference_timestamp_ms,
        "positive_timestamp_count": len(timestamps),
        "missing_timestamp_count": missing_count,
        "weight_stats": _float_stats(weights),
    }


def _example_age_weight(timestamp_ms: int, reference_timestamp_ms: int, config: dict[str, Any]) -> float:
    half_life_days = max(1e-9, float(config.get("example_age_half_life_days", 30.0)))
    min_weight = min(1.0, max(0.0, float(config.get("example_age_min_weight", 0.1))))
    age_days = max(0.0, (reference_timestamp_ms - timestamp_ms) / 86_400_000.0)
    return round(max(min_weight, 0.5 ** (age_days / half_life_days)), 6)


def _negative_sampling_stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    explicit_counts = [len(row.get("explicit_negative_items", [])) for row in rows]
    return {
        "explicit_negative_candidate_count": sum(explicit_counts),
        "rows_with_explicit_negative_items": sum(1 for count in explicit_counts if count),
        "negative_examples": 0,
        "negative_samples_requested_total": 0,
        "negative_samples_effective_total": 0,
        "explicit_negative_used_count": 0,
        "dynamic_negative_used_count": 0,
        "dynamic_same_category_popular_used_count": 0,
        "dynamic_same_category_tail_used_count": 0,
        "dynamic_global_random_used_count": 0,
        "negative_duplicate_avoided_count": 0,
        "positive_negative_collision_blocked_count": 0,
        "sampled_softmax_corrected_examples": 0,
        "sampled_softmax_corrected_candidates": 0,
    }


def _negative_sampling_payload(config: dict[str, Any], item_frequency_count: int, stats: dict[str, Any] | None = None) -> dict[str, Any]:
    stats = stats or {}
    examples = max(1, int(stats.get("negative_examples", 0)))
    requested_total = int(stats.get("negative_samples_requested_total", 0))
    effective_total = int(stats.get("negative_samples_effective_total", 0))
    return {
        "strategy": "popularity_power",
        "version": str(config.get("negative_sampling_version", "v1")),
        "power": float(config["negative_sampling_power"]),
        "item_frequency_count": item_frequency_count,
        "negative_samples_requested": int(config["negative_samples"]),
        "unique_negatives_per_example": bool(config.get("unique_negatives_per_example")),
        "dynamic_negative_sampling": bool(config.get("dynamic_negative_sampling")),
        "dynamic_negative_sampling_mode": str(config.get("dynamic_negative_sampling_mode", "same_category_popular_tail_global_train_only")),
        "dynamic_negative_resample_each_epoch": bool(config.get("dynamic_negative_resample_each_epoch", True)),
        "dynamic_negative_ratios": {
            "same_category_popular": float(config.get("dynamic_same_category_popular_ratio", 0.5)),
            "same_category_tail": float(config.get("dynamic_same_category_tail_ratio", 0.25)),
            "global_random": float(config.get("dynamic_global_random_ratio", 0.25)),
        },
        "use_explicit_negative_item_ids": bool(config.get("use_explicit_negative_item_ids")),
        "explicit_negative_weight": float(config.get("explicit_negative_weight", 0.0)),
        "negative_dedup_max_attempts": int(config.get("negative_dedup_max_attempts", 100)),
        "sampled_softmax_candidate_mode": str(config.get("sampled_softmax_candidate_mode", "per_example")),
        "negative_samples_interpretation": "batch_level_shared" if str(config.get("sampled_softmax_candidate_mode", "per_example")) == "batch_shared" else "per_example",
        "sampled_softmax_correction": str(config.get("sampled_softmax_correction", "none")),
        "sampled_softmax_logq_epsilon": float(config.get("sampled_softmax_logq_epsilon", 1e-12)),
        "batch_shared_candidate_batches": int(stats.get("batch_shared_candidate_batches", 0)),
        "batch_shared_positive_candidates": int(stats.get("batch_shared_positive_candidates", 0)),
        "batch_shared_negative_candidates": int(stats.get("batch_shared_negative_candidates", 0)),
        "batch_shared_masked_positive_collisions": int(stats.get("batch_shared_masked_positive_collisions", 0)),
        "explicit_negative_candidate_count": int(stats.get("explicit_negative_candidate_count", 0)),
        "rows_with_explicit_negative_items": int(stats.get("rows_with_explicit_negative_items", 0)),
        "explicit_negative_candidates_ignored_by_dynamic_sampling": bool(config.get("dynamic_negative_sampling")) and int(stats.get("explicit_negative_candidate_count", 0)) > 0,
        "explicit_negative_used_count": int(stats.get("explicit_negative_used_count", 0)),
        "dynamic_negative_used_count": int(stats.get("dynamic_negative_used_count", 0)),
        "dynamic_negative_component_counts": {
            "same_category_popular": int(stats.get("dynamic_same_category_popular_used_count", 0)),
            "same_category_tail": int(stats.get("dynamic_same_category_tail_used_count", 0)),
            "global_random": int(stats.get("dynamic_global_random_used_count", 0)),
        },
        "negative_duplicate_avoided_count": int(stats.get("negative_duplicate_avoided_count", 0)),
        "positive_negative_collision_blocked_count": int(stats.get("positive_negative_collision_blocked_count", 0)),
        "sampled_softmax_corrected_examples": int(stats.get("sampled_softmax_corrected_examples", 0)),
        "sampled_softmax_corrected_candidates": int(stats.get("sampled_softmax_corrected_candidates", 0)),
        "negative_samples_effective_avg": round(effective_total / examples, 6) if requested_total else 0.0,
    }


def _history_weights(history_len: int, padding_len: int, config: dict[str, Any]) -> list[float]:
    if history_len <= 0:
        return [0.0] * max(0, padding_len)
    if str(config.get("torch_user_history_weighting", "uniform")) != "recency_decay":
        return [1.0] * history_len + [0.0] * max(0, padding_len)
    recency_decay = float(config.get("recency_decay", 0.9))
    weights = [recency_decay ** rank for rank in reversed(range(history_len))]
    return weights + [0.0] * max(0, padding_len)


def _adjust_sampled_softmax_logits(logits: Any, logq_tensor: Any, config: dict[str, Any]) -> Any:
    adjusted = logits / float(config.get("score_temperature", 1.0))
    if str(config.get("sampled_softmax_correction", "none")) == "logq":
        adjusted = adjusted - logq_tensor
    return adjusted


def _train_with_torch(
    torch: Any,
    sequences: list[dict[str, Any]],
    rows: list[dict[str, Any]],
    item_by_id: dict[str, dict[str, Any]],
    item_ids: list[str],
    config: dict[str, Any],
    progress_callback: ProgressCallback | None = None,
) -> dict[str, Any]:
    started_at = time.perf_counter()
    torch.manual_seed(int(config["seed"]))
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    if device.type == "cuda":
        torch.cuda.manual_seed_all(int(config["seed"]))
        torch.cuda.reset_peak_memory_stats(device)
    rng = random.Random(int(config["seed"]))
    item_to_idx = {item_id: index for index, item_id in enumerate(item_ids)}
    item_frequencies = _item_frequencies_by_index(rows, item_to_idx)
    negative_sampler = _negative_sampling_distribution(item_frequencies, len(item_ids), float(config["negative_sampling_power"]))
    dynamic_negative_sampler = _dynamic_negative_sampler(item_by_id, item_ids, item_frequencies) if bool(config.get("dynamic_negative_sampling")) else None
    negative_sampling_stats = _negative_sampling_stats(rows)
    if progress_callback:
        progress_callback("item_feature_token_df_start", {"item_count": len(item_ids)})
    token_df = _token_document_frequency(item_by_id, config)
    if progress_callback:
        progress_callback("item_feature_token_df_complete", {"item_count": len(item_ids), "token_count": len(token_df)})
    feature_rows = []
    for offset, item_id in enumerate(item_ids, start=1):
        feature_rows.append(_initial_item_vector(item_by_id[item_id], item_by_id, config, token_df))
        if progress_callback and offset % 10000 == 0:
            progress_callback("item_feature_rows", {"built_rows": offset, "item_count": len(item_ids)})
    if progress_callback:
        progress_callback("item_feature_rows_complete", {"built_rows": len(feature_rows), "item_count": len(item_ids)})
    item_features = torch.tensor(feature_rows, dtype=torch.float32, device=device)
    example_count = _torch_example_count(rows, item_to_idx, int(config["max_samples_per_user"]))
    if progress_callback:
        progress_callback("torch_examples_complete", {"example_count": example_count, "row_count": len(rows), "materialized": False, "max_samples_per_user": int(config["max_samples_per_user"])})
    model = _build_torch_model(torch, config, item_features).to(device)
    if progress_callback:
        progress_callback("model_constructed", {"model_class": model.__class__.__name__, "parameter_devices": sorted({str(parameter.device) for parameter in model.parameters()})})
    optimizer = torch.optim.Adam(model.parameters(), lr=float(config["learning_rate"]))
    loss_history = []

    batch_size = max(1, int(config["batch_size"]))
    gradient_accumulation_steps = max(1, int(config["gradient_accumulation_steps"]))
    torch_amp = getattr(torch, "amp", None)
    cuda_amp = getattr(torch.cuda, "amp", None)
    mixed_precision_requested = bool(config["mixed_precision"])
    mixed_precision_enabled = bool(mixed_precision_requested and device.type == "cuda" and (torch_amp is not None or cuda_amp is not None))
    if mixed_precision_enabled and torch_amp is not None:
        scaler = torch_amp.GradScaler("cuda", enabled=True)
        autocast_context = lambda: torch_amp.autocast("cuda")
    elif mixed_precision_enabled:
        scaler = cuda_amp.GradScaler(enabled=True)
        autocast_context = cuda_amp.autocast
    else:
        scaler = None
        autocast_context = nullcontext
    optimizer_steps = 0
    first_batch_logged = False
    checkpoint_epochs = {int(item) for item in config.get("checkpoint_epochs", []) if int(item) > 0}
    checkpoint_output_root = str(config.get("checkpoint_output_root") or "").strip()
    checkpoint_contracts: list[dict[str, Any]] = []
    for epoch in range(int(config["epochs"])):
        rng.shuffle(rows)
        loss_total = 0.0
        loss_count = 0
        accumulated_batches = 0
        optimizer.zero_grad(set_to_none=True)
        for batch_index, batch in enumerate(_torch_example_batches(rows, item_to_idx, batch_size, int(config["max_samples_per_user"])), start=1):
            tensors = _torch_batch_tensors(torch, batch, len(item_ids), config, rng, device, negative_sampler, negative_sampling_stats, dynamic_negative_sampler)
            if tensors is None:
                continue
            history_tensor, history_mask, candidate_tensor, target_tensor, sample_weight_tensor, logq_tensor, candidate_mask_tensor = tensors
            if progress_callback and not first_batch_logged:
                progress_callback(
                    "first_batch_devices",
                    {
                        "epoch": epoch,
                        "batch_size": len(batch),
                        "effective_batch_size": batch_size * gradient_accumulation_steps,
                        "gradient_accumulation_steps": gradient_accumulation_steps,
                        "mixed_precision_enabled": mixed_precision_enabled,
                        "requested_training_device": str(device),
                        "history_tensor_device": str(history_tensor.device),
                        "history_mask_device": str(history_mask.device),
                        "candidate_tensor_device": str(candidate_tensor.device),
                        "target_tensor_device": str(target_tensor.device),
                    },
                )
                first_batch_logged = True
            with autocast_context():
                logits = model(history_tensor, candidate_tensor, history_mask)
                logits = _adjust_sampled_softmax_logits(logits, logq_tensor, config)
                logits = logits.masked_fill(candidate_mask_tensor == 0, float("-inf"))
                per_example_loss = torch.nn.functional.cross_entropy(logits, target_tensor, reduction="none")
                loss = (per_example_loss * sample_weight_tensor).sum() / sample_weight_tensor.sum().clamp_min(1.0)
                scaled_loss = loss / gradient_accumulation_steps
            if scaler is not None:
                scaler.scale(scaled_loss).backward()
            else:
                scaled_loss.backward()
            accumulated_batches += 1
            if accumulated_batches % gradient_accumulation_steps == 0:
                if scaler is not None:
                    scaler.step(optimizer)
                    scaler.update()
                else:
                    optimizer.step()
                optimizer.zero_grad(set_to_none=True)
                optimizer_steps += 1
            loss_total += float(loss.detach().cpu().item())
            loss_count += 1
            if progress_callback and batch_index % 1000 == 0:
                progress_callback("torch_training_batches", {"epoch": epoch, "batch_index": batch_index, "batch_size": len(batch), "effective_batch_size": batch_size * gradient_accumulation_steps, "example_count": example_count})
        if accumulated_batches % gradient_accumulation_steps:
            if scaler is not None:
                scaler.step(optimizer)
                scaler.update()
            else:
                optimizer.step()
            optimizer.zero_grad(set_to_none=True)
            optimizer_steps += 1
        loss_history.append(round(loss_total / loss_count, 6) if loss_count else 0.0)
        completed_epoch = epoch + 1
        if checkpoint_output_root and completed_epoch in checkpoint_epochs:
            checkpoint_item_embeddings = _torch_item_embeddings(torch, model, item_ids, device)
            checkpoint_user_embeddings = _torch_user_embeddings(torch, model, sequences, item_to_idx, config, device, progress_callback)
            checkpoint_backend = {
                "name": "pytorch",
                "torch_available": True,
                "torch_version": str(torch.__version__),
                "device": str(device),
                "cuda_available": bool(torch.cuda.is_available()),
                "cuda_device_name": _cuda_device_name(torch, device),
                "model_class": model.__class__.__name__,
                "batch_training": True,
                "example_materialization": "streamed_batches",
                "training_examples": example_count,
                "gradient_accumulation_steps": gradient_accumulation_steps,
                "effective_batch_size": batch_size * gradient_accumulation_steps,
                "mixed_precision_requested": mixed_precision_requested,
                "mixed_precision_enabled": mixed_precision_enabled,
                "optimizer_steps": optimizer_steps,
                "max_samples_per_user": int(config["max_samples_per_user"]),
                "negative_sampling": _negative_sampling_payload(config, len(item_frequencies), negative_sampling_stats),
                "checkpoint_epoch": completed_epoch,
                "loss_history": list(loss_history),
            }
            checkpoint_metrics = _training_metrics(rows, checkpoint_user_embeddings, checkpoint_item_embeddings, config, checkpoint_backend, list(loss_history))
            checkpoint_dir = Path(checkpoint_output_root) / f"epoch_{completed_epoch}"
            checkpoint_dir.mkdir(parents=True, exist_ok=True)
            checkpoint_contract = save_two_tower_artifacts(
                {
                    "train_config": config | {"epochs": completed_epoch},
                    "model": _model_payload(config | {"epochs": completed_epoch}, item_by_id, checkpoint_metrics, checkpoint_metrics["training_backend"], _torch_model_parameters(model)),
                    "item_embeddings": _embedding_rows(checkpoint_item_embeddings, item_by_id, "item_id"),
                    "user_embeddings": _embedding_rows(checkpoint_user_embeddings, {}, "user_id"),
                    "train_metrics": checkpoint_metrics,
                },
                checkpoint_dir,
            )
            checkpoint_contracts.append({"epoch": completed_epoch, "output_dir": str(checkpoint_dir), "contract": checkpoint_contract})
            if progress_callback:
                progress_callback("checkpoint_saved", {"epoch": completed_epoch, "output_dir": str(checkpoint_dir)})

    item_embeddings = _torch_item_embeddings(torch, model, item_ids, device)
    user_embeddings = _torch_user_embeddings(torch, model, sequences, item_to_idx, config, device, progress_callback)
    elapsed_seconds = time.perf_counter() - started_at
    peak_memory_mb = round(torch.cuda.max_memory_allocated(device) / (1024 * 1024), 3) if device.type == "cuda" else 0.0
    cuda_device_name = _cuda_device_name(torch, device)
    return {
        "item_embeddings": item_embeddings,
        "user_embeddings": user_embeddings,
        "training_backend": {
            "name": "pytorch",
            "torch_available": True,
            "torch_version": str(torch.__version__),
            "device": str(device),
            "cuda_available": bool(torch.cuda.is_available()),
            "cuda_device_name": cuda_device_name,
            "model_class": model.__class__.__name__,
            "batch_training": True,
            "example_materialization": "streamed_batches",
            "training_examples": example_count,
            "gradient_accumulation_steps": gradient_accumulation_steps,
            "effective_batch_size": batch_size * gradient_accumulation_steps,
            "mixed_precision_requested": mixed_precision_requested,
            "mixed_precision_enabled": mixed_precision_enabled,
            "optimizer_steps": optimizer_steps,
            "max_samples_per_user": int(config["max_samples_per_user"]),
            "negative_sampling": _negative_sampling_payload(config, len(item_frequencies), negative_sampling_stats),
            "training_seconds": round(elapsed_seconds, 3),
            "peak_cuda_memory_mb": peak_memory_mb,
            "checkpoint_contracts": checkpoint_contracts,
        },
        "checkpoint_contracts": checkpoint_contracts,
        "loss_history": loss_history,
        "training_seconds": round(elapsed_seconds, 3),
        "peak_cuda_memory_mb": peak_memory_mb,
        "model_parameters": _torch_model_parameters(model),
    }


def _cuda_device_name(torch: Any, device: Any) -> str:
    if getattr(device, "type", "") != "cuda":
        return ""
    try:
        index = device.index if device.index is not None else torch.cuda.current_device()
        return str(torch.cuda.get_device_name(index))
    except (AssertionError, RuntimeError, ValueError):
        return ""



def _build_torch_model(torch: Any, config: dict[str, Any], item_features: Any) -> Any:
    if config["variant"] == "youtube_dnn":
        return _TorchYouTubeDNN(torch, item_features, int(config["embedding_dim"]), int(config["hidden_dim"]))
    if config["variant"] == "dssm":
        return _TorchDSSM(torch, item_features, int(config["embedding_dim"]), int(config["hidden_dim"]))
    raise ValueError(f"Unsupported two-tower variant: {config['variant']}")


def _torch_example_count(rows: list[dict[str, Any]], item_to_idx: dict[str, int], max_samples_per_user: int = 5) -> int:
    return sum(len(_torch_user_examples(row, item_to_idx, max_samples_per_user)) for row in rows)


def _torch_example_batches(
    rows: list[dict[str, Any]],
    item_to_idx: dict[str, int],
    batch_size: int,
    max_samples_per_user: int = 5,
) -> Iterable[list[tuple[list[int], int, set[int], list[int], float]]]:
    batch: list[tuple[list[int], int, set[int], list[int], float]] = []
    for row in rows:
        batch.extend(_torch_user_examples(row, item_to_idx, max_samples_per_user))
        while len(batch) >= batch_size:
            yield batch[:batch_size]
            batch = batch[batch_size:]
    if batch:
        yield batch


def _torch_user_examples(row: dict[str, Any], item_to_idx: dict[str, int], max_samples_per_user: int) -> list[tuple[list[int], int, set[int], list[int], float]]:
    positives = [item_to_idx[item] for item in row["positive_items"] if item in item_to_idx]
    if len(positives) < 2:
        return []
    positive_set = set(positives)
    explicit_negatives = [
        item_to_idx[item]
        for item in row.get("explicit_negative_items", [])
        if item in item_to_idx and item_to_idx[item] not in positive_set
    ]
    explicit_negatives = list(dict.fromkeys(explicit_negatives))
    sample_weights = row.get("positive_sample_weights", [])
    samples = [
        (positives[:offset], positive_index, positive_set, explicit_negatives, _sample_weight_at(sample_weights, offset))
        for offset, positive_index in enumerate(positives)
        if offset > 0
    ]
    limit = max(1, int(max_samples_per_user))
    return samples[-limit:]


def _sample_weight_at(weights: Any, offset: int) -> float:
    if isinstance(weights, list) and offset < len(weights):
        try:
            value = float(weights[offset])
            if math.isfinite(value) and value > 0:
                return value
        except (TypeError, ValueError):
            return 1.0
    return 1.0


def _item_frequencies_by_index(rows: list[dict[str, Any]], item_to_idx: dict[str, int]) -> Counter[int]:
    return Counter(item_to_idx[item] for row in rows for item in row["positive_items"] if item in item_to_idx)


def _negative_sampling_distribution(item_frequencies: Counter[int], item_count: int, power: float) -> tuple[list[float], float] | None:
    cumulative = []
    total = 0.0
    for index in range(item_count):
        weight = float(item_frequencies.get(index, 0)) ** power
        total += weight
        cumulative.append(total)
    if total <= 0.0:
        return None
    return cumulative, total


def _dynamic_negative_sampler(item_by_id: dict[str, dict[str, Any]], item_ids: list[str], item_frequencies: Counter[int]) -> dict[str, Any]:
    categories_by_index: dict[int, list[str]] = {}
    popular_by_category: dict[str, list[int]] = {}
    for index, item_id in enumerate(item_ids):
        categories = _item_category_tokens(item_by_id.get(item_id, {}))
        categories_by_index[index] = categories
        for category in categories:
            popular_by_category.setdefault(category, []).append(index)
    popular_order = list(range(len(item_ids)))
    popular_order.sort(key=lambda index: (-int(item_frequencies.get(index, 0)), index))
    rank_by_index = {index: rank for rank, index in enumerate(popular_order)}
    for category, candidates in popular_by_category.items():
        candidates.sort(key=lambda index: (rank_by_index.get(index, len(item_ids)), index))
    tail_by_category = {category: list(reversed(candidates)) for category, candidates in popular_by_category.items()}
    return {
        "categories_by_index": categories_by_index,
        "popular_by_category": popular_by_category,
        "tail_by_category": tail_by_category,
        "global_items": popular_order,
    }


def _item_category_tokens(record: dict[str, Any]) -> list[str]:
    tokens: list[str] = []
    for field in ("main_category", "category", "categories_flat", "categories_path", "source_categories"):
        value = record.get(field)
        if isinstance(value, list):
            values = value
        else:
            values = [value]
        for raw in values:
            if raw is None:
                continue
            for part in re.split(r"[>|/;,]", str(raw)):
                token = part.strip().lower()
                if token:
                    tokens.append(token)
    return list(dict.fromkeys(tokens))


def _dynamic_negative_indices(
    positive_index: int,
    positives: set[int],
    count: int,
    rng: random.Random,
    sampler: dict[str, Any],
    *,
    unique: bool = False,
    config: dict[str, Any] | None = None,
    stats: dict[str, Any] | None = None,
) -> list[int]:
    requested = max(0, count)
    if stats is not None:
        stats["negative_examples"] = int(stats.get("negative_examples", 0)) + 1
        stats["negative_samples_requested_total"] = int(stats.get("negative_samples_requested_total", 0)) + requested
    if requested <= 0:
        return []
    config = config or {}
    ratios = {
        "same_category_popular": max(0.0, float(config.get("dynamic_same_category_popular_ratio", 0.5))),
        "same_category_tail": max(0.0, float(config.get("dynamic_same_category_tail_ratio", 0.25))),
        "global_random": max(0.0, float(config.get("dynamic_global_random_ratio", 0.25))),
    }
    quotas = _dynamic_negative_quotas(requested, ratios)
    categories = sampler.get("categories_by_index", {}).get(positive_index, [])
    negatives: list[int] = []
    blocked = set(positives) | {positive_index}

    for component, pool_key in (("same_category_popular", "popular_by_category"), ("same_category_tail", "tail_by_category")):
        selected = _draw_from_category_pools(
            categories,
            sampler.get(pool_key, {}),
            quotas[component],
            rng,
            unique=unique,
            blocked=blocked,
            selected=set(negatives),
        )
        negatives.extend(selected)
        if stats is not None:
            stats[f"dynamic_{component}_used_count"] = int(stats.get(f"dynamic_{component}_used_count", 0)) + len(selected)

    remaining = requested - len(negatives)
    global_quota = max(remaining, quotas["global_random"])
    if global_quota > 0:
        global_selected = _draw_negative_candidates(sampler.get("global_items", []), global_quota, rng, unique=unique, blocked=blocked, selected=set(negatives))
        negatives.extend(global_selected[:remaining])
        if stats is not None:
            stats["dynamic_global_random_used_count"] = int(stats.get("dynamic_global_random_used_count", 0)) + len(global_selected[:remaining])
    if stats is not None:
        stats["dynamic_negative_used_count"] = int(stats.get("dynamic_negative_used_count", 0)) + len(negatives[:requested])
        stats["negative_samples_effective_total"] = int(stats.get("negative_samples_effective_total", 0)) + len(negatives[:requested])
    return negatives[:requested]


def _dynamic_negative_quotas(requested: int, ratios: dict[str, float]) -> dict[str, int]:
    total = sum(ratios.values()) or 1.0
    raw = {key: requested * value / total for key, value in ratios.items()}
    quotas = {key: int(math.floor(value)) for key, value in raw.items()}
    while sum(quotas.values()) < requested:
        key = max(raw, key=lambda item: (raw[item] - quotas[item], raw[item], item))
        quotas[key] += 1
    return quotas


def _draw_from_category_pools(
    categories: list[str],
    pools: dict[str, list[int]],
    limit: int,
    rng: random.Random,
    *,
    unique: bool,
    blocked: set[int],
    selected: set[int],
) -> list[int]:
    if limit <= 0 or not categories:
        return []
    chosen: list[int] = []
    seen = set(selected)
    category_order = list(categories)
    rng.shuffle(category_order)
    max_scan = max(limit * 20, limit + 10)
    for category in category_order:
        candidates = pools.get(category, [])
        if not candidates:
            continue
        start = rng.randrange(len(candidates))
        scanned = 0
        for offset in range(len(candidates)):
            index = candidates[(start + offset) % len(candidates)]
            scanned += 1
            if index in blocked or (unique and index in seen):
                if scanned >= max_scan:
                    break
                continue
            chosen.append(index)
            seen.add(index)
            if len(chosen) >= limit:
                return chosen
            if scanned >= max_scan:
                break
    return chosen


def _category_negative_candidates(categories: list[str], pools: dict[str, list[int]], blocked: set[int]) -> list[int]:
    candidates: list[int] = []
    for category in categories:
        candidates.extend(index for index in pools.get(category, []) if index not in blocked)
    return list(dict.fromkeys(candidates))


def _draw_negative_candidates(
    candidates: list[int],
    limit: int,
    rng: random.Random,
    *,
    unique: bool,
    blocked: set[int] | None = None,
    selected: set[int] | None = None,
) -> list[int]:
    if limit <= 0 or not candidates:
        return []
    blocked = blocked or set()
    selected = selected or set()
    chosen: list[int] = []
    seen = set(selected)
    max_attempts = max(limit * 20, limit + 10)
    attempts = 0
    while len(chosen) < limit and attempts < max_attempts:
        attempts += 1
        index = candidates[rng.randrange(len(candidates))]
        if index in blocked or (unique and index in seen):
            continue
        chosen.append(index)
        seen.add(index)
    if len(chosen) >= limit:
        return chosen
    for index in candidates:
        if index in blocked or (unique and index in seen):
            continue
        chosen.append(index)
        seen.add(index)
        if len(chosen) >= limit:
            break
    return chosen


def _negative_indices(
    item_count: int,
    positives: set[int],
    count: int,
    rng: random.Random,
    sampling_distribution: tuple[list[float], float] | None = None,
    *,
    explicit_negatives: list[int] | None = None,
    unique: bool = False,
    explicit_negative_weight: float = 0.0,
    max_attempts: int = 100,
    stats: dict[str, Any] | None = None,
) -> list[int]:
    requested = max(0, count)
    if stats is not None:
        stats["negative_examples"] = int(stats.get("negative_examples", 0)) + 1
        stats["negative_samples_requested_total"] = int(stats.get("negative_samples_requested_total", 0)) + requested
    if item_count <= len(positives):
        return []

    negatives: list[int] = []
    positive_set = set(positives)
    explicit_candidates: list[int] = []
    seen_explicit: set[int] = set()
    explicit_collision_count = 0
    explicit_duplicate_count = 0
    for index in explicit_negatives or []:
        if index in positive_set:
            explicit_collision_count += 1
            continue
        if index in seen_explicit:
            explicit_duplicate_count += 1
            continue
        seen_explicit.add(index)
        explicit_candidates.append(index)
    if stats is not None and explicit_negatives:
        stats["positive_negative_collision_blocked_count"] = int(stats.get("positive_negative_collision_blocked_count", 0)) + explicit_collision_count
        stats["negative_duplicate_avoided_count"] = int(stats.get("negative_duplicate_avoided_count", 0)) + explicit_duplicate_count

    if requested and explicit_candidates and explicit_negative_weight > 0:
        explicit_quota = min(requested, max(1, round(requested * min(1.0, max(0.0, explicit_negative_weight)))))
        shuffled_explicit = list(explicit_candidates)
        rng.shuffle(shuffled_explicit)
        for index in shuffled_explicit:
            if len(negatives) >= explicit_quota:
                break
            if unique and index in negatives:
                if stats is not None:
                    stats["negative_duplicate_avoided_count"] = int(stats.get("negative_duplicate_avoided_count", 0)) + 1
                continue
            negatives.append(index)
        if stats is not None:
            stats["explicit_negative_used_count"] = int(stats.get("explicit_negative_used_count", 0)) + len(negatives)

    while len(negatives) < requested:
        excluded = positive_set | (set(negatives) if unique else set())
        if item_count <= len(excluded):
            break
        index = _sample_negative_index(item_count, excluded, rng, sampling_distribution, max_attempts=max_attempts)
        if index is None:
            break
        negatives.append(index)
    if stats is not None:
        stats["negative_samples_effective_total"] = int(stats.get("negative_samples_effective_total", 0)) + len(negatives)
    return negatives


def _sampled_softmax_logq_values(candidate_indices: list[int], sampling_distribution: tuple[list[float], float] | None, item_count: int, epsilon: float, sample_count: int = 1) -> list[float]:
    draw_count = max(1, int(sample_count))
    probabilities = [_sampling_probability(index, sampling_distribution, item_count, epsilon) for index in candidate_indices]
    return [round(math.log(max(epsilon, draw_count * probability)), 8) for probability in probabilities]


def _sampling_probability(index: int, sampling_distribution: tuple[list[float], float] | None, item_count: int, epsilon: float = 1e-12) -> float:
    if item_count <= 0 or index < 0 or index >= item_count:
        return epsilon
    if sampling_distribution is None:
        return 1.0 / item_count
    cumulative, total = sampling_distribution
    if total <= 0.0 or index >= len(cumulative):
        return 1.0 / item_count
    previous = cumulative[index - 1] if index > 0 else 0.0
    weight = max(0.0, cumulative[index] - previous)
    if weight <= 0.0:
        return epsilon
    return max(epsilon, weight / total)


def _sample_negative_index(
    item_count: int,
    positives: set[int],
    rng: random.Random,
    sampling_distribution: tuple[list[float], float] | None,
    *,
    max_attempts: int = 100,
) -> int | None:
    if item_count <= len(positives):
        return None
    if sampling_distribution is not None:
        cumulative, total = sampling_distribution
        for _ in range(max(1, max_attempts)):
            index = bisect_right(cumulative, rng.random() * total)
            if index < item_count and index not in positives:
                return index
    for _ in range(max(1, max_attempts)):
        index = rng.randrange(item_count)
        if index not in positives:
            return index
    candidates = [index for index in range(item_count) if index not in positives]
    if not candidates:
        return None
    return candidates[rng.randrange(len(candidates))]


def _torch_batch_tensors(
    torch: Any,
    batch: list[tuple[list[int], int, set[int], list[int], float]],
    item_count: int,
    config: dict[str, Any],
    rng: random.Random,
    device: Any,
    sampling_distribution: tuple[list[float], float] | None = None,
    stats: dict[str, Any] | None = None,
    dynamic_negative_sampler: dict[str, Any] | None = None,
) -> tuple[Any, Any, Any, Any, Any, Any, Any] | None:
    if str(config.get("sampled_softmax_candidate_mode", "per_example")) == "batch_shared":
        return _torch_batch_shared_tensors(torch, batch, item_count, config, rng, device, sampling_distribution, stats)
    return _torch_per_example_batch_tensors(torch, batch, item_count, config, rng, device, sampling_distribution, stats, dynamic_negative_sampler)


def _torch_per_example_batch_tensors(
    torch: Any,
    batch: list[tuple[list[int], int, set[int], list[int], float]],
    item_count: int,
    config: dict[str, Any],
    rng: random.Random,
    device: Any,
    sampling_distribution: tuple[list[float], float] | None = None,
    stats: dict[str, Any] | None = None,
    dynamic_negative_sampler: dict[str, Any] | None = None,
) -> tuple[Any, Any, Any, Any, Any, Any, Any] | None:
    rows = []
    use_explicit = bool(config.get("use_explicit_negative_item_ids"))
    use_dynamic = bool(config.get("dynamic_negative_sampling")) and dynamic_negative_sampler is not None
    apply_logq = str(config.get("sampled_softmax_correction", "none")) == "logq"
    for history_indices, positive_index, positive_set, explicit_negative_indices, sample_weight in batch:
        if use_dynamic:
            negative_indices = _dynamic_negative_indices(
                positive_index,
                positive_set,
                int(config["negative_samples"]),
                rng,
                dynamic_negative_sampler or {},
                unique=bool(config.get("unique_negatives_per_example")),
                config=config,
                stats=stats,
            )
        else:
            negative_indices = _negative_indices(
                item_count,
                positive_set,
                int(config["negative_samples"]),
                rng,
                sampling_distribution,
                explicit_negatives=explicit_negative_indices if use_explicit else None,
                unique=bool(config.get("unique_negatives_per_example")),
                explicit_negative_weight=float(config.get("explicit_negative_weight", 0.0)) if use_explicit else 0.0,
                max_attempts=int(config.get("negative_dedup_max_attempts", 100)),
                stats=stats,
            )
        candidate_indices = [positive_index, *negative_indices]
        logq_values = _sampled_softmax_logq_values(
            candidate_indices,
            sampling_distribution,
            item_count,
            float(config.get("sampled_softmax_logq_epsilon", 1e-12)),
            sample_count=max(1, len(negative_indices)),
        ) if apply_logq else [0.0] * len(candidate_indices)
        if history_indices and candidate_indices:
            rows.append((history_indices, candidate_indices, 0, sample_weight, logq_values, [1.0] * len(candidate_indices)))
            if apply_logq and stats is not None:
                stats["sampled_softmax_corrected_examples"] = int(stats.get("sampled_softmax_corrected_examples", 0)) + 1
                stats["sampled_softmax_corrected_candidates"] = int(stats.get("sampled_softmax_corrected_candidates", 0)) + len(candidate_indices)
    return _torch_rows_to_tensors(torch, rows, config, device)


def _torch_batch_shared_tensors(
    torch: Any,
    batch: list[tuple[list[int], int, set[int], list[int], float]],
    item_count: int,
    config: dict[str, Any],
    rng: random.Random,
    device: Any,
    sampling_distribution: tuple[list[float], float] | None = None,
    stats: dict[str, Any] | None = None,
) -> tuple[Any, Any, Any, Any, Any, Any, Any] | None:
    examples = [example for example in batch if example[0]]
    if not examples:
        return None
    batch_positives = list(dict.fromkeys(positive_index for _, positive_index, _, _, _ in examples))
    blocked_positives = set().union(*(positive_set for _, _, positive_set, _, _ in examples))
    negative_indices = _negative_indices(
        item_count,
        blocked_positives,
        int(config["negative_samples"]),
        rng,
        sampling_distribution,
        unique=True,
        max_attempts=int(config.get("negative_dedup_max_attempts", 100)),
        stats=stats,
    )
    candidate_indices = [*batch_positives, *negative_indices]
    if not candidate_indices:
        return None
    candidate_position = {index: offset for offset, index in enumerate(candidate_indices)}
    apply_logq = str(config.get("sampled_softmax_correction", "none")) == "logq"
    logq_values = _sampled_softmax_logq_values(
        candidate_indices,
        sampling_distribution,
        item_count,
        float(config.get("sampled_softmax_logq_epsilon", 1e-12)),
        sample_count=max(1, len(negative_indices)),
    ) if apply_logq else [0.0] * len(candidate_indices)
    rows = []
    masked_collisions = 0
    for history_indices, positive_index, positive_set, _, sample_weight in examples:
        if positive_index not in candidate_position:
            continue
        candidate_mask = [1.0] * len(candidate_indices)
        for known_positive in positive_set - {positive_index}:
            position = candidate_position.get(known_positive)
            if position is not None:
                candidate_mask[position] = 0.0
                masked_collisions += 1
        candidate_mask[candidate_position[positive_index]] = 1.0
        rows.append((history_indices, candidate_indices, candidate_position[positive_index], sample_weight, logq_values, candidate_mask))
        if apply_logq and stats is not None:
            stats["sampled_softmax_corrected_examples"] = int(stats.get("sampled_softmax_corrected_examples", 0)) + 1
            stats["sampled_softmax_corrected_candidates"] = int(stats.get("sampled_softmax_corrected_candidates", 0)) + len(candidate_indices)
    if stats is not None and rows:
        stats["batch_shared_candidate_batches"] = int(stats.get("batch_shared_candidate_batches", 0)) + 1
        stats["batch_shared_positive_candidates"] = int(stats.get("batch_shared_positive_candidates", 0)) + len(batch_positives)
        stats["batch_shared_negative_candidates"] = int(stats.get("batch_shared_negative_candidates", 0)) + len(negative_indices)
        stats["batch_shared_masked_positive_collisions"] = int(stats.get("batch_shared_masked_positive_collisions", 0)) + masked_collisions
    return _torch_rows_to_tensors(torch, rows, config, device)


def _torch_rows_to_tensors(
    torch: Any,
    rows: list[tuple[list[int], list[int], int, float, list[float], list[float]]],
    config: dict[str, Any],
    device: Any,
) -> tuple[Any, Any, Any, Any, Any, Any, Any] | None:
    if not rows:
        return None
    max_history = max(len(history_indices) for history_indices, _, _, _, _, _ in rows)
    max_candidates = max(len(candidate_indices) for _, candidate_indices, _, _, _, _ in rows)
    history_rows = []
    mask_rows = []
    candidate_rows = []
    target_rows = []
    sample_weight_rows = []
    logq_rows = []
    candidate_mask_rows = []
    for history_indices, candidate_indices, target_index, sample_weight, logq_values, candidate_mask in rows:
        history_padding = [history_indices[0]] * (max_history - len(history_indices))
        candidate_padding = [candidate_indices[-1]] * (max_candidates - len(candidate_indices))
        logq_padding = [logq_values[-1]] * (max_candidates - len(logq_values))
        candidate_mask_padding = [0.0] * (max_candidates - len(candidate_mask))
        history_rows.append([*history_indices, *history_padding])
        mask_rows.append(_history_weights(len(history_indices), len(history_padding), config))
        candidate_rows.append([*candidate_indices, *candidate_padding])
        target_rows.append(int(target_index))
        sample_weight_rows.append(float(sample_weight))
        logq_rows.append([*logq_values, *logq_padding])
        candidate_mask_rows.append([*candidate_mask, *candidate_mask_padding])
    return (
        torch.tensor(history_rows, dtype=torch.long, device=device),
        torch.tensor(mask_rows, dtype=torch.float32, device=device),
        torch.tensor(candidate_rows, dtype=torch.long, device=device),
        torch.tensor(target_rows, dtype=torch.long, device=device),
        torch.tensor(sample_weight_rows, dtype=torch.float32, device=device),
        torch.tensor(logq_rows, dtype=torch.float32, device=device),
        torch.tensor(candidate_mask_rows, dtype=torch.float32, device=device),
    )


def _torch_item_embeddings(torch: Any, model: Any, item_ids: list[str], device: Any) -> dict[str, list[float]]:
    with torch.no_grad():
        indices = torch.arange(len(item_ids), dtype=torch.long, device=device)
        vectors = model.encode_items(indices).detach().cpu().tolist()
    return {item_id: normalize_vector(vector) for item_id, vector in zip(item_ids, vectors)}


def _torch_user_embeddings(
    torch: Any,
    model: Any,
    sequences: list[dict[str, Any]],
    item_to_idx: dict[str, int],
    config: dict[str, Any],
    device: Any,
    progress_callback: ProgressCallback | None = None,
) -> dict[str, list[float]]:
    rows = {}
    batch_size = max(1, int(config.get("user_embedding_batch_size", config["batch_size"])))
    pending: list[tuple[str, list[int]]] = []

    def flush() -> None:
        if not pending:
            return
        max_history = max(len(history) for _, history in pending)
        history_rows = []
        mask_rows = []
        user_ids = []
        for user_id, history in pending:
            padding = [history[0]] * (max_history - len(history))
            history_rows.append([*history, *padding])
            mask_rows.append(_history_weights(len(history), len(padding), config))
            user_ids.append(user_id)
        vectors = model.encode_user(
            torch.tensor(history_rows, dtype=torch.long, device=device),
            torch.tensor(mask_rows, dtype=torch.float32, device=device),
        ).detach().cpu().tolist()
        for user_id, vector in zip(user_ids, vectors):
            rows[user_id] = normalize_vector(vector)
        pending.clear()
        if progress_callback and len(rows) % (batch_size * 10) == 0:
            progress_callback("user_embedding_batches", {"user_embedding_count": len(rows), "batch_size": batch_size})

    with torch.no_grad():
        for sequence in sequences:
            user_id = str(sequence.get("user_id", ""))
            history = [item_to_idx[item] for item in _sequence_items(sequence, config) if item in item_to_idx]
            if not user_id or not history:
                continue
            pending.append((user_id, history))
            if len(pending) >= batch_size:
                flush()
        flush()
    if progress_callback:
        progress_callback("user_embeddings_complete", {"user_embedding_count": len(rows), "batch_size": batch_size})
    return rows


def _torch_model_parameters(model: Any) -> dict[str, Any]:
    payload = {}
    for name, tensor in model.state_dict().items():
        if "item_embedding" in name or "item_features" in name:
            payload[name] = {"shape": list(tensor.shape), "stored_in": "item_embeddings"}
            continue
        payload[name] = _round_nested(tensor.detach().cpu().tolist())
    return payload


def _round_nested(value: Any) -> Any:
    if isinstance(value, list):
        return [_round_nested(item) for item in value]
    return round(float(value), 8)


class _TorchDSSM:
    def __new__(cls, torch: Any, item_features: Any, embedding_dim: int, hidden_dim: int) -> Any:
        class DSSMModule(torch.nn.Module):
            def __init__(self) -> None:
                super().__init__()
                self.register_buffer("item_features", item_features)
                self.user_tower = torch.nn.Sequential(
                    torch.nn.Linear(embedding_dim, hidden_dim),
                    torch.nn.ReLU(),
                    torch.nn.Linear(hidden_dim, embedding_dim),
                )
                self.item_tower = torch.nn.Sequential(
                    torch.nn.Linear(embedding_dim, hidden_dim),
                    torch.nn.ReLU(),
                    torch.nn.Linear(hidden_dim, embedding_dim),
                )

            def encode_user(self, history_indices: Any, history_mask: Any | None = None) -> Any:
                features = self.item_features[history_indices]
                if history_mask is None:
                    history = features.mean(dim=0)
                    normalize_dim = 0
                else:
                    weights = history_mask.unsqueeze(-1)
                    history = (features * weights).sum(dim=1) / weights.sum(dim=1).clamp_min(1.0)
                    normalize_dim = -1
                return torch.nn.functional.normalize(self.user_tower(history) + history, dim=normalize_dim)

            def encode_items(self, item_indices: Any) -> Any:
                features = self.item_features[item_indices]
                return torch.nn.functional.normalize(self.item_tower(features) + features, dim=-1)

            def forward(self, history_indices: Any, candidate_indices: Any, history_mask: Any | None = None) -> Any:
                user_vector = self.encode_user(history_indices, history_mask)
                item_vectors = self.encode_items(candidate_indices)
                return (item_vectors * user_vector.unsqueeze(1)).sum(dim=-1)

        return DSSMModule()


class _TorchYouTubeDNN:
    def __new__(cls, torch: Any, item_features: Any, embedding_dim: int, hidden_dim: int) -> Any:
        class YouTubeDNNModule(torch.nn.Module):
            def __init__(self) -> None:
                super().__init__()
                self.item_embedding = torch.nn.Embedding.from_pretrained(item_features.clone(), freeze=False)
                self.user_tower = torch.nn.Sequential(
                    torch.nn.Linear(embedding_dim, hidden_dim),
                    torch.nn.ReLU(),
                    torch.nn.Linear(hidden_dim, embedding_dim),
                )

            def encode_user(self, history_indices: Any, history_mask: Any | None = None) -> Any:
                embeddings = self.item_embedding(history_indices)
                if history_mask is None:
                    history = embeddings.mean(dim=0)
                    normalize_dim = 0
                else:
                    weights = history_mask.unsqueeze(-1)
                    history = (embeddings * weights).sum(dim=1) / weights.sum(dim=1).clamp_min(1.0)
                    normalize_dim = -1
                return torch.nn.functional.normalize(self.user_tower(history) + history, dim=normalize_dim)

            def encode_items(self, item_indices: Any) -> Any:
                return torch.nn.functional.normalize(self.item_embedding(item_indices), dim=-1)

            def forward(self, history_indices: Any, candidate_indices: Any, history_mask: Any | None = None) -> Any:
                user_vector = self.encode_user(history_indices, history_mask)
                item_vectors = self.encode_items(candidate_indices)
                return (item_vectors * user_vector.unsqueeze(1)).sum(dim=-1)

        return YouTubeDNNModule()


def _train_python_fallback(
    sequences: list[dict[str, Any]],
    rows: list[dict[str, Any]],
    item_by_id: dict[str, dict[str, Any]],
    item_ids: list[str],
    config: dict[str, Any],
) -> dict[str, Any]:
    token_df = _token_document_frequency(item_by_id, config)
    item_embeddings = {item_id: _initial_item_vector(item_by_id[item_id], item_by_id, config, token_df) for item_id in item_ids}
    rng = random.Random(int(config["seed"]))
    item_frequencies = Counter(item for row in rows for item in row["positive_items"] if item in item_embeddings)
    negative_sampler = _negative_item_sampling_distribution(item_ids, item_frequencies, float(config["negative_sampling_power"]))
    negative_sampling_stats = _negative_sampling_stats(rows)
    if config["variant"] == "youtube_dnn":
        _train_youtube_dnn_fallback(item_embeddings, rows, config, rng, negative_sampler, negative_sampling_stats)
    elif config["variant"] == "dssm":
        _train_dssm_fallback(item_embeddings, rows, item_by_id, config, rng, negative_sampler, negative_sampling_stats)
    else:
        raise ValueError(f"Unsupported two-tower variant: {config['variant']}")
    return {
        "item_embeddings": item_embeddings,
        "user_embeddings": _user_embeddings(sequences, item_embeddings, config),
        "training_backend": {
            "name": "python_fallback_vector_updates",
            "torch_available": False,
            "gradient_accumulation_steps": max(1, int(config["gradient_accumulation_steps"])),
            "effective_batch_size": max(1, int(config["batch_size"])) * max(1, int(config["gradient_accumulation_steps"])),
            "mixed_precision_requested": bool(config["mixed_precision"]),
            "mixed_precision_enabled": False,
            "negative_sampling": _negative_sampling_payload(config, len(item_frequencies), negative_sampling_stats),
        },
        "loss_history": [],
        "model_parameters": {},
    }


def _train_youtube_dnn_fallback(
    item_embeddings: dict[str, list[float]],
    rows: list[dict[str, Any]],
    config: dict[str, Any],
    rng: random.Random,
    negative_sampler: tuple[list[str], list[float], float] | None = None,
    stats: dict[str, Any] | None = None,
) -> None:
    item_ids = sorted(item_embeddings)
    for _ in range(int(config["epochs"])):
        shuffled = list(rows)
        rng.shuffle(shuffled)
        for row in shuffled:
            positives = row["positive_items"]
            for history, positive, positive_set in _string_user_examples(positives, int(config["max_samples_per_user"])):
                context = _weighted_average([item_embeddings[item] for item in history], float(config["recency_decay"]))
                _update_pair(item_embeddings[positive], context, float(config["learning_rate"]))
                for negative in _negative_items(
                    item_ids,
                    positive_set,
                    int(config["negative_samples"]),
                    rng,
                    negative_sampler,
                    explicit_negatives=row.get("explicit_negative_items", []) if bool(config.get("use_explicit_negative_item_ids")) else None,
                    unique=bool(config.get("unique_negatives_per_example")),
                    explicit_negative_weight=float(config.get("explicit_negative_weight", 0.0)) if bool(config.get("use_explicit_negative_item_ids")) else 0.0,
                    max_attempts=int(config.get("negative_dedup_max_attempts", 100)),
                    stats=stats,
                ):
                    _update_pair(item_embeddings[negative], context, -float(config["learning_rate"]))


def _train_dssm_fallback(
    item_embeddings: dict[str, list[float]],
    rows: list[dict[str, Any]],
    item_by_id: dict[str, dict[str, Any]],
    config: dict[str, Any],
    rng: random.Random,
    negative_sampler: tuple[list[str], list[float], float] | None = None,
    stats: dict[str, Any] | None = None,
) -> None:
    item_ids = sorted(item_embeddings)
    category_items: dict[str, set[str]] = {}
    for item_id, record in item_by_id.items():
        category = str(record.get("main_category") or record.get("category") or "")
        if category:
            category_items.setdefault(category, set()).add(item_id)
    for _ in range(int(config["epochs"])):
        shuffled = list(rows)
        rng.shuffle(shuffled)
        for row in shuffled:
            positives = row["positive_items"]
            user_vector = _weighted_average([item_embeddings[item] for item in positives], float(config["recency_decay"]))
            hard_negative_pool = set()
            for positive in positives:
                category = str(item_by_id.get(positive, {}).get("main_category") or item_by_id.get(positive, {}).get("category") or "")
                hard_negative_pool.update(category_items.get(category, set()) - set(positives))
            if bool(config.get("use_explicit_negative_item_ids")) and float(config.get("explicit_negative_weight", 0.0)) > 0.0:
                negatives = _negative_items(
                    item_ids,
                    set(positives),
                    int(config["negative_samples"]),
                    rng,
                    negative_sampler,
                    explicit_negatives=row.get("explicit_negative_items", []),
                    unique=bool(config.get("unique_negatives_per_example")),
                    explicit_negative_weight=float(config.get("explicit_negative_weight", 0.0)),
                    max_attempts=int(config.get("negative_dedup_max_attempts", 100)),
                    stats=stats,
                )
            else:
                negatives = list(hard_negative_pool)
                rng.shuffle(negatives)
                negatives = negatives[: int(config["negative_samples"])] or _negative_items(
                    item_ids,
                    set(positives),
                    int(config["negative_samples"]),
                    rng,
                    negative_sampler,
                    unique=bool(config.get("unique_negatives_per_example")),
                    max_attempts=int(config.get("negative_dedup_max_attempts", 100)),
                    stats=stats,
                )
            for positive in positives:
                _update_pair(item_embeddings[positive], user_vector, float(config["learning_rate"]))
            for negative in negatives:
                _update_pair(item_embeddings[negative], user_vector, -float(config["learning_rate"]))


def _user_embeddings(sequences: list[dict[str, Any]], item_embeddings: dict[str, list[float]], config: dict[str, Any]) -> dict[str, list[float]]:
    rows = {}
    for sequence in sequences:
        user_id = str(sequence.get("user_id", ""))
        vectors = [item_embeddings[item] for item in _sequence_items(sequence, config) if item in item_embeddings]
        if user_id and vectors:
            rows[user_id] = normalize_vector(_weighted_average(vectors, float(config["recency_decay"])))
    return rows


def _training_metrics(
    rows: list[dict[str, Any]],
    user_embeddings: dict[str, list[float]],
    item_embeddings: dict[str, list[float]],
    config: dict[str, Any],
    training_backend: dict[str, Any],
    loss_history: list[float],
) -> dict[str, Any]:
    positives = sum(len(row["positive_items"]) for row in rows)
    history_lengths = [len(row["positive_items"]) for row in rows]
    text_fields_active = list(config["text_fields"])
    side_feature_fields_active = list(config["side_feature_fields"])
    example_counts = [len(_string_user_examples(row["positive_items"], int(config["max_samples_per_user"]))) for row in rows]
    positive_item_missing_count = sum(int(row.get("positive_item_missing_count", 0)) for row in rows)
    sampled_scores = []
    for row in rows[: min(100, len(rows))]:
        user_vector = user_embeddings.get(row["user_id"])
        if not user_vector:
            continue
        sampled_scores.extend(dot_score(user_vector, item_embeddings[item]) for item in row["positive_items"] if item in item_embeddings)
    return {
        "variant": config["variant"],
        "training_backend": training_backend | {"text_fields": text_fields_active, "side_feature_fields_active": side_feature_fields_active},
        "text_fields": text_fields_active,
        "side_feature_fields_active": side_feature_fields_active,
        "users_with_training_rows": len(rows),
        "positive_interactions": positives,
        "positive_item_missing_from_vocab_count": positive_item_missing_count,
        "history_length_stats": _count_stats(history_lengths),
        "examples_per_user_stats": _count_stats(example_counts),
        "item_count": len(item_embeddings),
        "user_embedding_count": len(user_embeddings),
        "embedding_dim": int(config["embedding_dim"]),
        "score_mode": "cosine",
        "embedding_normalization": "l2",
        "score_temperature": float(config.get("score_temperature", 1.0)),
        "logit_scale": round(1.0 / float(config.get("score_temperature", 1.0)), 8),
        "epochs": int(config["epochs"]),
        "negative_samples": int(config["negative_samples"]),
        "negative_sampling_power": float(config["negative_sampling_power"]),
        "negative_sampling": training_backend.get("negative_sampling", {}),
        "negative_sampling_version": str(config.get("negative_sampling_version", "v1")),
        "unique_negatives_per_example": bool(config.get("unique_negatives_per_example")),
        "use_explicit_negative_item_ids": bool(config.get("use_explicit_negative_item_ids")),
        "explicit_negative_weight": float(config.get("explicit_negative_weight", 0.0)),
        "sampled_softmax_candidate_mode": str(config.get("sampled_softmax_candidate_mode", "per_example")),
        "negative_samples_interpretation": "batch_level_shared" if str(config.get("sampled_softmax_candidate_mode", "per_example")) == "batch_shared" else "per_example",
        "sampled_softmax_correction": str(config.get("sampled_softmax_correction", "none")),
        "sampled_softmax_logq_epsilon": float(config.get("sampled_softmax_logq_epsilon", 1e-12)),
        "torch_user_history_weighting": str(config.get("torch_user_history_weighting", "uniform")),
        "recency_decay": float(config["recency_decay"]),
        "example_age_weighting": str(config.get("example_age_weighting", "none")),
        "example_age_half_life_days": float(config.get("example_age_half_life_days", 30.0)),
        "example_age_min_weight": float(config.get("example_age_min_weight", 0.1)),
        "example_age": training_backend.get("example_age_weighting", {}),
        "batch_size": int(config["batch_size"]),
        "gradient_accumulation_steps": max(1, int(config["gradient_accumulation_steps"])),
        "effective_batch_size": int(config["batch_size"]) * max(1, int(config["gradient_accumulation_steps"])),
        "mixed_precision": bool(config["mixed_precision"]),
        "max_samples_per_user": int(config["max_samples_per_user"]),
        "min_user_positives": int(config["min_user_positives"]),
        "loss_history": loss_history,
        "training_seconds": training_backend.get("training_seconds", 0.0),
        "peak_cuda_memory_mb": training_backend.get("peak_cuda_memory_mb", 0.0),
        "sample_positive_score_avg": round(sum(sampled_scores) / len(sampled_scores), 6) if sampled_scores else 0.0,
    }


def _count_stats(values: list[int]) -> dict[str, Any]:
    if not values:
        return {"count": 0, "min": 0, "p50": 0, "p90": 0, "max": 0, "avg": 0.0}
    ordered = sorted(values)
    return {
        "count": len(ordered),
        "min": ordered[0],
        "p50": _percentile(ordered, 0.5),
        "p90": _percentile(ordered, 0.9),
        "max": ordered[-1],
        "avg": round(sum(ordered) / len(ordered), 6),
    }


def _float_stats(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"count": 0, "min": 0.0, "p50": 0.0, "p90": 0.0, "max": 0.0, "avg": 0.0}
    ordered = sorted(float(value) for value in values)
    return {
        "count": len(ordered),
        "min": round(ordered[0], 6),
        "p50": round(_float_percentile(ordered, 0.5), 6),
        "p90": round(_float_percentile(ordered, 0.9), 6),
        "max": round(ordered[-1], 6),
        "avg": round(sum(ordered) / len(ordered), 6),
    }


def _float_percentile(ordered: list[float], q: float) -> float:
    if not ordered:
        return 0.0
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * q)))
    return ordered[index]


def _percentile(ordered: list[int], q: float) -> int:
    if not ordered:
        return 0
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * q)))
    return ordered[index]


def _model_payload(config: dict[str, Any], item_by_id: dict[str, dict[str, Any]], metrics: dict[str, Any], training_backend: dict[str, Any], model_parameters: dict[str, Any]) -> dict[str, Any]:
    return {
        "model_type": f"{config['variant']}_two_tower_v1",
        "variant": config["variant"],
        "default_enabled": False,
        "embedding_dim": int(config["embedding_dim"]),
        "hidden_dim": int(config["hidden_dim"]),
        "score_mode": "cosine",
        "embedding_normalization": "l2",
        "score_temperature": float(config.get("score_temperature", 1.0)),
        "logit_scale": round(1.0 / float(config.get("score_temperature", 1.0)), 8),
        "source_name": config["source_name"],
        "text_fields": config["text_fields"],
        "side_feature_fields": config["side_feature_fields"],
        "side_feature_fields_active": metrics.get("side_feature_fields_active", []),
        "sequence_keys": config["sequence_keys"],
        "max_samples_per_user": int(config["max_samples_per_user"]),
        "gradient_accumulation_steps": max(1, int(config["gradient_accumulation_steps"])),
        "effective_batch_size": int(config["batch_size"]) * max(1, int(config["gradient_accumulation_steps"])),
        "mixed_precision": bool(config["mixed_precision"]),
        "negative_sampling_power": float(config["negative_sampling_power"]),
        "negative_sampling_version": str(config.get("negative_sampling_version", "v1")),
        "unique_negatives_per_example": bool(config.get("unique_negatives_per_example")),
        "use_explicit_negative_item_ids": bool(config.get("use_explicit_negative_item_ids")),
        "explicit_negative_weight": float(config.get("explicit_negative_weight", 0.0)),
        "sampled_softmax_candidate_mode": str(config.get("sampled_softmax_candidate_mode", "per_example")),
        "negative_samples_interpretation": "batch_level_shared" if str(config.get("sampled_softmax_candidate_mode", "per_example")) == "batch_shared" else "per_example",
        "sampled_softmax_correction": str(config.get("sampled_softmax_correction", "none")),
        "sampled_softmax_logq_epsilon": float(config.get("sampled_softmax_logq_epsilon", 1e-12)),
        "torch_user_history_weighting": str(config.get("torch_user_history_weighting", "uniform")),
        "recency_decay": float(config["recency_decay"]),
        "example_age_weighting": str(config.get("example_age_weighting", "none")),
        "example_age_half_life_days": float(config.get("example_age_half_life_days", 30.0)),
        "example_age_min_weight": float(config.get("example_age_min_weight", 0.1)),
        "min_user_positives": int(config["min_user_positives"]),
        "item_count": len(item_by_id),
        "training_backend": training_backend,
        "model_parameters": model_parameters,
        "metrics_summary": metrics,
    }


def _embedding_rows(embeddings: dict[str, list[float]], item_by_id: dict[str, dict[str, Any]], id_field: str) -> list[dict[str, Any]]:
    rows = []
    for entity_id, vector in sorted(embeddings.items()):
        record = item_by_id.get(entity_id, {})
        rows.append({
            id_field: entity_id,
            "embedding": [round(value, 8) for value in normalize_vector(vector)],
            "embedding_norm": 1.0,
            "main_category": record.get("main_category", ""),
            "category": record.get("category", ""),
            "title_clean": record.get("title_clean", ""),
        })
    return rows


def _recall_index_rows(item_embeddings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "parent_asin": row["item_id"],
            "embedding": row["embedding"],
            "main_category": row.get("main_category", ""),
            "category": row.get("category", ""),
            "title_clean": row.get("title_clean", ""),
        }
        for row in item_embeddings
    ]


def _id_map(rows: list[dict[str, Any]], id_field: str) -> dict[str, Any]:
    return {"ids": [row[id_field] for row in rows], "count": len(rows)}


def _string_user_examples(positives: list[str], max_samples_per_user: int) -> list[tuple[list[str], str, set[str]]]:
    if len(positives) < 2:
        return []
    positive_set = set(positives)
    samples = [(positives[:offset], positive, positive_set) for offset, positive in enumerate(positives) if offset > 0]
    return samples[-max(1, int(max_samples_per_user)) :]


def _negative_item_sampling_distribution(item_ids: list[str], item_frequencies: Counter[str], power: float) -> tuple[list[str], list[float], float] | None:
    cumulative = []
    total = 0.0
    for item_id in item_ids:
        total += float(item_frequencies.get(item_id, 0)) ** power
        cumulative.append(total)
    if total <= 0.0:
        return None
    return item_ids, cumulative, total


def _negative_items(
    item_ids: list[str],
    positives: set[str],
    count: int,
    rng: random.Random,
    sampling_distribution: tuple[list[str], list[float], float] | None = None,
    *,
    explicit_negatives: list[str] | None = None,
    unique: bool = False,
    explicit_negative_weight: float = 0.0,
    max_attempts: int = 100,
    stats: dict[str, Any] | None = None,
) -> list[str]:
    requested = max(0, count)
    if stats is not None:
        stats["negative_examples"] = int(stats.get("negative_examples", 0)) + 1
        stats["negative_samples_requested_total"] = int(stats.get("negative_samples_requested_total", 0)) + requested
    candidates = [item for item in item_ids if item not in positives]
    if not candidates:
        return []

    rows: list[str] = []
    explicit_candidates: list[str] = []
    seen_explicit: set[str] = set()
    explicit_collision_count = 0
    explicit_duplicate_count = 0
    for item in explicit_negatives or []:
        if item in positives:
            explicit_collision_count += 1
            continue
        if item in seen_explicit:
            explicit_duplicate_count += 1
            continue
        seen_explicit.add(item)
        explicit_candidates.append(item)
    if stats is not None and explicit_negatives:
        stats["positive_negative_collision_blocked_count"] = int(stats.get("positive_negative_collision_blocked_count", 0)) + explicit_collision_count
        stats["negative_duplicate_avoided_count"] = int(stats.get("negative_duplicate_avoided_count", 0)) + explicit_duplicate_count

    if requested and explicit_candidates and explicit_negative_weight > 0:
        explicit_quota = min(requested, max(1, round(requested * min(1.0, max(0.0, explicit_negative_weight)))))
        shuffled_explicit = list(explicit_candidates)
        rng.shuffle(shuffled_explicit)
        for item in shuffled_explicit:
            if len(rows) >= explicit_quota:
                break
            if unique and item in rows:
                if stats is not None:
                    stats["negative_duplicate_avoided_count"] = int(stats.get("negative_duplicate_avoided_count", 0)) + 1
                continue
            rows.append(item)
        if stats is not None:
            stats["explicit_negative_used_count"] = int(stats.get("explicit_negative_used_count", 0)) + len(rows)

    while len(rows) < requested:
        excluded = positives | (set(rows) if unique else set())
        if len(excluded) >= len(item_ids):
            break
        if sampling_distribution is not None:
            weighted_items, cumulative, total = sampling_distribution
            for _attempt in range(max(1, max_attempts)):
                item = weighted_items[bisect_right(cumulative, rng.random() * total)]
                if item not in excluded:
                    rows.append(item)
                    break
            else:
                available = [item for item in candidates if item not in excluded]
                if not available:
                    break
                rows.append(available[rng.randrange(len(available))])
        else:
            available = [item for item in candidates if item not in excluded]
            if not available:
                break
            rows.append(available[rng.randrange(len(available))])
    if stats is not None:
        stats["negative_samples_effective_total"] = int(stats.get("negative_samples_effective_total", 0)) + len(rows)
    return rows


def _update_pair(item_vector: list[float], context_vector: list[float], learning_rate: float) -> None:
    for index, value in enumerate(context_vector):
        item_vector[index] += learning_rate * value
    item_vector[:] = normalize_vector(item_vector)


def _weighted_average(vectors: list[list[float]], recency_decay: float) -> list[float]:
    if not vectors:
        return []
    dim = len(vectors[0])
    output = [0.0] * dim
    total_weight = 0.0
    for rank, vector in enumerate(reversed(vectors)):
        weight = recency_decay**rank
        total_weight += weight
        for index, value in enumerate(vector):
            output[index] += value * weight
    if total_weight:
        output = [value / total_weight for value in output]
    return normalize_vector(output)


def _token_document_frequency(item_by_id: dict[str, dict[str, Any]], config: dict[str, Any]) -> Counter[str]:
    return Counter(token for item in item_by_id.values() for token in set(_item_feature_tokens(item, config)))


def _initial_item_vector(record: dict[str, Any], item_by_id: dict[str, dict[str, Any]], config: dict[str, Any], token_df: Counter[str] | None = None) -> list[float]:
    token_df = token_df or _token_document_frequency(item_by_id, config)
    vector = [0.0] * int(config["embedding_dim"])
    for token, count in Counter(_item_feature_tokens(record, config)).items():
        idf = math.log((1.0 + len(item_by_id)) / (1.0 + token_df[token])) + 1.0
        token_vector = _hash_vector(token, int(config["embedding_dim"]))
        for index, value in enumerate(token_vector):
            vector[index] += float(count) * idf * value
    return normalize_vector(vector)


def _item_feature_tokens(record: dict[str, Any], config: dict[str, Any]) -> list[str]:
    tokens = _tokens(record, list(config["text_fields"]))
    tokens.extend(_side_feature_tokens(record, list(config.get("side_feature_fields", []))))
    return tokens


def _side_feature_tokens(record: dict[str, Any], fields: list[str]) -> list[str]:
    tokens = []
    for field in fields:
        value = record.get(field, "")
        values = value if isinstance(value, list) else [value]
        for item in values:
            text = str(item).strip().lower()
            if text:
                tokens.append(f"{field.lower()}={text}")
    return tokens


def _tokens(record: dict[str, Any], fields: list[str]) -> list[str]:
    values = []
    for field in fields:
        value = record.get(field, "")
        if isinstance(value, list):
            values.extend(str(item) for item in value)
        else:
            values.append(str(value))
    return [token for token in re.findall(r"[a-z0-9]+", " ".join(values).lower()) if len(token) >= 2]


def _hash_vector(token: str, dim: int) -> list[float]:
    digest = hashlib.sha256(token.encode("utf-8")).digest()
    return [((digest[index % len(digest)] / 255.0) * 2.0 - 1.0) / math.sqrt(dim) for index in range(dim)]


def _import_torch() -> Any | None:
    try:
        import torch  # type: ignore
    except Exception:
        return None
    return torch
