from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from rs_core.common.config import load_config
from rs_core.common.io import read_jsonl, write_json, write_jsonl
from rs_core.recsys.two_tower import save_two_tower_artifacts, train_two_tower_model
from rs_core.recsys.vector_index import dot_score, normalize_vector
from rs_core.workflow.hybrid_demo import _ensure_inputs, _leave_one_positive_out_sequences, _merge_nested, _required_paths, _resolve_path


def train_two_tower_recall(
    config_path: str | Path,
    output_dir: str | Path | None = None,
    limit_users: int | None = None,
    variant: str | None = None,
    config_overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    config = load_config(config_path)
    if config_overrides:
        config = _merge_nested(config, config_overrides)

    training_config = dict(config.get("two_tower_training", {}) or {})
    if variant:
        training_config["variant"] = variant
    training_config.setdefault("variant", "dssm")
    training_config.setdefault("source_name", f"two_tower_{training_config['variant']}")

    clean_dir = _resolve_path(config.get("clean_dir", "data/processed/amazon_2023_recall_clean_smoke_e2e"))
    views_dir = _resolve_path(config.get("views_dir", "data/processed/amazon_2023_recall_views_smoke_e2e"))
    output_path = _resolve_path(output_dir or training_config.get("output_dir", f"outputs/training/two_tower/two_tower_training/{training_config['variant']}"))

    paths = _required_paths(clean_dir, views_dir)
    _ensure_inputs(paths)

    sequences = read_jsonl(paths["sequences"])
    if limit_users is not None:
        sequences = sequences[:limit_users]
    split_stats: dict[str, int] = {"training_input_users": len(sequences)}
    if str(config.get("evaluation_mode", "valid_test")) == "leave_one_positive_out":
        sequences, _, lopo_stats = _leave_one_positive_out_sequences(sequences)
        split_stats.update(lopo_stats)

    item_records = _load_item_records(paths["category_items"], paths["popular"])
    result = train_two_tower_model(sequences, item_records, training_config)
    result["train_metrics"].update(split_stats)
    contract = save_two_tower_artifacts(result, output_path)
    return {
        "artifact_manifest_path": contract["artifact_manifest"],
        "train_config_path": contract["train_config"],
        "model_path": contract["model"],
        "item_embeddings_path": contract["item_embeddings"],
        "user_embeddings_path": contract["user_embeddings"],
        "item_id_map_path": contract["item_id_map"],
        "user_id_map_path": contract["user_id_map"],
        "train_metrics_path": contract["train_metrics"],
        "recall_index_path": contract["recall_index"],
        "metrics": result["train_metrics"],
    }


def train_two_tower_variants(
    config_path: str | Path,
    output_dir: str | Path | None = None,
    limit_users: int | None = None,
    variants: list[str] | None = None,
) -> dict[str, Any]:
    selected = variants or ["dssm", "youtube_dnn"]
    base_output = _resolve_path(output_dir) if output_dir else None
    runs = {}
    for variant in selected:
        run_output = (base_output / variant) if base_output else None
        runs[variant] = train_two_tower_recall(config_path, output_dir=run_output, limit_users=limit_users, variant=variant)
    return {"variants": selected, "runs": runs}


def build_two_tower_seed_sidecar(
    embedding_input_path: str | Path,
    sidecar_path: str | Path,
    manifest_path: str | Path,
    neighbor_k: int,
    config_path: str | Path | None = None,
) -> dict[str, Any]:
    input_path = _resolve_path(embedding_input_path)
    output_path = _resolve_path(sidecar_path)
    output_manifest_path = _resolve_path(manifest_path)
    if neighbor_k < 1:
        raise ValueError("neighbor_k must be >= 1")
    _validate_distinct_sidecar_paths(input_path, output_path, output_manifest_path)
    if not input_path.exists():
        raise ValueError(f"missing two_tower_seed embedding input: {input_path}")

    rows = _load_sidecar_embedding_rows(input_path)
    sidecar_rows = _two_tower_seed_rows(rows, neighbor_k)
    _cleanup_sidecar_outputs(output_path, output_manifest_path)
    write_jsonl(output_path, sidecar_rows)

    config_hash = _sha256_file(_resolve_path(config_path)) if config_path else ""
    manifest = {
        "phase": "1.18",
        "source": "two_tower_seed",
        "created_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "embedding_input_path": str(input_path),
        "sidecar_path": str(output_path),
        "item_count": len(rows),
        "neighbor_k": neighbor_k,
        "similarity": "cosine",
        "deterministic_sort": "score_desc_item_id_asc",
        "embedding_sha256": _sha256_file(input_path),
        "sidecar_sha256": _sha256_file(output_path),
        "config_sha256": config_hash,
        "schema_version": "two_tower_seed_neighbors_v1",
    }
    write_json(output_manifest_path, manifest)
    return manifest


def build_two_tower_seed_sidecar_from_config(config_path: str | Path) -> dict[str, Any]:
    resolved_config_path = _resolve_path(config_path)
    config = load_config(resolved_config_path)
    sidecar_config = dict(config.get("two_tower_seed_sidecar", {}) or {})
    embedding_input_path = sidecar_config.get("embedding_input_path") or sidecar_config.get("item_embeddings_path")
    sidecar_path = sidecar_config.get("sidecar_path")
    manifest_path = sidecar_config.get("manifest_path")
    if not embedding_input_path or not sidecar_path or not manifest_path:
        raise ValueError("two_tower_seed_sidecar requires embedding_input_path, sidecar_path, and manifest_path")
    return build_two_tower_seed_sidecar(
        embedding_input_path=embedding_input_path,
        sidecar_path=sidecar_path,
        manifest_path=manifest_path,
        neighbor_k=int(sidecar_config.get("neighbor_k", 50)),
        config_path=resolved_config_path,
    )


def _load_item_records(category_items_path: Path, popular_path: Path) -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    for path in (category_items_path, popular_path):
        for row in read_jsonl(path):
            item_id = str(row.get("parent_asin") or row.get("item_id") or "")
            if not item_id:
                continue
            by_id[item_id] = dict(by_id.get(item_id, {})) | dict(row) | {"parent_asin": item_id}
    return list(by_id.values())


def _load_sidecar_embedding_rows(path: Path) -> list[dict[str, Any]]:
    rows = []
    seen: set[str] = set()
    for line_number, row in enumerate(read_jsonl(path), start=1):
        if set(row) - {"item_id", "embedding", "embedding_norm", "main_category", "category", "title_clean"}:
            raise ValueError(f"schema mismatch in two_tower_seed embedding row {line_number}")
        item_id = row.get("item_id")
        embedding = row.get("embedding")
        if not isinstance(item_id, str) or not item_id:
            raise ValueError(f"missing item_id in two_tower_seed embedding row {line_number}")
        if item_id in seen:
            raise ValueError(f"duplicate two_tower_seed source item_id: {item_id}")
        if not isinstance(embedding, list) or not embedding:
            raise ValueError(f"missing embedding for two_tower_seed item_id: {item_id}")
        try:
            vector = normalize_vector([float(value) for value in embedding])
        except (TypeError, ValueError) as exc:
            raise ValueError(f"invalid embedding for two_tower_seed item_id: {item_id}") from exc
        if not vector:
            raise ValueError(f"empty embedding vector for two_tower_seed item_id: {item_id}")
        seen.add(item_id)
        rows.append({"item_id": item_id, "embedding": vector})
    if not rows:
        raise ValueError(f"empty two_tower_seed embedding input: {path}")
    dimensions = {len(row["embedding"]) for row in rows}
    if len(dimensions) != 1:
        raise ValueError("two_tower_seed embeddings must have a consistent dimension")
    return rows


def _two_tower_seed_rows(rows: list[dict[str, Any]], neighbor_k: int) -> list[dict[str, Any]]:
    output = []
    for source in sorted(rows, key=lambda row: row["item_id"]):
        seen_neighbors: set[str] = set()
        scored = []
        for neighbor in rows:
            neighbor_id = neighbor["item_id"]
            if neighbor_id == source["item_id"]:
                continue
            if neighbor_id in seen_neighbors:
                raise ValueError(f"duplicate two_tower_seed neighbor item_id: {neighbor_id}")
            seen_neighbors.add(neighbor_id)
            scored.append({"item_id": neighbor_id, "score": round(dot_score(source["embedding"], neighbor["embedding"]), 6)})
        scored = sorted(scored, key=lambda row: (-row["score"], row["item_id"]))[:neighbor_k]
        output.append({
            "item_id": source["item_id"],
            "neighbors": [dict(row, rank=rank) for rank, row in enumerate(scored, start=1)],
        })
    return output


def _validate_distinct_sidecar_paths(input_path: Path, sidecar_path: Path, manifest_path: Path) -> None:
    resolved = {
        "embedding_input_path": input_path.resolve(),
        "sidecar_path": sidecar_path.resolve(),
        "manifest_path": manifest_path.resolve(),
    }
    if len(set(resolved.values())) != len(resolved):
        raise ValueError("two_tower_seed sidecar paths must be distinct")



def _cleanup_sidecar_outputs(sidecar_path: Path, manifest_path: Path) -> None:
    for path in {sidecar_path, manifest_path}:
        if path.exists():
            path.unlink()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
