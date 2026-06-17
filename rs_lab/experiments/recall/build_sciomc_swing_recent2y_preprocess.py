from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rs_core.common.io import iter_jsonl, write_json, write_jsonl
from rs_lab.experiments.recall.run_phase1_itemcf_covisit_representative_merge_eval import _enforce_project_venv

SCHEMA_VERSION = "sciomc_swing_recent2y_preprocess_v2"
BUILDER_SCHEMA_VERSION = "sciomc_swing_builder_train_manifest_v1"
DEFAULT_RECENT_WINDOW_MANIFEST = ROOT / "data" / "processed" / "amazon_2023_recall_recent_2y_1m_3m" / "manifest.json"
DEFAULT_OUTPUT_DIR = ROOT / "data" / "processed" / "amazon_2023_sciomc_swing_recent2y"
DEFAULT_SMOKE_TRAIN_USERS = 256
DEFAULT_SMOKE_EVAL_USERS = 128

FORBIDDEN_BUILDER_KEYS = {
    "all_interactions_path",
    "all_user_sequences_path",
    "all_window_path",
    "all_window_user_sequences_path",
    "canonical_interactions_path",
    "holdout_path",
    "holdout_user_sequences_path",
    "label_path",
    "labels_path",
    "split_paths",
    "test",
    "test_path",
    "test_user_sequences_path",
    "user_sequences_path",
    "valid",
    "valid_path",
    "valid_user_sequences_path",
}
FORBIDDEN_BUILDER_PATH_PARTS = {"valid", "test", "holdout", "label", "labels", "all_window"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Derive smoke and formal SciOMC Swing datasets from the fixed recent-window 2y manifest."
    )
    parser.add_argument("--recent-window-manifest", default=str(DEFAULT_RECENT_WINDOW_MANIFEST))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--smoke-train-users", type=int, default=DEFAULT_SMOKE_TRAIN_USERS)
    parser.add_argument("--smoke-eval-users", type=int, default=DEFAULT_SMOKE_EVAL_USERS)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--skip-venv-check", action="store_true")
    return parser.parse_args()


def build_sciomc_swing_recent2y_preprocess(
    *,
    recent_window_manifest_path: str | Path = DEFAULT_RECENT_WINDOW_MANIFEST,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    smoke_train_users: int = DEFAULT_SMOKE_TRAIN_USERS,
    smoke_eval_users: int = DEFAULT_SMOKE_EVAL_USERS,
    enforce_venv: bool = True,
    overwrite: bool = False,
) -> dict[str, Any]:
    if smoke_train_users <= 0:
        raise ValueError("smoke_train_users must be positive")
    if smoke_eval_users <= 0:
        raise ValueError("smoke_eval_users must be positive")
    if enforce_venv:
        _enforce_project_venv()

    manifest_path = Path(recent_window_manifest_path).resolve()
    output_path = Path(output_dir).resolve()
    if output_path.exists() and any(output_path.iterdir()):
        if not overwrite:
            raise FileExistsError(f"Refusing to overwrite non-empty output directory: {output_path}")
        shutil.rmtree(output_path)
    output_path.mkdir(parents=True, exist_ok=True)

    recent_manifest = _read_json(manifest_path)
    split_paths = _resolve_split_paths(manifest_path, recent_manifest)

    train_sequences, train_stats = _load_train_sequences(split_paths["train"])
    train_item_universe = set(train_stats["item_support"])
    valid_rows, valid_stats = _load_eval_rows(split_paths["valid"], train_item_universe)
    test_rows, test_stats = _load_eval_rows(split_paths["test"], train_item_universe)

    generated_at = datetime.now(UTC).isoformat()
    source_payload = {
        "recent_window_manifest_path": str(manifest_path),
        "source_schema_version": recent_manifest.get("schema_version"),
        "input_signatures": {split: _file_signature(path) for split, path in split_paths.items()},
    }
    policy_payload = {
        "time_split_source": "recent_window_manifest.fixed_splits",
        "signal": "positive_only_label_binary",
        "dedup": "user_item_keep_earliest_timestamp_per_split",
        "train_order": "chronological_by_timestamp_then_item",
        "eval_item_policy": "train_item_universe_only",
        "sample_count_caps": "none_for_formal; smoke_debug_subset_only",
    }

    formal = _write_variant(
        variant="formal",
        variant_dir=output_path / "formal",
        generated_at=generated_at,
        source_payload=source_payload,
        policy_payload={**policy_payload, "variant_sampling_policy": "formal_full_eligible_2y_processed_data"},
        recent_manifest=recent_manifest,
        train_sequences=train_sequences,
        valid_rows=valid_rows,
        test_rows=test_rows,
        train_stats=train_stats,
        valid_stats=valid_stats,
        test_stats=test_stats,
        sampling_policy={"type": "formal", "description": "Preserve all eligible processed 2y train/valid/test rows."},
    )

    smoke_train = _select_smoke_train_sequences(train_sequences, smoke_train_users)
    smoke_item_universe = {item_id for row in smoke_train for item_id in row["recent_positive_item_sequence"]}
    smoke_valid = _select_smoke_eval_rows(valid_rows, smoke_item_universe, smoke_eval_users)
    smoke_test = _select_smoke_eval_rows(test_rows, smoke_item_universe, smoke_eval_users)
    smoke_train_stats = _stats_from_train_sequences(smoke_train, skipped_non_positive_count=0, raw_positive_count=sum(row["positive_sequence_len"] for row in smoke_train))
    smoke_valid_stats = _stats_from_eval_rows(smoke_valid, raw_positive_pair_count=len(smoke_valid), skipped_non_positive_count=0, filtered_out_of_universe_count=0)
    smoke_test_stats = _stats_from_eval_rows(smoke_test, raw_positive_pair_count=len(smoke_test), skipped_non_positive_count=0, filtered_out_of_universe_count=0)
    smoke = _write_variant(
        variant="smoke",
        variant_dir=output_path / "smoke",
        generated_at=generated_at,
        source_payload=source_payload,
        policy_payload={**policy_payload, "variant_sampling_policy": "deterministic_debug_subset_by_sorted_user_id"},
        recent_manifest=recent_manifest,
        train_sequences=smoke_train,
        valid_rows=smoke_valid,
        test_rows=smoke_test,
        train_stats=smoke_train_stats,
        valid_stats=smoke_valid_stats,
        test_stats=smoke_test_stats,
        sampling_policy={
            "type": "smoke",
            "description": "Small deterministic pipeline/debug subset, not an old benchmark-size cap.",
            "train_selection": "first N train users after user_id sort",
            "eval_selection": "first N eval users after user_id/timestamp/item sort, filtered to smoke train item universe",
            "smoke_train_users": smoke_train_users,
            "smoke_eval_users": smoke_eval_users,
        },
    )

    manifest_out_path = output_path / "manifest.json"
    root_manifest = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "source_manifest_path": str(manifest_path),
        "source_schema_version": recent_manifest.get("schema_version"),
        "output_dir": str(output_path),
        "variants": {
            "smoke": smoke["manifest_path"],
            "formal": formal["manifest_path"],
        },
        "builder_manifests": {
            "smoke": smoke["builder_manifest_path"],
            "formal": formal["builder_manifest_path"],
        },
        "counts": {
            "smoke": smoke["manifest"]["counts"],
            "formal": formal["manifest"]["counts"],
        },
        "policy": policy_payload,
    }
    write_json(manifest_out_path, root_manifest)
    return {
        "manifest": root_manifest,
        "variants": {"smoke": smoke, "formal": formal},
        "manifest_path": str(manifest_out_path),
    }


def _write_variant(
    *,
    variant: str,
    variant_dir: Path,
    generated_at: str,
    source_payload: dict[str, Any],
    policy_payload: dict[str, Any],
    recent_manifest: dict[str, Any],
    train_sequences: list[dict[str, Any]],
    valid_rows: list[dict[str, Any]],
    test_rows: list[dict[str, Any]],
    train_stats: dict[str, Any],
    valid_stats: dict[str, Any],
    test_stats: dict[str, Any],
    sampling_policy: dict[str, Any],
) -> dict[str, Any]:
    variant_dir.mkdir(parents=True, exist_ok=True)
    train_item_universe = set(train_stats["item_support"])
    train_path = variant_dir / "user_sequences.train.jsonl"
    valid_path = variant_dir / "swing_valid_in_universe.jsonl"
    test_path = variant_dir / "swing_test_in_universe.jsonl"
    manifest_out_path = variant_dir / "manifest.json"
    stats_path = variant_dir / "stats.json"
    builder_manifest_path = variant_dir / "swing_builder_train_manifest.json"

    write_jsonl(train_path, train_sequences)
    write_jsonl(valid_path, valid_rows)
    write_jsonl(test_path, test_rows)

    stats_payload = {
        "schema_version": SCHEMA_VERSION,
        "variant": variant,
        "generated_at": generated_at,
        "source": source_payload,
        "policy": policy_payload,
        "sampling_policy": sampling_policy,
        "train_readiness": {
            "train_user_count": train_stats["user_count"],
            "train_item_count": len(train_item_universe),
            "train_positive_pair_count": train_stats["positive_pair_count"],
            "train_users_with_ge2_items": train_stats["users_with_ge2_items"],
            "train_ready_for_swing": train_stats["users_with_ge2_items"] > 0 and len(train_item_universe) > 1,
        },
        "support": {
            "train_user_support_histogram": dict(sorted(train_stats["user_support_histogram"].items())),
            "train_item_support_histogram": dict(sorted(_histogram(train_stats["item_support"].values()).items())),
            "valid": valid_stats,
            "test": test_stats,
        },
        "outputs": {
            "train": str(train_path),
            "valid": str(valid_path),
            "test": str(test_path),
            "builder_manifest_path": str(builder_manifest_path),
        },
    }
    manifest_payload = {
        "schema_version": SCHEMA_VERSION,
        "variant": variant,
        "generated_at": generated_at,
        "source_manifest_path": source_payload["recent_window_manifest_path"],
        "source_schema_version": recent_manifest.get("schema_version"),
        "output_dir": str(variant_dir),
        "primary_outputs": {
            "train": str(train_path),
            "valid": str(valid_path),
            "test": str(test_path),
        },
        "stats_path": str(stats_path),
        "builder_manifest_path": str(builder_manifest_path),
        "sampling_policy": sampling_policy,
        "counts": {
            "train": {
                "user_count": train_stats["user_count"],
                "item_count": len(train_item_universe),
                "positive_pair_count": train_stats["positive_pair_count"],
            },
            "valid": {
                "raw_positive_pair_count": valid_stats["raw_positive_pair_count"],
                "in_universe_pair_count": valid_stats["in_universe_pair_count"],
                "user_count": valid_stats["in_universe_user_count"],
                "item_count": valid_stats["in_universe_item_count"],
            },
            "test": {
                "raw_positive_pair_count": test_stats["raw_positive_pair_count"],
                "in_universe_pair_count": test_stats["in_universe_pair_count"],
                "user_count": test_stats["in_universe_user_count"],
                "item_count": test_stats["in_universe_item_count"],
            },
        },
    }
    builder_manifest = {
        "schema_version": BUILDER_SCHEMA_VERSION,
        "generated_at": generated_at,
        "train_user_sequences_path": str(train_path),
        "source_schema_version": recent_manifest.get("schema_version"),
        "metadata": {
            "method": "swing_recall",
            "variant": variant,
            "signal": "positive_only_label_binary",
            "dedup": "user_item_keep_earliest_timestamp",
            "sequence_order": "chronological",
            "train_user_count": train_stats["user_count"],
            "train_item_count": len(train_item_universe),
            "sample_count_caps": "none" if variant == "formal" else "deterministic_smoke_debug_subset",
        },
    }
    _validate_builder_manifest(builder_manifest)

    write_json(manifest_out_path, manifest_payload)
    write_json(stats_path, stats_payload)
    write_json(builder_manifest_path, builder_manifest)
    return {
        "manifest": manifest_payload,
        "stats": stats_payload,
        "builder_manifest": builder_manifest,
        "manifest_path": str(manifest_out_path),
        "stats_path": str(stats_path),
        "builder_manifest_path": str(builder_manifest_path),
    }


def _select_smoke_train_sequences(train_sequences: list[dict[str, Any]], max_users: int) -> list[dict[str, Any]]:
    return [dict(row) for row in sorted(train_sequences, key=lambda row: str(row["user_id"]))[:max_users]]


def _select_smoke_eval_rows(eval_rows: list[dict[str, Any]], smoke_item_universe: set[str], max_users: int) -> list[dict[str, Any]]:
    selected_users: set[str] = set()
    rows: list[dict[str, Any]] = []
    for row in sorted(eval_rows, key=lambda item: (str(item["user_id"]), int(item["timestamp"]), str(item["item_id"]))):
        user_id = str(row["user_id"])
        if row["item_id"] not in smoke_item_universe:
            continue
        if user_id not in selected_users and len(selected_users) >= max_users:
            continue
        selected_users.add(user_id)
        rows.append(dict(row))
    return rows


def _stats_from_train_sequences(rows: list[dict[str, Any]], *, skipped_non_positive_count: int, raw_positive_count: int) -> dict[str, Any]:
    item_support: Counter[str] = Counter()
    user_support_histogram: Counter[int] = Counter()
    users_with_ge2_items = 0
    positive_pair_count = 0
    for row in rows:
        item_ids = [str(item_id) for item_id in row["recent_positive_item_sequence"]]
        positive_pair_count += len(item_ids)
        user_support_histogram[len(item_ids)] += 1
        if len(item_ids) >= 2:
            users_with_ge2_items += 1
        for item_id in item_ids:
            item_support[item_id] += 1
    return {
        "raw_positive_count": raw_positive_count,
        "skipped_non_positive_count": skipped_non_positive_count,
        "user_count": len(rows),
        "positive_pair_count": positive_pair_count,
        "users_with_ge2_items": users_with_ge2_items,
        "user_support_histogram": user_support_histogram,
        "item_support": item_support,
    }


def _stats_from_eval_rows(
    rows: list[dict[str, Any]],
    *,
    raw_positive_pair_count: int,
    skipped_non_positive_count: int,
    filtered_out_of_universe_count: int,
) -> dict[str, Any]:
    users = {str(row["user_id"]) for row in rows}
    items = {str(row["item_id"]) for row in rows}
    return {
        "raw_positive_pair_count": raw_positive_pair_count,
        "skipped_non_positive_count": skipped_non_positive_count,
        "filtered_out_of_universe_count": filtered_out_of_universe_count,
        "in_universe_pair_count": len(rows),
        "in_universe_user_count": len(users),
        "in_universe_item_count": len(items),
        "user_support_histogram": dict(sorted(_histogram(Counter(str(row["user_id"]) for row in rows).values()).items())),
        "item_support_histogram": dict(sorted(_histogram(Counter(str(row["item_id"]) for row in rows).values()).items())),
    }


def _resolve_split_paths(manifest_path: Path, manifest: dict[str, Any]) -> dict[str, Path]:
    raw_split_paths = manifest.get("split_paths")
    if not isinstance(raw_split_paths, dict):
        raise ValueError("recent-window manifest must declare split_paths")
    missing = [split for split in ("train", "valid", "test") if not raw_split_paths.get(split)]
    if missing:
        raise ValueError("recent-window manifest missing split paths: " + ", ".join(missing))
    return {split: _resolve_path(manifest_path, str(raw_split_paths[split])) for split in ("train", "valid", "test")}


def _resolve_path(manifest_path: Path, raw_path: str) -> Path:
    path = Path(raw_path)
    if path.is_absolute():
        return path.resolve()
    root_candidate = (ROOT / path).resolve()
    if root_candidate.exists():
        return root_candidate
    return (manifest_path.parent / path).resolve()


def _load_train_sequences(path: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    by_user: dict[str, dict[str, int]] = defaultdict(dict)
    raw_positive_count = 0
    skipped_non_positive_count = 0
    for record in iter_jsonl(path):
        if not record.get("label_binary"):
            skipped_non_positive_count += 1
            continue
        raw_positive_count += 1
        user_id = str(record.get("user_id", ""))
        item_id = str(record.get("parent_asin", ""))
        if not user_id or not item_id:
            continue
        timestamp = int(record.get("timestamp", 0))
        existing = by_user[user_id].get(item_id)
        if existing is None or timestamp < existing:
            by_user[user_id][item_id] = timestamp

    rows: list[dict[str, Any]] = []
    item_support: Counter[str] = Counter()
    user_support_histogram: Counter[int] = Counter()
    users_with_ge2_items = 0
    for user_id in sorted(by_user):
        pairs = sorted(by_user[user_id].items(), key=lambda item: (item[1], item[0]))
        item_ids = [item_id for item_id, _ in pairs]
        timestamps = [timestamp for _, timestamp in pairs]
        for item_id in item_ids:
            item_support[item_id] += 1
        user_support_histogram[len(item_ids)] += 1
        if len(item_ids) >= 2:
            users_with_ge2_items += 1
        rows.append(
            {
                "user_id": user_id,
                "sequence_len": len(item_ids),
                "positive_sequence_len": len(item_ids),
                "recent_positive_item_sequence": item_ids,
                "recent_positive_timestamp_sequence": timestamps,
            }
        )

    return rows, {
        "raw_positive_count": raw_positive_count,
        "skipped_non_positive_count": skipped_non_positive_count,
        "user_count": len(rows),
        "positive_pair_count": sum(len(items) for items in by_user.values()),
        "users_with_ge2_items": users_with_ge2_items,
        "user_support_histogram": user_support_histogram,
        "item_support": item_support,
    }


def _load_eval_rows(path: Path, train_item_universe: set[str]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    dedup: dict[tuple[str, str], int] = {}
    raw_positive_count = 0
    skipped_non_positive_count = 0
    filtered_out_of_universe_count = 0
    for record in iter_jsonl(path):
        if not record.get("label_binary"):
            skipped_non_positive_count += 1
            continue
        raw_positive_count += 1
        user_id = str(record.get("user_id", ""))
        item_id = str(record.get("parent_asin", ""))
        if not user_id or not item_id:
            continue
        if item_id not in train_item_universe:
            filtered_out_of_universe_count += 1
            continue
        timestamp = int(record.get("timestamp", 0))
        key = (user_id, item_id)
        existing = dedup.get(key)
        if existing is None or timestamp < existing:
            dedup[key] = timestamp

    rows = [
        {"user_id": user_id, "item_id": item_id, "timestamp": timestamp, "label": 1}
        for (user_id, item_id), timestamp in sorted(dedup.items(), key=lambda item: (item[0][0], item[1], item[0][1]))
    ]
    stats = _stats_from_eval_rows(
        rows,
        raw_positive_pair_count=raw_positive_count,
        skipped_non_positive_count=skipped_non_positive_count,
        filtered_out_of_universe_count=filtered_out_of_universe_count,
    )
    return rows, stats


def _histogram(values) -> Counter[int]:
    return Counter(int(value) for value in values)


def _validate_builder_manifest(payload: dict[str, Any]) -> None:
    _walk_forbidden_builder_keys(payload)
    train_path = Path(str(payload["train_user_sequences_path"]))
    lowered_parts = {part.lower() for part in train_path.parts}
    forbidden_parts = lowered_parts & FORBIDDEN_BUILDER_PATH_PARTS
    if forbidden_parts:
        raise ValueError("Forbidden Swing builder path parts: " + ", ".join(sorted(forbidden_parts)))


def _walk_forbidden_builder_keys(value: Any, prefix: str = "") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            key_text = str(key)
            if key_text in FORBIDDEN_BUILDER_KEYS:
                raise ValueError(f"Forbidden Swing builder manifest key: {prefix}{key_text}")
            _walk_forbidden_builder_keys(child, f"{prefix}{key_text}.")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _walk_forbidden_builder_keys(child, f"{prefix}{index}.")


def _file_signature(path: Path) -> dict[str, Any]:
    digest = hashlib.sha256()
    rows = 0
    with path.open("rb") as handle:
        for line in handle:
            if line.strip():
                rows += 1
            digest.update(line)
    return {"path": str(path), "size_bytes": path.stat().st_size, "row_count": rows, "sha256": digest.hexdigest()}


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    args = parse_args()
    outputs = build_sciomc_swing_recent2y_preprocess(
        recent_window_manifest_path=args.recent_window_manifest,
        output_dir=args.output_dir,
        smoke_train_users=args.smoke_train_users,
        smoke_eval_users=args.smoke_eval_users,
        enforce_venv=not args.skip_venv_check,
        overwrite=args.overwrite,
    )
    print(f"Root manifest written to: {outputs['manifest_path']}")
    for variant, payload in outputs["variants"].items():
        manifest = payload["manifest"]
        print(f"{variant} manifest written to: {payload['manifest_path']}")
        print(f"{variant} stats written to: {payload['stats_path']}")
        print(f"{variant} builder manifest written to: {payload['builder_manifest_path']}")
        print(f"{variant} train rows: {manifest['counts']['train']['user_count']}")
        print(f"{variant} valid in-universe rows: {manifest['counts']['valid']['in_universe_pair_count']}")
        print(f"{variant} test in-universe rows: {manifest['counts']['test']['in_universe_pair_count']}")


if __name__ == "__main__":
    main()
