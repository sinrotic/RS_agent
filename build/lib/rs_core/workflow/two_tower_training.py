from __future__ import annotations

import hashlib
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

FORBIDDEN_TRAIN_INPUT_MARKERS = ("valid", "test", "holdout", "eval_label", "eval-label", "10000")
ProgressCallback = Callable[[str, dict[str, Any]], None]

from rs_core.common.config import load_config
from rs_core.common.io import iter_jsonl, read_json, read_jsonl, write_json, write_jsonl
from rs_core.recsys.two_tower import save_two_tower_artifacts, train_two_tower_model
from rs_core.recsys.vector_index import dot_score, normalize_vector
from rs_core.workflow.hybrid_demo import _ensure_inputs, _leave_one_positive_out_sequences, _merge_nested, _resolve_path


def train_two_tower_recall(
    config_path: str | Path,
    output_dir: str | Path | None = None,
    limit_users: int | None = None,
    variant: str | None = None,
    config_overrides: dict[str, Any] | None = None,
    user_quality_manifest: str | Path | None = None,
    user_quality_bucket: str | None = None,
    item_vocab_manifest: str | Path | None = None,
    compact_inputs: bool = False,
    progress_callback: ProgressCallback | None = None,
) -> dict[str, Any]:
    config = load_config(config_path)
    if config_overrides:
        config = _merge_nested(config, config_overrides)

    training_config = dict(config.get("two_tower_training", {}) or {})
    if variant:
        training_config["variant"] = variant
    training_config.setdefault("variant", "dssm")
    training_config.setdefault("source_name", f"two_tower_{training_config['variant']}")
    training_config.setdefault("min_user_positives", 3)
    training_config.setdefault("max_samples_per_user", 5)
    training_config.setdefault("negative_sampling_power", 0.75)
    training_config.setdefault("gradient_accumulation_steps", 1)
    training_config.setdefault("mixed_precision", False)

    clean_dir = _resolve_path(config.get("clean_dir", "data/processed/amazon_2023_recall_clean_smoke_e2e"))
    output_path = _resolve_path(output_dir or training_config.get("output_dir", f"outputs/training/two_tower/two_tower_training/{training_config['variant']}"))
    item_vocab_manifest_path = _resolve_item_vocab_manifest_path(config, training_config, item_vocab_manifest)

    paths = _two_tower_required_paths(clean_dir, item_vocab_manifest_path)
    _ensure_inputs(paths)

    selected_user_ids = _user_quality_user_ids(user_quality_manifest, user_quality_bucket) if user_quality_manifest else None
    item_records = _load_item_records(paths["item_vocab_manifest"], training_config, compact_inputs, progress_callback)
    sequences = _load_training_sequences(paths["sequences"], limit_users, selected_user_ids, training_config, compact_inputs, progress_callback)
    sample_negative_stats = _attach_training_sample_negatives(sequences, training_config, progress_callback)
    split_stats: dict[str, Any] = {"training_input_users": len(sequences), "compact_inputs": compact_inputs, **sample_negative_stats}
    if user_quality_manifest:
        split_stats.update(
            {
                "user_quality_manifest_path": str(_resolve_path(user_quality_manifest)),
                "user_quality_bucket": user_quality_bucket or "all",
                "user_quality_selected_user_count": len(selected_user_ids or set()),
                "user_quality_matched_user_count": len(sequences),
            }
        )
    if str(config.get("evaluation_mode", "valid_test")) == "leave_one_positive_out":
        sequences, _, lopo_stats = _leave_one_positive_out_sequences(sequences)
        split_stats.update(lopo_stats)

    split_stats.update(
        {
            "item_vocab_manifest_path": str(paths["item_vocab_manifest"]),
            "item_vocab_path": str(paths["item_vocab"]),
            "item_vocab_size": len(item_records),
            "item_vocab_min_frequency": read_json(paths["item_vocab_manifest"]).get("min_frequency", 1),
            "split_scope": "train_only",
            "leakage_checks": {"train_inputs_only": True, "eval_paths_rejected": True},
        }
    )
    result = train_two_tower_model(sequences, item_records, training_config, progress_callback=progress_callback)
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
    user_quality_manifest: str | Path | None = None,
    user_quality_bucket: str | None = None,
    item_vocab_manifest: str | Path | None = None,
) -> dict[str, Any]:
    selected = variants or ["dssm", "youtube_dnn"]
    base_output = _resolve_path(output_dir) if output_dir else None
    runs = {}
    for variant in selected:
        run_output = (base_output / variant) if base_output else None
        runs[variant] = train_two_tower_recall(
            config_path,
            output_dir=run_output,
            limit_users=limit_users,
            variant=variant,
            item_vocab_manifest=item_vocab_manifest,
            user_quality_manifest=user_quality_manifest,
            user_quality_bucket=user_quality_bucket,
        )
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


def build_two_tower_item_vocab(
    canonical_interactions_train: str | Path,
    output_vocab: str | Path,
    output_manifest: str | Path,
    canonical_items: str | Path | None = None,
    min_frequency: int = 1,
) -> dict[str, Any]:
    interactions_path = _resolve_path(canonical_interactions_train)
    vocab_path = _resolve_path(output_vocab)
    manifest_path = _resolve_path(output_manifest)
    metadata_path = _resolve_path(canonical_items) if canonical_items else None
    if min_frequency < 1:
        raise ValueError("min_frequency must be >= 1")
    _validate_train_only_path(interactions_path, "canonical_interactions_train")
    _ensure_inputs({"canonical_interactions_train": interactions_path})
    if metadata_path:
        _ensure_inputs({"canonical_items_metadata": metadata_path})

    item_counts = Counter(
        item_id
        for row in iter_jsonl(interactions_path)
        for item_id in [str(row.get("parent_asin") or row.get("item_id") or "")]
        if item_id
    )
    item_id_set = {item_id for item_id, count in item_counts.items() if count >= min_frequency}
    item_ids = sorted(item_id_set)
    if not item_ids:
        raise ValueError("canonical_interactions.train.jsonl did not yield any item ids")

    metadata_by_id: dict[str, dict[str, Any]] = {}
    if metadata_path:
        for row in iter_jsonl(metadata_path):
            item_id = str(row.get("parent_asin") or row.get("item_id") or "")
            if item_id in item_id_set:
                metadata_by_id[item_id] = dict(row)

    rows = []
    for item_id in item_ids:
        row = dict(metadata_by_id.get(item_id, {}))
        row["parent_asin"] = item_id
        row["item_id"] = item_id
        rows.append(row)
    write_jsonl(vocab_path, rows)

    manifest = {
        "schema_version": "two_tower_item_vocab_v1",
        "item_vocab_path": str(vocab_path),
        "source_paths": {
            "canonical_interactions_train": str(interactions_path),
            "canonical_items_metadata": str(metadata_path) if metadata_path else None,
        },
        "item_count": len(rows),
        "original_item_count": len(item_counts),
        "filtered_item_count": len(item_counts) - len(rows),
        "min_frequency": min_frequency,
        "metadata_join_added_items": False,
        "forbidden_sources": ["popular_recall.jsonl", "category_recall_items.jsonl", "valid", "test", "holdout", "eval_label"],
        "content_hash": f"sha256:{_sha256_file(vocab_path)}",
    }
    write_json(manifest_path, manifest)
    return manifest


def _two_tower_required_paths(clean_dir: Path, item_vocab_manifest_path: Path) -> dict[str, Path]:
    sequence_path = clean_dir / "user_sequences.train.jsonl"
    _validate_train_only_path(sequence_path, "user_sequences_train")
    manifest = _load_item_vocab_manifest(item_vocab_manifest_path)
    item_vocab_path = _resolve_path(manifest["item_vocab_path"])
    return {
        "sequences": sequence_path,
        "item_vocab_manifest": item_vocab_manifest_path,
        "item_vocab": item_vocab_path,
    }


def _load_training_sequences(
    sequence_path: Path,
    limit_users: int | None,
    selected_user_ids: set[str] | None,
    training_config: dict[str, Any] | None = None,
    compact_inputs: bool = False,
    progress_callback: ProgressCallback | None = None,
) -> list[dict[str, Any]]:
    if not compact_inputs and progress_callback is None and selected_user_ids is None:
        sequences = read_jsonl(sequence_path)
        return sequences[:limit_users] if limit_users is not None else sequences

    sequences = []
    matched_user_ids: set[str] = set()
    scanned = 0
    for row in iter_jsonl(sequence_path):
        scanned += 1
        user_id = str(row.get("user_id") or "")
        if selected_user_ids is not None and user_id not in selected_user_ids:
            continue
        sequences.append(_compact_training_sequence(row, training_config) if compact_inputs else row)
        if selected_user_ids is not None:
            matched_user_ids.add(user_id)
        if progress_callback and len(sequences) % 10000 == 0:
            progress_callback("load_training_sequences", {"scanned_rows": scanned, "kept_rows": len(sequences), "limit_users": limit_users})
        if limit_users is not None and len(sequences) >= limit_users:
            break
        if selected_user_ids is not None and len(matched_user_ids) == len(selected_user_ids):
            break
    if progress_callback:
        progress_callback("load_training_sequences_complete", {"scanned_rows": scanned, "kept_rows": len(sequences), "limit_users": limit_users})
    return sequences


def _attach_training_sample_negatives(
    sequences: list[dict[str, Any]],
    training_config: dict[str, Any] | None,
    progress_callback: ProgressCallback | None = None,
) -> dict[str, Any]:
    config = training_config or {}
    raw_path = config.get("training_sample_path") or config.get("train_samples_path") or config.get("two_tower_train_samples_path")
    if not raw_path:
        return {"training_sample_negative_path": "", "training_sample_negative_users": 0, "training_sample_negative_items_attached": 0}
    sample_path = _resolve_path(raw_path)
    _validate_train_only_path(sample_path, "two_tower_train_samples")
    if sample_path.name != "two_tower_train_samples.jsonl":
        raise ValueError("two_tower explicit negative samples must come from two_tower_train_samples.jsonl")
    user_to_negatives: dict[str, list[str]] = {}
    scanned = 0
    for row in iter_jsonl(sample_path):
        scanned += 1
        if row.get("source") not in {None, "two_tower_method_dataset"}:
            raise ValueError("two_tower training samples must come from two_tower_method_dataset")
        user_id = str(row.get("user_id") or "")
        values = row.get("negative_item_ids", [])
        if not user_id or not isinstance(values, list):
            continue
        user_to_negatives.setdefault(user_id, []).extend(str(item) for item in values if item)
    attached_users = 0
    attached_items = 0
    for sequence in sequences:
        user_id = str(sequence.get("user_id") or "")
        negatives = user_to_negatives.get(user_id, [])
        if not negatives:
            continue
        existing = sequence.get("negative_item_ids", [])
        merged = list(dict.fromkeys([*(str(item) for item in existing if item), *negatives])) if isinstance(existing, list) else list(dict.fromkeys(negatives))
        sequence["negative_item_ids"] = merged
        attached_users += 1
        attached_items += len(merged)
    if progress_callback:
        progress_callback(
            "training_sample_negatives_complete",
            {"sample_rows_scanned": scanned, "attached_users": attached_users, "attached_negative_items": attached_items, "sample_path": str(sample_path)},
        )
    return {
        "training_sample_negative_path": str(sample_path),
        "training_sample_negative_users": attached_users,
        "training_sample_negative_items_attached": attached_items,
    }


def _compact_training_sequence(row: dict[str, Any], training_config: dict[str, Any] | None) -> dict[str, Any]:
    config = training_config or {}
    keys = [str(item) for item in config.get("sequence_keys", ["recent_positive_item_sequence", "recent_strong_positive_item_sequence"])]
    if "recent_item_sequence" not in keys:
        keys.append("recent_item_sequence")
    window = int(config.get("user_history_window", 20))
    compact = {"user_id": str(row.get("user_id") or "")}
    for key in keys:
        values = row.get(key, [])
        timestamp_key = _timestamp_sequence_key(key)
        timestamp_values = row.get(timestamp_key, [])
        if isinstance(values, list):
            source_values = values[-window:]
            source_timestamps = timestamp_values[-window:] if isinstance(timestamp_values, list) else []
            compact_values = []
            compact_timestamps = []
            for index, item in enumerate(source_values):
                item_id = str(item or "")
                if not item_id:
                    continue
                compact_values.append(item_id)
                if index < len(source_timestamps):
                    compact_timestamps.append(source_timestamps[index])
            compact[key] = compact_values
            compact[timestamp_key] = compact_timestamps
    negative_values = row.get("negative_item_ids", [])
    if isinstance(negative_values, list):
        compact["negative_item_ids"] = [str(item) for item in negative_values if item]
    return compact


def _user_quality_user_ids(user_quality_manifest: str | Path, bucket: str | None) -> set[str]:
    manifest_path = _resolve_path(user_quality_manifest)
    manifest = read_json(manifest_path)
    if manifest.get("policy_role") != "eligibility_policy_not_recall_source":
        raise ValueError("user_quality manifest must be an eligibility policy, not a recall source")
    if manifest.get("candidate_generation_allowed") is not False:
        raise ValueError("user_quality candidate_generation_allowed must be false")
    if manifest.get("ranking_input_replacement_allowed") is not False:
        raise ValueError("user_quality ranking_input_replacement_allowed must be false")
    if manifest.get("pool1000_allowed") is not False:
        raise ValueError("user_quality pool1000_allowed must be false")

    selected = set()
    for profile in manifest.get("profiles", []):
        if bucket and bucket != "all_eligible" and profile.get("quality_bucket") != bucket:
            continue
        user_id = str(profile.get("user_id") or "")
        if user_id:
            selected.add(user_id)
    if not selected:
        raise ValueError("user_quality selection did not yield any users")
    return selected


def _resolve_item_vocab_manifest_path(config: dict[str, Any], training_config: dict[str, Any], item_vocab_manifest: str | Path | None) -> Path:
    candidate = item_vocab_manifest or training_config.get("item_vocab_manifest") or training_config.get("item_vocab_manifest_path") or config.get("two_tower_item_vocab_manifest") or config.get("two_tower_item_vocab_manifest_path")
    if not candidate:
        raise ValueError("two_tower training requires a train-only item_vocab_manifest")
    return _resolve_path(candidate)


def _load_item_vocab_manifest(item_vocab_manifest_path: Path) -> dict[str, Any]:
    _validate_train_only_path(item_vocab_manifest_path, "item_vocab_manifest")
    manifest = read_json(item_vocab_manifest_path)
    if manifest.get("schema_version") != "two_tower_item_vocab_v1":
        raise ValueError("item_vocab_manifest must use schema_version two_tower_item_vocab_v1")
    if manifest.get("metadata_join_added_items") is not False:
        raise ValueError("metadata join must not add item ids to two_tower item vocab")
    source_paths = manifest.get("source_paths", {})
    _validate_train_only_path(_resolve_path(source_paths.get("canonical_interactions_train", "")), "canonical_interactions_train")
    vocab_path = _resolve_path(manifest.get("item_vocab_path", ""))
    if not vocab_path.exists():
        raise ValueError(f"missing two_tower item vocab: {vocab_path}")
    row_count = sum(1 for _ in iter_jsonl(vocab_path))
    if manifest.get("item_count") != row_count:
        raise ValueError("item_vocab manifest item_count does not match vocab rows")
    return manifest


def _load_item_records(
    item_vocab_manifest_path: Path,
    training_config: dict[str, Any] | None = None,
    compact_inputs: bool = False,
    progress_callback: ProgressCallback | None = None,
) -> list[dict[str, Any]]:
    manifest = _load_item_vocab_manifest(item_vocab_manifest_path)
    item_vocab_path = _resolve_path(manifest["item_vocab_path"])
    text_fields = [str(item) for item in (training_config or {}).get("text_fields", ["title_clean", "main_category", "category", "description_text", "features_text", "item_text", "categories_flat"])]
    side_feature_fields = [str(item) for item in (training_config or {}).get("side_feature_fields", [])]
    compact_fields = list(dict.fromkeys([*text_fields, *side_feature_fields]))
    by_id: dict[str, dict[str, Any]] = {}
    scanned = 0
    for row in iter_jsonl(item_vocab_path):
        scanned += 1
        item_id = str(row.get("parent_asin") or row.get("item_id") or "")
        if not item_id:
            continue
        if compact_inputs:
            record = {field: row[field] for field in compact_fields if field in row}
            record.update({"parent_asin": item_id, "item_id": item_id})
        else:
            record = dict(row) | {"parent_asin": item_id}
        by_id[item_id] = record
        if progress_callback and len(by_id) % 10000 == 0:
            progress_callback("load_item_records", {"scanned_rows": scanned, "kept_rows": len(by_id), "manifest_item_count": manifest.get("item_count")})
    if len(by_id) != manifest.get("item_count"):
        raise ValueError("item_vocab contains empty or duplicate item ids")
    if progress_callback:
        progress_callback("load_item_records_complete", {"scanned_rows": scanned, "kept_rows": len(by_id), "manifest_item_count": manifest.get("item_count")})
    return list(by_id.values())


def _timestamp_sequence_key(sequence_key: str) -> str:
    if sequence_key.endswith("_item_sequence"):
        return f"{sequence_key[:-len('_item_sequence')]}_timestamp_sequence"
    if sequence_key.endswith("_sequence"):
        return f"{sequence_key[:-len('_sequence')]}_timestamp_sequence"
    return f"{sequence_key}_timestamp_sequence"


def _validate_train_only_path(path: Path, role: str) -> None:
    if not str(path):
        raise ValueError(f"missing {role} path")
    parts = [part.lower() for part in path.parts]
    name = path.name.lower()
    if any(marker in parts or marker in name for marker in FORBIDDEN_TRAIN_INPUT_MARKERS):
        raise ValueError(f"{role} must be train-only and must not reference eval/valid/test/holdout inputs: {path}")
    if role == "canonical_interactions_train" and path.name != "canonical_interactions.train.jsonl":
        raise ValueError("two_tower item vocab must be derived from canonical_interactions.train.jsonl")
    if role == "user_sequences_train" and path.name != "user_sequences.train.jsonl":
        raise ValueError("two_tower training must read user_sequences.train.jsonl")


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
