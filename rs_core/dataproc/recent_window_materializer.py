from __future__ import annotations

import hashlib
import json
import shutil
import os
from collections import Counter, deque
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DEFAULT_SOURCE_MANIFEST = "./data/processed/amazon_2023_recall_clean_full/manifest.json"
DEFAULT_OUTPUT_DIR = "./data/processed/amazon_2023_recall_recent_2y_1m_3m"
DEFAULT_SEQUENCE_MAX_LEN = 50
DEFAULT_SHARD_COUNT = 256

TRAIN_START_MS = 1623715200000
VALID_START_MS = 1684108800000
TEST_START_MS = 1686787200000
TEST_END_MS = 1694649600000

WINDOWS = {
    "train": {
        "start_ms": TRAIN_START_MS,
        "end_ms": VALID_START_MS,
        "start_utc": "2021-06-15T00:00:00Z",
        "end_utc": "2023-05-15T00:00:00Z",
    },
    "valid": {
        "start_ms": VALID_START_MS,
        "end_ms": TEST_START_MS,
        "start_utc": "2023-05-15T00:00:00Z",
        "end_utc": "2023-06-15T00:00:00Z",
    },
    "test": {
        "start_ms": TEST_START_MS,
        "end_ms": TEST_END_MS,
        "start_utc": "2023-06-15T00:00:00Z",
        "end_utc": "2023-09-14T00:00:00Z",
    },
}


def compact_json(record: dict[str, Any]) -> str:
    return json.dumps(record, ensure_ascii=False)


def iter_jsonl(path: Path):
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            payload = line.strip()
            if payload:
                yield json.loads(payload)


def resolve_manifest_path(manifest_path: Path, configured_path: str) -> Path:
    path = Path(configured_path)
    if path.is_absolute():
        return path
    root_candidate = Path.cwd() / path
    if root_candidate.exists():
        return root_candidate
    return manifest_path.parent / path


def file_signature(path: Path) -> dict[str, Any]:
    digest = hashlib.sha256()
    rows = 0
    with path.open("rb") as handle:
        for line in handle:
            if line.strip():
                rows += 1
            digest.update(line)
    return {"path": str(path), "size_bytes": path.stat().st_size, "row_count": rows, "sha256": digest.hexdigest()}


def split_for_timestamp(timestamp: int) -> str | None:
    if TRAIN_START_MS <= timestamp < VALID_START_MS:
        return "train"
    if VALID_START_MS <= timestamp < TEST_START_MS:
        return "valid"
    if TEST_START_MS <= timestamp < TEST_END_MS:
        return "test"
    return None


def empty_sequence_state(sequence_max_len: int) -> dict[str, Any]:
    return {
        "sequence_len": 0,
        "positive_sequence_len": 0,
        "strong_positive_sequence_len": 0,
        "recent_item_sequence": deque(maxlen=sequence_max_len),
        "recent_timestamp_sequence": deque(maxlen=sequence_max_len),
        "recent_positive_item_sequence": deque(maxlen=sequence_max_len),
        "recent_positive_timestamp_sequence": deque(maxlen=sequence_max_len),
        "recent_strong_positive_item_sequence": deque(maxlen=sequence_max_len),
        "recent_strong_positive_timestamp_sequence": deque(maxlen=sequence_max_len),
    }


def update_sequence_state(state: dict[str, Any], record: dict[str, Any]) -> None:
    item_id = record["parent_asin"]
    timestamp = int(record["timestamp"])
    is_positive = bool(record.get("label_binary"))
    is_strong_positive = bool(record.get("label_strong"))
    state["sequence_len"] += 1
    state["recent_item_sequence"].append(item_id)
    state["recent_timestamp_sequence"].append(timestamp)
    if is_positive:
        state["positive_sequence_len"] += 1
        state["recent_positive_item_sequence"].append(item_id)
        state["recent_positive_timestamp_sequence"].append(timestamp)
    if is_strong_positive:
        state["strong_positive_sequence_len"] += 1
        state["recent_strong_positive_item_sequence"].append(item_id)
        state["recent_strong_positive_timestamp_sequence"].append(timestamp)


def serialize_sequence(user_id: str, state: dict[str, Any]) -> dict[str, Any]:
    return {
        "user_id": user_id,
        "sequence_len": state["sequence_len"],
        "positive_sequence_len": state["positive_sequence_len"],
        "strong_positive_sequence_len": state["strong_positive_sequence_len"],
        "recent_item_sequence": list(state["recent_item_sequence"]),
        "recent_timestamp_sequence": list(state["recent_timestamp_sequence"]),
        "recent_positive_item_sequence": list(state["recent_positive_item_sequence"]),
        "recent_positive_timestamp_sequence": list(state["recent_positive_timestamp_sequence"]),
        "recent_strong_positive_item_sequence": list(state["recent_strong_positive_item_sequence"]),
        "recent_strong_positive_timestamp_sequence": list(state["recent_strong_positive_timestamp_sequence"]),
    }


def stable_shard(user_id: str, shard_count: int) -> int:
    return int(hashlib.blake2b(user_id.encode("utf-8"), digest_size=4).hexdigest(), 16) % shard_count


def ensure_new_output_dir(output_dir: Path) -> None:
    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError(f"Refusing to overwrite non-empty output directory: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)


def collect_window_counts(source_interactions_path: Path) -> dict[str, Any]:
    split_bits = {"train": 1, "valid": 2, "test": 4}
    user_stats: dict[str, list[int]] = {}
    item_stats: dict[str, list[int]] = {}
    split_counts = {"train": 0, "valid": 0, "test": 0}
    positive_train_interaction_count = 0
    strong_positive_train_interaction_count = 0
    source_rows = 0
    kept_rows = 0
    skipped_outside_window = 0

    for record in iter_jsonl(source_interactions_path):
        source_rows += 1
        split = split_for_timestamp(int(record["timestamp"]))
        if split is None:
            skipped_outside_window += 1
            continue
        kept_rows += 1
        user_id = record["user_id"]
        item_id = record["parent_asin"]
        bit = split_bits[split]
        user_stat = user_stats.setdefault(user_id, [0, 0, 0, 0])
        item_stat = item_stats.setdefault(item_id, [0, 0])
        user_stat[0] += 1
        user_stat[1] |= bit
        item_stat[0] += 1
        item_stat[1] |= bit
        split_counts[split] += 1
        if split == "train" and record.get("label_binary"):
            positive_train_interaction_count += 1
            user_stat[2] += 1
            if record.get("label_strong"):
                strong_positive_train_interaction_count += 1
                user_stat[3] += 1

    split_user_counts = {
        split: sum(1 for stat in user_stats.values() if stat[1] & bit)
        for split, bit in split_bits.items()
    }
    split_item_counts = {
        split: sum(1 for stat in item_stats.values() if stat[1] & bit)
        for split, bit in split_bits.items()
    }
    split_items = {
        split: {item_id for item_id, stat in item_stats.items() if stat[1] & bit}
        for split, bit in split_bits.items()
    }

    return {
        "user_counts": Counter({user_id: stat[0] for user_id, stat in user_stats.items()}),
        "item_counts": Counter({item_id: stat[0] for item_id, stat in item_stats.items()}),
        "split_counts": split_counts,
        "split_user_counts": split_user_counts,
        "split_item_counts": split_item_counts,
        "split_items": split_items,
        "source_rows": source_rows,
        "kept_rows": kept_rows,
        "skipped_outside_window": skipped_outside_window,
        "train_readiness": {
            "positive_train_interaction_count": positive_train_interaction_count,
            "strong_positive_train_interaction_count": strong_positive_train_interaction_count,
            "users_with_ge2_positive_train_items": sum(1 for stat in user_stats.values() if stat[2] >= 2),
            "users_with_ge2_strong_positive_train_items": sum(1 for stat in user_stats.values() if stat[3] >= 2),
        },
    }


def write_window_interactions(
    source_interactions_path: Path,
    output_dir: Path,
    user_counts: Counter[str],
    item_counts: Counter[str],
    shard_count: int,
) -> dict[str, Any]:
    canonical_path = output_dir / "canonical_interactions.jsonl"
    split_paths = {
        "all": canonical_path,
        "train": output_dir / "canonical_interactions.train.jsonl",
        "valid": output_dir / "canonical_interactions.valid.jsonl",
        "test": output_dir / "canonical_interactions.test.jsonl",
    }
    shard_dir = output_dir / f"_sequence_shards_{os.getpid()}"
    shard_dir.mkdir()
    shard_handles = [
        (shard_dir / f"part-{index:04d}.jsonl").open("w", encoding="utf-8")
        for index in range(shard_count)
    ]
    split_handles = {
        split: path.open("w", encoding="utf-8")
        for split, path in split_paths.items()
    }
    row_num = 0
    try:
        for record in iter_jsonl(source_interactions_path):
            split = split_for_timestamp(int(record["timestamp"]))
            if split is None:
                continue
            row_num += 1
            record = dict(record)
            record["split"] = split
            record["row_num"] = row_num
            record["user_interaction_count"] = int(user_counts[record["user_id"]])
            record["item_interaction_count"] = int(item_counts[record["parent_asin"]])
            line = compact_json(record) + "\n"
            split_handles["all"].write(line)
            split_handles[split].write(line)
            shard_handles[stable_shard(record["user_id"], shard_count)].write(line)
    finally:
        for handle in split_handles.values():
            handle.close()
        for handle in shard_handles:
            handle.close()

    return {
        "canonical_interactions_path": str(canonical_path),
        "all_interactions_path": str(canonical_path),
        "split_paths": {split: str(path) for split, path in split_paths.items()},
        "shard_dir": shard_dir,
        "rows_written": row_num,
    }


def write_window_items(source_items_path: Path, output_dir: Path, train_items: set[str], all_items: set[str]) -> dict[str, Any]:
    train_path = output_dir / "canonical_items.jsonl"
    all_path = output_dir / "canonical_items.all.jsonl"
    train_written = 0
    all_written = 0
    seen_train: set[str] = set()
    seen_all: set[str] = set()
    with train_path.open("w", encoding="utf-8") as train_sink, all_path.open("w", encoding="utf-8") as all_sink:
        for record in iter_jsonl(source_items_path):
            item_id = record["parent_asin"]
            line = compact_json(record) + "\n"
            if item_id in all_items:
                all_sink.write(line)
                all_written += 1
                seen_all.add(item_id)
            if item_id in train_items:
                train_sink.write(line)
                train_written += 1
                seen_train.add(item_id)
    return {
        "canonical_items_path": str(train_path),
        "all_canonical_items_path": str(all_path),
        "canonical_items_written": train_written,
        "all_canonical_items_written": all_written,
        "missing_train_item_metadata": len(train_items - seen_train),
        "missing_all_item_metadata": len(all_items - seen_all),
    }


def write_user_sequences_from_shards(
    shard_dir: Path,
    output_dir: Path,
    sequence_max_len: int,
) -> dict[str, Any]:
    all_path = output_dir / "user_sequences.jsonl"
    train_path = output_dir / "user_sequences.train.jsonl"
    user_sequence_count = 0
    train_user_sequence_count = 0
    longest_sequence = 0
    longest_train_sequence = 0

    with all_path.open("w", encoding="utf-8") as all_sink, train_path.open("w", encoding="utf-8") as train_sink:
        for shard_path in sorted(shard_dir.glob("part-*.jsonl")):
            states: dict[str, dict[str, Any]] = {}
            train_states: dict[str, dict[str, Any]] = {}
            for record in iter_jsonl(shard_path):
                user_id = record["user_id"]
                state = states.setdefault(user_id, empty_sequence_state(sequence_max_len))
                update_sequence_state(state, record)
                if record["split"] == "train":
                    train_state = train_states.setdefault(user_id, empty_sequence_state(sequence_max_len))
                    update_sequence_state(train_state, record)
            for user_id in sorted(states):
                state = states[user_id]
                all_sink.write(compact_json(serialize_sequence(user_id, state)) + "\n")
                user_sequence_count += 1
                longest_sequence = max(longest_sequence, int(state["sequence_len"]))
                train_state = train_states.get(user_id)
                if train_state and train_state["sequence_len"] > 0:
                    train_sink.write(compact_json(serialize_sequence(user_id, train_state)) + "\n")
                    train_user_sequence_count += 1
                    longest_train_sequence = max(longest_train_sequence, int(train_state["sequence_len"]))

    shutil.rmtree(shard_dir)
    return {
        "user_sequences_path": str(all_path),
        "train_user_sequences_path": str(train_path),
        "user_sequence_count": user_sequence_count,
        "train_user_sequence_count": train_user_sequence_count,
        "longest_sequence": longest_sequence,
        "longest_train_sequence": longest_train_sequence,
    }


def build_split_summary(
    split_counts: dict[str, int],
    split_user_counts: dict[str, int],
    split_item_counts: dict[str, int],
    total_users: int,
    total_items: int,
) -> dict[str, Any]:
    summary = {
        split: {
            "interaction_count": split_counts[split],
            "distinct_user_count": split_user_counts[split],
            "distinct_item_count": split_item_counts[split],
        }
        for split in ("train", "valid", "test")
    }
    summary["all"] = {
        "interaction_count": sum(split_counts.values()),
        "distinct_user_count": total_users,
        "distinct_item_count": total_items,
    }
    return summary


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def materialize_recent_window_dataset(
    source_manifest_path: str | Path = DEFAULT_SOURCE_MANIFEST,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    sequence_max_len: int = DEFAULT_SEQUENCE_MAX_LEN,
    shard_count: int = DEFAULT_SHARD_COUNT,
) -> dict[str, Any]:
    if sequence_max_len < 1:
        raise ValueError("sequence_max_len must be >= 1")
    if shard_count < 1:
        raise ValueError("shard_count must be >= 1")

    source_manifest_path = Path(source_manifest_path)
    source_manifest = json.loads(source_manifest_path.read_text(encoding="utf-8"))
    output_path = Path(output_dir)
    ensure_new_output_dir(output_path)

    source_interactions_path = resolve_manifest_path(
        source_manifest_path,
        source_manifest.get("all_interactions_path") or source_manifest["canonical_interactions_path"],
    )
    source_items_path = resolve_manifest_path(source_manifest_path, source_manifest["canonical_items_path"])

    counts = collect_window_counts(source_interactions_path)
    split_summary = build_split_summary(
        counts["split_counts"],
        counts["split_user_counts"],
        counts["split_item_counts"],
        len(counts["user_counts"]),
        len(counts["item_counts"]),
    )
    interaction_outputs = write_window_interactions(
        source_interactions_path,
        output_path,
        counts["user_counts"],
        counts["item_counts"],
        shard_count,
    )
    item_outputs = write_window_items(
        source_items_path,
        output_path,
        counts["split_items"]["train"],
        set().union(*counts["split_items"].values()),
    )
    sequence_outputs = write_user_sequences_from_shards(
        interaction_outputs.pop("shard_dir"),
        output_path,
        sequence_max_len,
    )

    generated_at = datetime.now(UTC).isoformat()
    manifest_payload = {
        "dataset": source_manifest.get("dataset"),
        "schema_version": "recent_window_2y_1m_3m_v1",
        "generated_at": generated_at,
        "source_manifest": str(source_manifest_path),
        "source_canonical_interactions_path": str(source_interactions_path),
        "source_canonical_items_path": str(source_items_path),
        "output_dir": str(output_path),
        "window_policy": {
            "timezone": "UTC",
            "boundary_policy": "half_open",
            "splits": WINDOWS,
        },
        "canonical_interactions_path": interaction_outputs["canonical_interactions_path"],
        "all_interactions_path": interaction_outputs["all_interactions_path"],
        "split_paths": interaction_outputs["split_paths"],
        "canonical_items_path": item_outputs["canonical_items_path"],
        "all_canonical_items_path": item_outputs["all_canonical_items_path"],
        "user_sequences_path": sequence_outputs["user_sequences_path"],
        "train_user_sequences_path": sequence_outputs["train_user_sequences_path"],
        "sqlite_path": None,
        "counts": {
            "interactions": split_summary,
            "canonical_items": {
                "train_only": item_outputs["canonical_items_written"],
                "all_window": item_outputs["all_canonical_items_written"],
            },
            "user_sequences": {
                "all": sequence_outputs["user_sequence_count"],
                "train": sequence_outputs["train_user_sequence_count"],
            },
        },
        "stats_path": str(output_path / "stats.json"),
    }
    stats_payload = {
        "dataset": source_manifest.get("dataset"),
        "schema_version": "recent_window_2y_1m_3m_v1",
        "generated_at": generated_at,
        "config": {
            "sequence_max_len": sequence_max_len,
            "shard_count": shard_count,
            "window_policy": manifest_payload["window_policy"],
        },
        "source": {
            "manifest_path": str(source_manifest_path),
            "canonical_interactions_signature": file_signature(source_interactions_path),
            "canonical_items_signature": file_signature(source_items_path),
            "source_rows": counts["source_rows"],
            "skipped_outside_window": counts["skipped_outside_window"],
        },
        "split_summary": split_summary,
        "train_readiness": counts["train_readiness"],
        "outputs": {
            **interaction_outputs,
            **item_outputs,
            **sequence_outputs,
        },
    }
    write_json(output_path / "manifest.json", manifest_payload)
    write_json(output_path / "stats.json", stats_payload)
    return {"manifest": manifest_payload, "stats": stats_payload, "manifest_path": str(output_path / "manifest.json"), "stats_path": str(output_path / "stats.json")}
