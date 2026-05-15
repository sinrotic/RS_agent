from __future__ import annotations

import hashlib
import math
import random
import re
import time
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

from rs_core.common.io import read_json, write_json, write_jsonl

DEFAULT_TEXT_FIELDS = ["title_clean", "main_category", "category", "description_text", "features_text", "item_text", "categories_flat"]
DEFAULT_SEQUENCE_KEYS = ["recent_positive_item_sequence", "recent_strong_positive_item_sequence"]


def train_two_tower_model(
    sequences: list[dict[str, Any]],
    item_records: list[dict[str, Any]],
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    train_config = _normalized_config(config or {})
    item_by_id = _item_records_by_id(item_records)
    item_ids = sorted(item_by_id)
    if not item_ids:
        raise ValueError("two-tower training requires at least one item record")

    rows = _training_rows(sequences, item_ids, train_config)
    if not rows:
        raise ValueError("two-tower training requires at least one user with positive item history")

    torch_module = _import_torch()
    if torch_module is not None:
        trained = _train_with_torch(torch_module, sequences, rows, item_by_id, item_ids, train_config)
    else:
        trained = _train_python_fallback(sequences, rows, item_by_id, item_ids, train_config)

    metrics = _training_metrics(rows, trained["user_embeddings"], trained["item_embeddings"], train_config, trained["training_backend"], trained.get("loss_history", []))
    return {
        "train_config": train_config,
        "model": _model_payload(train_config, item_by_id, metrics, trained["training_backend"], trained.get("model_parameters", {})),
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
        "negative_samples": int(config.get("negative_samples", 5)),
        "batch_size": int(config.get("batch_size", 512)),
        "seed": int(config.get("seed", 20260509)),
        "sequence_keys": [str(item) for item in config.get("sequence_keys", DEFAULT_SEQUENCE_KEYS)],
        "text_fields": [str(item) for item in config.get("text_fields", DEFAULT_TEXT_FIELDS)],
        "user_history_window": int(config.get("user_history_window", 20)),
        "recency_decay": float(config.get("recency_decay", 0.9)),
        "min_user_positives": int(config.get("min_user_positives", 1)),
    }


def _item_records_by_id(item_records: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for record in item_records:
        item_id = str(record.get("parent_asin") or record.get("item_id") or "")
        if item_id:
            rows[item_id] = dict(record) | {"parent_asin": item_id}
    return rows


def _training_rows(sequences: list[dict[str, Any]], item_ids: list[str], config: dict[str, Any]) -> list[dict[str, Any]]:
    item_set = set(item_ids)
    rows = []
    for sequence in sequences:
        user_id = str(sequence.get("user_id", ""))
        positives = [item for item in _sequence_items(sequence, config) if item in item_set]
        if user_id and len(positives) >= int(config["min_user_positives"]):
            rows.append({"user_id": user_id, "positive_items": positives})
    return rows


def _sequence_items(sequence: dict[str, Any], config: dict[str, Any]) -> list[str]:
    items: list[str] = []
    for key in config["sequence_keys"]:
        items.extend(str(item) for item in sequence.get(key, []) if item)
    if not items:
        items.extend(str(item) for item in sequence.get("recent_item_sequence", []) if item)
    deduped = list(dict.fromkeys(reversed(items)))
    return list(reversed(deduped[: int(config["user_history_window"])]))


def _train_with_torch(
    torch: Any,
    sequences: list[dict[str, Any]],
    rows: list[dict[str, Any]],
    item_by_id: dict[str, dict[str, Any]],
    item_ids: list[str],
    config: dict[str, Any],
) -> dict[str, Any]:
    started_at = time.perf_counter()
    torch.manual_seed(int(config["seed"]))
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    if device.type == "cuda":
        torch.cuda.manual_seed_all(int(config["seed"]))
        torch.cuda.reset_peak_memory_stats(device)
    rng = random.Random(int(config["seed"]))
    item_to_idx = {item_id: index for index, item_id in enumerate(item_ids)}
    token_df = _token_document_frequency(item_by_id, config)
    item_features = torch.tensor([_initial_item_vector(item_by_id[item_id], item_by_id, config, token_df) for item_id in item_ids], dtype=torch.float32, device=device)
    examples = _torch_examples(rows, item_to_idx)
    model = _build_torch_model(torch, config, item_features).to(device)
    optimizer = torch.optim.Adam(model.parameters(), lr=float(config["learning_rate"]))
    loss_history = []

    batch_size = max(1, int(config["batch_size"]))
    for _ in range(int(config["epochs"])):
        rng.shuffle(examples)
        losses = []
        for batch_start in range(0, len(examples), batch_size):
            batch = examples[batch_start: batch_start + batch_size]
            tensors = _torch_batch_tensors(torch, batch, len(item_ids), int(config["negative_samples"]), rng, device)
            if tensors is None:
                continue
            history_tensor, history_mask, candidate_tensor, target_tensor = tensors
            optimizer.zero_grad()
            logits = model(history_tensor, candidate_tensor, history_mask)
            loss = torch.nn.functional.cross_entropy(logits, target_tensor)
            loss.backward()
            optimizer.step()
            losses.append(float(loss.detach().cpu().item()))
        loss_history.append(round(sum(losses) / len(losses), 6) if losses else 0.0)

    item_embeddings = _torch_item_embeddings(torch, model, item_ids, device)
    user_embeddings = _torch_user_embeddings(torch, model, sequences, item_to_idx, config, device)
    elapsed_seconds = time.perf_counter() - started_at
    peak_memory_mb = round(torch.cuda.max_memory_allocated(device) / (1024 * 1024), 3) if device.type == "cuda" else 0.0
    return {
        "item_embeddings": item_embeddings,
        "user_embeddings": user_embeddings,
        "training_backend": {
            "name": "pytorch",
            "torch_available": True,
            "torch_version": str(torch.__version__),
            "device": str(device),
            "cuda_available": bool(torch.cuda.is_available()),
            "cuda_device_name": torch.cuda.get_device_name(0) if torch.cuda.is_available() else "",
            "model_class": model.__class__.__name__,
            "batch_training": True,
            "training_seconds": round(elapsed_seconds, 3),
            "peak_cuda_memory_mb": peak_memory_mb,
        },
        "loss_history": loss_history,
        "training_seconds": round(elapsed_seconds, 3),
        "peak_cuda_memory_mb": peak_memory_mb,
        "model_parameters": _torch_model_parameters(model),
    }


def _build_torch_model(torch: Any, config: dict[str, Any], item_features: Any) -> Any:
    if config["variant"] == "youtube_dnn":
        return _TorchYouTubeDNN(torch, item_features, int(config["embedding_dim"]), int(config["hidden_dim"]))
    if config["variant"] == "dssm":
        return _TorchDSSM(torch, item_features, int(config["embedding_dim"]), int(config["hidden_dim"]))
    raise ValueError(f"Unsupported two-tower variant: {config['variant']}")


def _torch_examples(rows: list[dict[str, Any]], item_to_idx: dict[str, int]) -> list[tuple[list[int], int, set[int]]]:
    examples = []
    for row in rows:
        positives = [item_to_idx[item] for item in row["positive_items"] if item in item_to_idx]
        positive_set = set(positives)
        for offset, positive_index in enumerate(positives):
            history = positives[:offset] or positives
            examples.append((history, positive_index, positive_set))
    return examples


def _negative_indices(item_count: int, positives: set[int], count: int, rng: random.Random) -> list[int]:
    candidates = [index for index in range(item_count) if index not in positives]
    if not candidates:
        return []
    return [candidates[rng.randrange(len(candidates))] for _ in range(max(0, count))]


def _torch_batch_tensors(
    torch: Any,
    batch: list[tuple[list[int], int, set[int]]],
    item_count: int,
    negative_samples: int,
    rng: random.Random,
    device: Any,
) -> tuple[Any, Any, Any, Any] | None:
    rows = []
    for history_indices, positive_index, positive_set in batch:
        negative_indices = _negative_indices(item_count, positive_set, negative_samples, rng)
        candidate_indices = [positive_index, *negative_indices]
        if history_indices and candidate_indices:
            rows.append((history_indices, candidate_indices))
    if not rows:
        return None
    max_history = max(len(history_indices) for history_indices, _ in rows)
    max_candidates = max(len(candidate_indices) for _, candidate_indices in rows)
    history_rows = []
    mask_rows = []
    candidate_rows = []
    for history_indices, candidate_indices in rows:
        history_padding = [history_indices[0]] * (max_history - len(history_indices))
        candidate_padding = [candidate_indices[-1]] * (max_candidates - len(candidate_indices))
        history_rows.append([*history_indices, *history_padding])
        mask_rows.append([1.0] * len(history_indices) + [0.0] * len(history_padding))
        candidate_rows.append([*candidate_indices, *candidate_padding])
    return (
        torch.tensor(history_rows, dtype=torch.long, device=device),
        torch.tensor(mask_rows, dtype=torch.float32, device=device),
        torch.tensor(candidate_rows, dtype=torch.long, device=device),
        torch.zeros(len(rows), dtype=torch.long, device=device),
    )


def _torch_item_embeddings(torch: Any, model: Any, item_ids: list[str], device: Any) -> dict[str, list[float]]:
    with torch.no_grad():
        indices = torch.arange(len(item_ids), dtype=torch.long, device=device)
        vectors = model.encode_items(indices).detach().cpu().tolist()
    return {item_id: normalize_vector(vector) for item_id, vector in zip(item_ids, vectors)}


def _torch_user_embeddings(torch: Any, model: Any, sequences: list[dict[str, Any]], item_to_idx: dict[str, int], config: dict[str, Any], device: Any) -> dict[str, list[float]]:
    rows = {}
    with torch.no_grad():
        for sequence in sequences:
            user_id = str(sequence.get("user_id", ""))
            history = [item_to_idx[item] for item in _sequence_items(sequence, config) if item in item_to_idx]
            if not user_id or not history:
                continue
            vector = model.encode_user(torch.tensor(history, dtype=torch.long, device=device)).detach().cpu().tolist()
            rows[user_id] = normalize_vector(vector)
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
    if config["variant"] == "youtube_dnn":
        _train_youtube_dnn_fallback(item_embeddings, rows, config, rng)
    elif config["variant"] == "dssm":
        _train_dssm_fallback(item_embeddings, rows, item_by_id, config, rng)
    else:
        raise ValueError(f"Unsupported two-tower variant: {config['variant']}")
    return {
        "item_embeddings": item_embeddings,
        "user_embeddings": _user_embeddings(sequences, item_embeddings, config),
        "training_backend": {"name": "python_fallback_vector_updates", "torch_available": False},
        "loss_history": [],
        "model_parameters": {},
    }


def _train_youtube_dnn_fallback(item_embeddings: dict[str, list[float]], rows: list[dict[str, Any]], config: dict[str, Any], rng: random.Random) -> None:
    item_ids = sorted(item_embeddings)
    for _ in range(int(config["epochs"])):
        shuffled = list(rows)
        rng.shuffle(shuffled)
        for row in shuffled:
            positives = row["positive_items"]
            context = _weighted_average([item_embeddings[item] for item in positives[:-1] or positives], float(config["recency_decay"]))
            for positive in positives:
                _update_pair(item_embeddings[positive], context, float(config["learning_rate"]))
                for negative in _negative_items(item_ids, set(positives), int(config["negative_samples"]), rng):
                    _update_pair(item_embeddings[negative], context, -float(config["learning_rate"]))


def _train_dssm_fallback(item_embeddings: dict[str, list[float]], rows: list[dict[str, Any]], item_by_id: dict[str, dict[str, Any]], config: dict[str, Any], rng: random.Random) -> None:
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
            negatives = list(hard_negative_pool)
            rng.shuffle(negatives)
            negatives = negatives[: int(config["negative_samples"])] or _negative_items(item_ids, set(positives), int(config["negative_samples"]), rng)
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
    sampled_scores = []
    for row in rows[: min(100, len(rows))]:
        user_vector = user_embeddings.get(row["user_id"])
        if not user_vector:
            continue
        sampled_scores.extend(dot_score(user_vector, item_embeddings[item]) for item in row["positive_items"] if item in item_embeddings)
    return {
        "variant": config["variant"],
        "training_backend": training_backend,
        "users_with_training_rows": len(rows),
        "positive_interactions": positives,
        "item_count": len(item_embeddings),
        "user_embedding_count": len(user_embeddings),
        "embedding_dim": int(config["embedding_dim"]),
        "epochs": int(config["epochs"]),
        "negative_samples": int(config["negative_samples"]),
        "batch_size": int(config["batch_size"]),
        "loss_history": loss_history,
        "training_seconds": training_backend.get("training_seconds", 0.0),
        "peak_cuda_memory_mb": training_backend.get("peak_cuda_memory_mb", 0.0),
        "sample_positive_score_avg": round(sum(sampled_scores) / len(sampled_scores), 6) if sampled_scores else 0.0,
    }


def _model_payload(config: dict[str, Any], item_by_id: dict[str, dict[str, Any]], metrics: dict[str, Any], training_backend: dict[str, Any], model_parameters: dict[str, Any]) -> dict[str, Any]:
    return {
        "model_type": f"{config['variant']}_two_tower_v1",
        "variant": config["variant"],
        "default_enabled": False,
        "embedding_dim": int(config["embedding_dim"]),
        "hidden_dim": int(config["hidden_dim"]),
        "source_name": config["source_name"],
        "text_fields": config["text_fields"],
        "sequence_keys": config["sequence_keys"],
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


def _negative_items(item_ids: list[str], positives: set[str], count: int, rng: random.Random) -> list[str]:
    candidates = [item for item in item_ids if item not in positives]
    if not candidates:
        return []
    return [candidates[rng.randrange(len(candidates))] for _ in range(max(0, count))]


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
    return Counter(token for item in item_by_id.values() for token in set(_tokens(item, config["text_fields"])))


def _initial_item_vector(record: dict[str, Any], item_by_id: dict[str, dict[str, Any]], config: dict[str, Any], token_df: Counter[str] | None = None) -> list[float]:
    token_df = token_df or _token_document_frequency(item_by_id, config)
    vector = [0.0] * int(config["embedding_dim"])
    for token, count in Counter(_tokens(record, config["text_fields"])).items():
        idf = math.log((1.0 + len(item_by_id)) / (1.0 + token_df[token])) + 1.0
        token_vector = _hash_vector(token, int(config["embedding_dim"]))
        for index, value in enumerate(token_vector):
            vector[index] += float(count) * idf * value
    return normalize_vector(vector)


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
