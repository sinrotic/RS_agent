from __future__ import annotations

import hashlib
import json
import random
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import torch
from torch import nn
from torch.nn import functional as F

from rs_core.common.config import load_config
from rs_core.common.io import read_jsonl, write_json, write_jsonl
from rs_core.workflow.hybrid_demo import ROOT, _ensure_inputs, _leave_one_positive_out_sequences, _merge_nested, _required_paths, _resolve_path


SCHEMA_VERSION = "graph_walk_seed_pairs_v1"
SOURCE_NAME = "graph_walk_seed"
ALGORITHM = "deepwalk"
PHASE = "1.19"


class _SkipGramNegativeSampling(nn.Module):
    def __init__(self, item_count: int, embedding_dim: int) -> None:
        super().__init__()
        self.input_embeddings = nn.Embedding(item_count, embedding_dim)
        self.output_embeddings = nn.Embedding(item_count, embedding_dim)
        nn.init.xavier_uniform_(self.input_embeddings.weight)
        nn.init.zeros_(self.output_embeddings.weight)

    def forward(self, centers: torch.Tensor, contexts: torch.Tensor, negatives: torch.Tensor) -> torch.Tensor:
        center_vectors = self.input_embeddings(centers)
        context_vectors = self.output_embeddings(contexts)
        negative_vectors = self.output_embeddings(negatives)
        positive_loss = F.logsigmoid((center_vectors * context_vectors).sum(dim=1))
        negative_loss = F.logsigmoid(-(negative_vectors * center_vectors.unsqueeze(1)).sum(dim=2)).sum(dim=1)
        return -(positive_loss + negative_loss).mean()


def train_graph_walk_seed(
    config_path: str | Path,
    output_dir: str | Path | None = None,
    limit_users: int | None = None,
    config_overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    resolved_config_path = _resolve_path(config_path)
    config = load_config(resolved_config_path)
    if config_overrides:
        config = _merge_nested(config, config_overrides)
    training_config = _graph_walk_training_config(config, output_dir)

    if training_config["algorithm"] != ALGORITHM:
        raise ValueError("graph_walk_training.algorithm must be deepwalk for Phase 1.19")
    seed = int(training_config["seed"])
    _seed_everything(seed)

    clean_dir = _resolve_path(config.get("clean_dir", "data/processed/amazon_2023_recall_clean_smoke_e2e"))
    views_dir = _resolve_path(config.get("views_dir", "data/processed/amazon_2023_recall_views_smoke_e2e"))
    paths = _required_paths(clean_dir, views_dir)
    _ensure_inputs({"sequences": paths["sequences"]})

    sequences = read_jsonl(paths["sequences"])
    if limit_users is not None:
        if limit_users < 1:
            raise ValueError("limit_users must be >= 1")
        sequences = sequences[:limit_users]
    if str(config.get("evaluation_mode", "valid_test")) == "leave_one_positive_out":
        sequences, _, _ = _leave_one_positive_out_sequences(sequences)
    if not sequences:
        raise ValueError("empty graph_walk training sequence input")

    graph = build_item_graph(sequences)
    item_ids = sorted(graph)
    if len(item_ids) < 2:
        raise ValueError("graph_walk training requires at least two connected items")

    walks = generate_random_walks(
        graph,
        seed=seed,
        walk_length=int(training_config["walk_length"]),
        walks_per_node=int(training_config["walks_per_node"]),
    )
    pairs = skipgram_pairs(walks, window_size=int(training_config["window_size"]))
    if not pairs:
        raise ValueError("graph_walk random walks produced no skip-gram pairs")

    id_to_index = {item_id: index for index, item_id in enumerate(item_ids)}
    indexed_pairs = [(id_to_index[center], id_to_index[context]) for center, context in pairs]
    embeddings = train_skipgram_embeddings(
        indexed_pairs,
        graph,
        item_ids,
        embedding_dim=int(training_config["embedding_dim"]),
        epochs=int(training_config["epochs"]),
        negative_samples=int(training_config["negative_samples"]),
        learning_rate=float(training_config["learning_rate"]),
        batch_size=int(training_config["batch_size"]),
        seed=seed,
    )

    sidecar_path = _resolve_path(training_config["sidecar_path"])
    manifest_path = _resolve_path(training_config["manifest_path"])
    embeddings_path = _resolve_path(training_config["embeddings_path"])
    _validate_output_paths(paths["sequences"], sidecar_path, manifest_path, embeddings_path)
    _cleanup_outputs(sidecar_path, manifest_path, embeddings_path)

    embedding_rows = [{"item_id": item_id, "embedding": [round(float(value), 8) for value in embeddings[index].tolist()]} for index, item_id in enumerate(item_ids)]
    write_jsonl(embeddings_path, embedding_rows)
    sidecar_rows = graph_walk_pair_rows(
        item_ids,
        embeddings,
        neighbor_k=int(training_config["neighbor_k"]),
        chunk_size=int(training_config.get("similarity_chunk_size", 256)),
    )
    write_jsonl(sidecar_path, sidecar_rows)

    manifest = {
        "phase": PHASE,
        "source": SOURCE_NAME,
        "schema_version": SCHEMA_VERSION,
        "algorithm": ALGORITHM,
        "created_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "seed": seed,
        "walk_params": {
            "walk_length": int(training_config["walk_length"]),
            "walks_per_node": int(training_config["walks_per_node"]),
            "window_size": int(training_config["window_size"]),
        },
        "embedding_dim": int(training_config["embedding_dim"]),
        "epochs": int(training_config["epochs"]),
        "negative_samples": int(training_config["negative_samples"]),
        "neighbor_k": int(training_config["neighbor_k"]),
        "similarity": "cosine",
        "deterministic_sort": "score_desc_dst_item_asc",
        "device": "cuda" if torch.cuda.is_available() else "cpu",
        "input_path": str(paths["sequences"]),
        "config_path": str(resolved_config_path),
        "embeddings_path": str(embeddings_path),
        "sidecar_path": str(sidecar_path),
        "item_count": len(item_ids),
        "edge_count": sum(len(neighbors) for neighbors in graph.values()) // 2,
        "walk_count": len(walks),
        "positive_pair_count": len(indexed_pairs),
        "input_hash": _sha256_file(paths["sequences"]),
        "config_hash": _sha256_json(config),
        "embeddings_hash": _sha256_file(embeddings_path),
        "sidecar_hash": _sha256_file(sidecar_path),
    }
    write_json(manifest_path, manifest)
    return {
        "sidecar_path": str(sidecar_path),
        "manifest_path": str(manifest_path),
        "embeddings_path": str(embeddings_path),
        "manifest": manifest,
    }


def build_item_graph(sequences: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    graph: dict[str, dict[str, float]] = defaultdict(dict)
    for sequence in sequences:
        for field in ("recent_positive_item_sequence", "recent_strong_positive_item_sequence"):
            items = [str(item) for item in sequence.get(field, []) if item]
            for left, right in zip(items, items[1:]):
                if left == right:
                    continue
                graph[left][right] = graph[left].get(right, 0.0) + 1.0
                graph[right][left] = graph[right].get(left, 0.0) + 1.0
    return {item_id: dict(sorted(neighbors.items())) for item_id, neighbors in graph.items() if neighbors}


def generate_random_walks(graph: dict[str, dict[str, float]], seed: int, walk_length: int, walks_per_node: int) -> list[list[str]]:
    if walk_length < 2:
        raise ValueError("walk_length must be >= 2")
    if walks_per_node < 1:
        raise ValueError("walks_per_node must be >= 1")
    rng = random.Random(seed)
    nodes = sorted(graph)
    walks = []
    for _ in range(walks_per_node):
        round_nodes = list(nodes)
        rng.shuffle(round_nodes)
        for node in round_nodes:
            walk = [node]
            while len(walk) < walk_length:
                neighbors = graph.get(walk[-1], {})
                if not neighbors:
                    break
                walk.append(_weighted_choice(neighbors, rng))
            if len(walk) > 1:
                walks.append(walk)
    return walks


def skipgram_pairs(walks: list[list[str]], window_size: int) -> list[tuple[str, str]]:
    if window_size < 1:
        raise ValueError("window_size must be >= 1")
    pairs = []
    for walk in walks:
        for center_index, center in enumerate(walk):
            start = max(0, center_index - window_size)
            end = min(len(walk), center_index + window_size + 1)
            for context_index in range(start, end):
                if context_index != center_index:
                    pairs.append((center, walk[context_index]))
    return pairs


def train_skipgram_embeddings(
    indexed_pairs: list[tuple[int, int]],
    graph: dict[str, dict[str, float]],
    item_ids: list[str],
    embedding_dim: int,
    epochs: int,
    negative_samples: int,
    learning_rate: float,
    batch_size: int,
    seed: int,
) -> torch.Tensor:
    _validate_training_params(embedding_dim, epochs, negative_samples, learning_rate, batch_size)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = _SkipGramNegativeSampling(len(item_ids), embedding_dim).to(device)
    optimizer = torch.optim.Adam(model.parameters(), lr=learning_rate)
    centers = torch.tensor([pair[0] for pair in indexed_pairs], dtype=torch.long, device=device)
    contexts = torch.tensor([pair[1] for pair in indexed_pairs], dtype=torch.long, device=device)
    sampling_weights = torch.tensor([sum(graph[item_id].values()) ** 0.75 for item_id in item_ids], dtype=torch.float32, device=device)
    generator = torch.Generator(device=device).manual_seed(seed)

    model.train()
    for _ in range(epochs):
        order = torch.randperm(centers.numel(), generator=generator, device=device)
        for start in range(0, order.numel(), batch_size):
            batch = order[start : start + batch_size]
            negative_items = torch.multinomial(
                sampling_weights,
                num_samples=batch.numel() * negative_samples,
                replacement=True,
                generator=generator,
            ).view(batch.numel(), negative_samples)
            optimizer.zero_grad(set_to_none=True)
            loss = model(centers[batch], contexts[batch], negative_items)
            loss.backward()
            optimizer.step()

    model.eval()
    with torch.no_grad():
        return F.normalize(model.input_embeddings.weight.detach().cpu(), dim=1)


def graph_walk_pair_rows(item_ids: list[str], embeddings: torch.Tensor, neighbor_k: int, chunk_size: int = 256) -> list[dict[str, Any]]:
    if neighbor_k < 1:
        raise ValueError("neighbor_k must be >= 1")
    if chunk_size < 1:
        raise ValueError("chunk_size must be >= 1")
    rows = []
    normalized = F.normalize(embeddings, dim=1)
    k = min(neighbor_k, max(0, len(item_ids) - 1))
    for start in range(0, len(item_ids), chunk_size):
        end = min(len(item_ids), start + chunk_size)
        scores = normalized[start:end] @ normalized.T
        for local_index, score_row in enumerate(scores):
            source_index = start + local_index
            source_item = item_ids[source_index]
            score_row[source_index] = -float("inf")
            values, indices = torch.topk(score_row, k=k)
            scored = [
                (round(float(score), 6), item_ids[int(index)])
                for score, index in zip(values.tolist(), indices.tolist())
                if int(index) != source_index
            ]
            for rank, (score, target_item) in enumerate(sorted(scored, key=lambda item: (-item[0], item[1]))[:neighbor_k], start=1):
                rows.append({
                    "src_item": source_item,
                    "dst_item": target_item,
                    "score": score,
                    "rank": rank,
                    "source": SOURCE_NAME,
                    "algorithm": ALGORITHM,
                })
    return rows


def _graph_walk_training_config(config: dict[str, Any], output_dir: str | Path | None) -> dict[str, Any]:
    training_config = dict(config.get("graph_walk_training", {}) or {})
    output_path = _resolve_path(output_dir or training_config.get("output_dir", "outputs/graph_walk_training/deepwalk"))
    training_config.setdefault("algorithm", ALGORITHM)
    training_config.setdefault("seed", 20260511)
    training_config.setdefault("walk_length", 20)
    training_config.setdefault("walks_per_node", 10)
    training_config.setdefault("window_size", 5)
    training_config.setdefault("embedding_dim", 64)
    training_config.setdefault("epochs", 3)
    training_config.setdefault("negative_samples", 5)
    training_config.setdefault("learning_rate", 0.002)
    training_config.setdefault("batch_size", 4096)
    training_config.setdefault("neighbor_k", 50)
    training_config.setdefault("similarity_chunk_size", 256)
    training_config.setdefault("sidecar_path", str(output_path / "graph_walk_seed_neighbors.jsonl"))
    training_config.setdefault("manifest_path", str(output_path / "graph_walk_seed_manifest.json"))
    training_config.setdefault("embeddings_path", str(output_path / "graph_walk_item_embeddings.jsonl"))
    return training_config


def _validate_training_params(embedding_dim: int, epochs: int, negative_samples: int, learning_rate: float, batch_size: int) -> None:
    if embedding_dim < 1:
        raise ValueError("embedding_dim must be >= 1")
    if epochs < 1:
        raise ValueError("epochs must be >= 1")
    if negative_samples < 1:
        raise ValueError("negative_samples must be >= 1")
    if learning_rate <= 0:
        raise ValueError("learning_rate must be > 0")
    if batch_size < 1:
        raise ValueError("batch_size must be >= 1")


def _weighted_choice(neighbors: dict[str, float], rng: random.Random) -> str:
    total = sum(neighbors.values())
    if total <= 0:
        raise ValueError("graph walk neighbor weights must be positive")
    threshold = rng.random() * total
    cumulative = 0.0
    for item_id, weight in neighbors.items():
        cumulative += weight
        if cumulative >= threshold:
            return item_id
    return next(reversed(neighbors))


def _validate_output_paths(input_path: Path, sidecar_path: Path, manifest_path: Path, embeddings_path: Path) -> None:
    resolved = {
        "input_path": input_path.resolve(),
        "sidecar_path": sidecar_path.resolve(),
        "manifest_path": manifest_path.resolve(),
        "embeddings_path": embeddings_path.resolve(),
    }
    if len(set(resolved.values())) != len(resolved):
        raise ValueError("graph_walk output paths must be distinct from each other and the input path")
    for label, path in resolved.items():
        if label != "input_path" and ROOT.resolve() not in path.parents:
            raise ValueError(f"{label} must stay under project root: {path}")


def _cleanup_outputs(*paths: Path) -> None:
    for path in paths:
        if path.exists():
            path.unlink()


def _seed_everything(seed: int) -> None:
    random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_json(payload: dict[str, Any]) -> str:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
