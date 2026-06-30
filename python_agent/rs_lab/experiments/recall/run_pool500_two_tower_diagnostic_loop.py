from __future__ import annotations

import argparse
import json
import shutil
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rs_core.common.io import iter_jsonl, read_json, write_json, write_jsonl
from rs_core.common.runtime import enforce_project_venv
from rs_core.online.recall.vector_index import dot_score
from rs_core.workflow.two_tower_training import train_two_tower_recall
from scripts.recall.build_two_tower_source_index import build_two_tower_source_index

SCHEMA_VERSION = "pool500_two_tower_diagnostic_loop_v1"
DEFAULT_METHOD_DATASET_MANIFEST = ROOT / "outputs" / "recall" / "pool500_method_datasets" / "two_tower" / "train_only_v1" / "method_dataset_manifest.json"
DEFAULT_OUTPUT_DIR = ROOT / "outputs" / "recall" / "pool500_two_tower_diagnostic_loop"
GUARD_FLAGS = {
    "diagnostic_only": True,
    "candidate_generation_allowed": False,
    "ranking_input_replacement_allowed": False,
    "promotion_allowed": False,
    "final_pool500_ready_claimed": False,
}
LEAKAGE_CHECKS = {"train_inputs_only": True, "eval_paths_rejected": True}
FORBIDDEN_INPUT_PATH_TOKENS = {"eval", "oracle", "label", "valid", "validation", "test", "holdout"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a bounded train-only TwoTower diagnostic loop from P2 method dataset artifacts.")
    parser.add_argument("--method-dataset-manifest", default=str(DEFAULT_METHOD_DATASET_MANIFEST))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--limit-users", type=int, default=200)
    parser.add_argument("--top-k", type=int, default=50)
    parser.add_argument("--metric-ks", default="20,50")
    parser.add_argument("--embedding-dim", type=int, default=16)
    parser.add_argument("--hidden-dim", type=int, default=16)
    parser.add_argument("--epochs", type=int, default=1)
    parser.add_argument("--negative-samples", type=int, default=3)
    parser.add_argument("--batch-size", type=int, default=128)
    parser.add_argument("--gradient-accumulation-steps", type=int, default=1)
    parser.add_argument("--mixed-precision", action="store_true")
    parser.add_argument("--min-user-positives", type=int, default=3)
    parser.add_argument("--max-samples-per-user", type=int, default=5)
    parser.add_argument("--negative-sampling-power", type=float, default=0.75)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--skip-venv-check", action="store_true")
    return parser.parse_args()


def run_pool500_two_tower_diagnostic_loop(
    *,
    method_dataset_manifest_path: Path = DEFAULT_METHOD_DATASET_MANIFEST,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    limit_users: int = 200,
    top_k: int = 50,
    metric_ks: Iterable[int] = (20, 50),
    embedding_dim: int = 16,
    hidden_dim: int = 16,
    epochs: int = 1,
    negative_samples: int = 3,
    batch_size: int = 128,
    gradient_accumulation_steps: int = 1,
    mixed_precision: bool = False,
    min_user_positives: int = 3,
    max_samples_per_user: int = 5,
    negative_sampling_power: float = 0.75,
    overwrite: bool = False,
    enforce_venv: bool = True,
) -> dict[str, Any]:
    if enforce_venv:
        enforce_project_venv(ROOT)
    if limit_users <= 0:
        raise ValueError("limit_users must be positive")
    if top_k <= 0:
        raise ValueError("top_k must be positive")
    metric_ks = _parse_metric_ks(metric_ks)
    if max(metric_ks) > top_k:
        raise ValueError("top_k must be >= max(metric_ks)")

    method_dataset_manifest_path = method_dataset_manifest_path.resolve()
    output_dir = output_dir.resolve()
    _precheck_output_dir(output_dir, overwrite)
    method_manifest = _load_method_dataset_manifest(method_dataset_manifest_path)
    outputs = _resolve_method_outputs(method_dataset_manifest_path, method_manifest)
    _reject_forbidden_method_dataset_input_paths(method_dataset_manifest_path, method_manifest, outputs)

    if output_dir.exists() and overwrite:
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=False)

    compatibility_dir = output_dir / "train_only_compat_inputs"
    clean_dir = compatibility_dir / "clean"
    item_vocab_path = compatibility_dir / "two_tower_item_vocab.jsonl"
    item_vocab_manifest_path = compatibility_dir / "two_tower_item_vocab_manifest.json"
    canonical_interactions_train_path = compatibility_dir / "canonical_interactions.train.jsonl"
    train_config_path = compatibility_dir / "two_tower_train_config.json"
    training_run_dir = output_dir / "training_run"
    source_dir = output_dir / "source_index"
    source_manifest_path = source_dir / "source_index_manifest.json"
    topk_path = output_dir / "diagnostic_topk.jsonl"
    metrics_path = output_dir / "diagnostic_metrics.json"
    manifest_path = output_dir / "diagnostic_manifest.json"
    report_path = output_dir / "diagnostic_report.json"

    sample_rows = _load_limited_samples(outputs["two_tower_train_samples"], limit_users)
    if not sample_rows:
        raise ValueError("P2 method dataset produced no train samples for diagnostic loop")
    sequences = _sample_rows_to_sequences(sample_rows)
    _write_canonical_interactions(sample_rows, canonical_interactions_train_path)
    item_count = _write_item_vocab(outputs["training_item_universe"], item_vocab_path, sample_rows)
    write_json(
        item_vocab_manifest_path,
        {
            "schema_version": "two_tower_item_vocab_v1",
            "item_vocab_path": str(item_vocab_path),
            "item_count": item_count,
            "metadata_join_added_items": False,
            "source_paths": {
                "canonical_interactions_train": str(canonical_interactions_train_path),
                "p2_training_item_universe": str(outputs["training_item_universe"]),
            },
            "diagnostic_only": True,
            "split_scope": "train_only",
            "leakage_checks": LEAKAGE_CHECKS,
        },
    )
    write_jsonl(clean_dir / "user_sequences.train.jsonl", sequences)
    write_json(
        train_config_path,
        {
            "clean_dir": str(clean_dir),
            "evaluation_mode": "train_only",
            "two_tower_training": {
                "variant": "youtube_dnn",
                "source_name": "two_tower_youtube_dnn",
                "embedding_dim": embedding_dim,
                "hidden_dim": hidden_dim,
                "epochs": epochs,
                "negative_samples": negative_samples,
                "batch_size": batch_size,
                "gradient_accumulation_steps": gradient_accumulation_steps,
                "mixed_precision": mixed_precision,
                "sequence_keys": ["recent_positive_item_sequence"],
                "min_user_positives": min_user_positives,
                "max_samples_per_user": max_samples_per_user,
                "negative_sampling_power": negative_sampling_power,
            },
        },
    )

    training_result = train_two_tower_recall(
        train_config_path,
        output_dir=training_run_dir,
        limit_users=limit_users,
        variant="youtube_dnn",
        item_vocab_manifest=item_vocab_manifest_path,
    )
    source_manifest = build_two_tower_source_index(
        training_run_dir=training_run_dir,
        item_vocab_manifest=item_vocab_manifest_path,
        output_dir=source_dir,
        output_source_manifest=source_manifest_path,
        overwrite=True,
    )
    topk_rows, metrics = _write_diagnostic_topk_and_metrics(
        user_embeddings_path=Path(training_result["user_embeddings_path"]),
        item_embeddings_path=Path(training_result["item_embeddings_path"]),
        sample_rows=sample_rows,
        output_path=topk_path,
        top_k=top_k,
        metric_ks=metric_ks,
    )
    write_json(metrics_path, metrics)
    training_backend = training_result["metrics"].get("training_backend", {})
    if not isinstance(training_backend, dict):
        training_backend = {}

    report = {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS",
        "created_at": datetime.now(timezone.utc).isoformat(),
        **GUARD_FLAGS,
        "split_scope": "train_only",
        "leakage_checks": LEAKAGE_CHECKS,
        "method_dataset_manifest_path": str(method_dataset_manifest_path),
        "training_artifact_manifest_path": str(training_result["artifact_manifest_path"]),
        "source_index_manifest_path": str(source_manifest_path),
        "diagnostic_manifest_path": str(manifest_path),
        "diagnostic_report_path": str(report_path),
        "diagnostic_topk_path": str(topk_path),
        "diagnostic_metrics_path": str(metrics_path),
        "training_metrics_path": str(training_result["train_metrics_path"]),
        "source_index_row_count": source_manifest["row_count"],
        "diagnostic_topk_row_count": topk_rows,
        "training": {
            "variant": "youtube_dnn",
            "limit_users": limit_users,
            "embedding_dim": embedding_dim,
            "hidden_dim": hidden_dim,
            "epochs": epochs,
            "negative_samples": negative_samples,
            "batch_size": batch_size,
            "gradient_accumulation_steps": gradient_accumulation_steps,
            "effective_batch_size": training_result["metrics"].get("effective_batch_size", batch_size * max(1, gradient_accumulation_steps)),
            "mixed_precision": mixed_precision,
            "mixed_precision_enabled": training_backend.get("mixed_precision_enabled", False),
            "optimizer_steps": training_backend.get("optimizer_steps"),
            "min_user_positives": min_user_positives,
            "max_samples_per_user": max_samples_per_user,
            "negative_sampling_power": negative_sampling_power,
            "training_input_users": training_result["metrics"].get("training_input_users"),
            "users_with_training_rows": training_result["metrics"].get("users_with_training_rows"),
        },
        "retrieval_metrics": metrics,
        "offline_eval_helpers_reused": [],
        "offline_eval_helpers_not_run_reason": "diagnostic loop stays train_only and uses local metric cutoff parsing without touching label/oracle/challenger paths",
        "no_oracle_label_injection": True,
    }
    write_json(manifest_path, report)
    write_json(report_path, report)
    return report


def _precheck_output_dir(output_dir: Path, overwrite: bool) -> None:
    if output_dir.exists() and any(output_dir.iterdir()) and not overwrite:
        raise FileExistsError(f"Output directory already exists and is non-empty: {output_dir}")


def _parse_metric_ks(values: Iterable[int] | str) -> list[int]:
    if isinstance(values, str):
        raw_values = [value.strip() for value in values.split(",") if value.strip()]
    else:
        raw_values = list(values)
    metric_ks = sorted({int(value) for value in raw_values})
    if not metric_ks or any(k <= 0 for k in metric_ks):
        raise ValueError("--metric-ks must contain positive integer cutoffs")
    return metric_ks



def _load_method_dataset_manifest(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(path)
    manifest = read_json(path)
    if manifest.get("schema_version") != "pool500_two_tower_method_dataset_v1":
        raise ValueError("expected pool500_two_tower_method_dataset_v1 manifest")
    if manifest.get("train_only") is not True:
        raise ValueError("method dataset manifest must be train_only")
    boundary = manifest.get("data_usage_boundary") if isinstance(manifest.get("data_usage_boundary"), dict) else {}
    if boundary.get("diagnostic_only") is not True:
        raise ValueError("method dataset must declare diagnostic_only boundary")
    for field, expected in GUARD_FLAGS.items():
        if field == "diagnostic_only":
            continue
        for source in (manifest, boundary):
            if field in source and source.get(field) is not expected:
                raise ValueError(f"method dataset guard mismatch: {field}")
        if manifest.get(field) is not expected and boundary.get(field) is not expected:
            raise ValueError(f"method dataset guard mismatch: {field}")
    return manifest


def _resolve_method_outputs(manifest_path: Path, manifest: dict[str, Any]) -> dict[str, Path]:
    outputs = manifest.get("outputs") if isinstance(manifest.get("outputs"), dict) else {}
    required = ("two_tower_train_samples", "training_item_universe")
    resolved = {}
    for key in required:
        value = outputs.get(key)
        if not value:
            raise ValueError(f"method dataset outputs missing {key}")
        path = Path(str(value))
        candidates = [path] if path.is_absolute() else [manifest_path.parent / path, ROOT / path]
        for candidate in candidates:
            if candidate.is_file():
                resolved[key] = candidate.resolve()
                break
        else:
            raise FileNotFoundError(str(value))
    return resolved


def _reject_forbidden_method_dataset_input_paths(manifest_path: Path, manifest: dict[str, Any], outputs: dict[str, Path]) -> None:
    path_values = [("method_dataset_manifest_path", str(manifest_path)), *[(f"outputs.{key}", str(path)) for key, path in outputs.items()]]
    for key, value in _path_like_manifest_values(manifest):
        path_values.append((key, value))
    matches = [(key, value) for key, value in path_values if _has_forbidden_input_path_token(value)]
    if matches:
        preview = [{"field": key, "path": value} for key, value in matches[:10]]
        raise ValueError(f"forbidden method dataset input path detected: {preview}")


def _path_like_manifest_values(value: Any, prefix: str = "manifest"):
    if isinstance(value, dict):
        for key, nested in value.items():
            yield from _path_like_manifest_values(nested, f"{prefix}.{key}")
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            yield from _path_like_manifest_values(nested, f"{prefix}[{index}]")
    elif isinstance(value, (str, Path)):
        text = str(value)
        if _looks_like_input_path(text):
            yield prefix, text


def _looks_like_input_path(value: str) -> bool:
    normalized = value.replace("\\", "/")
    return "/" in normalized or normalized.endswith((".json", ".jsonl", ".parquet", ".npy", ".faiss"))


def _has_forbidden_input_path_token(value: str) -> bool:
    normalized = value.replace("\\", "/").lower()
    path_parts = [part for part in normalized.split("/") if part]
    filename_stems = [Path(part).stem for part in path_parts if "." in part]
    tokens = set(path_parts) | set(filename_stems)
    return bool(tokens & FORBIDDEN_INPUT_PATH_TOKENS)


def _load_limited_samples(path: Path, limit_users: int) -> list[dict[str, Any]]:
    rows = []
    users = set()
    for row in iter_jsonl(path):
        user_id = str(row.get("user_id") or "")
        if not user_id:
            continue
        if user_id not in users and len(users) >= limit_users:
            break
        users.add(user_id)
        rows.append(row)
    return rows


def _sample_rows_to_sequences(samples: list[dict[str, Any]]) -> list[dict[str, Any]]:
    positives_by_user: dict[str, list[str]] = defaultdict(list)
    for row in samples:
        user_id = str(row.get("user_id") or "")
        if not user_id:
            continue
        for item_id in [*row.get("history_items", []), row.get("target_item") or row.get("positive_item_id")]:
            if item_id and str(item_id) not in positives_by_user[user_id]:
                positives_by_user[user_id].append(str(item_id))
    return [{"user_id": user_id, "recent_positive_item_sequence": items, "recent_item_sequence": items} for user_id, items in sorted(positives_by_user.items()) if items]


def _write_canonical_interactions(samples: list[dict[str, Any]], output_path: Path) -> None:
    rows = []
    for row in samples:
        user_id = str(row.get("user_id") or "")
        item_id = str(row.get("target_item") or row.get("positive_item_id") or "")
        if user_id and item_id:
            rows.append({"user_id": user_id, "parent_asin": item_id, "event_type": "train_positive"})
    if not rows:
        raise ValueError("P2 samples produced no canonical train interactions")
    write_jsonl(output_path, rows)


def _write_item_vocab(training_item_universe_path: Path, output_path: Path, sample_rows: list[dict[str, Any]]) -> int:
    required_items = _diagnostic_item_ids(sample_rows)
    rows = []
    seen = set()
    for row in iter_jsonl(training_item_universe_path):
        item_id = str(row.get("parent_asin") or row.get("item_id") or "")
        if not item_id or item_id in seen or item_id not in required_items:
            continue
        seen.add(item_id)
        rows.append(
            {
                "parent_asin": item_id,
                "item_id": item_id,
                "title_clean": str(row.get("title_clean") or ""),
                "main_category": str(row.get("main_category") or ""),
                "category": str(row.get("category") or ""),
            }
        )
        if len(seen) == len(required_items):
            break
    if not rows:
        raise ValueError("training_item_universe did not cover diagnostic sampled target/history items")
    write_jsonl(output_path, rows)
    return len(rows)


def _diagnostic_item_ids(sample_rows: list[dict[str, Any]]) -> set[str]:
    item_ids = set()
    for row in sample_rows:
        for item_id in [*row.get("history_items", []), row.get("target_item") or row.get("positive_item_id")]:
            if item_id:
                item_ids.add(str(item_id))
    return item_ids


def _write_diagnostic_topk_and_metrics(
    *,
    user_embeddings_path: Path,
    item_embeddings_path: Path,
    sample_rows: list[dict[str, Any]],
    output_path: Path,
    top_k: int,
    metric_ks: list[int],
) -> tuple[int, dict[str, Any]]:
    users = _embedding_map(user_embeddings_path, "user_id")
    items = _embedding_map(item_embeddings_path, "item_id")
    targets_by_user = _targets_by_user(sample_rows)
    in_universe_targets_by_user = {user_id: {item_id for item_id in targets if item_id in items} for user_id, targets in targets_by_user.items()}
    ranked_by_user: dict[str, list[str]] = {}
    rows = []
    for user_id in sorted(targets_by_user):
        user_vector = users.get(user_id)
        if user_vector is None:
            ranked_by_user[user_id] = []
            continue
        scored = sorted(((dot_score(user_vector, item_vector), item_id) for item_id, item_vector in items.items()), key=lambda pair: (-pair[0], pair[1]))[:top_k]
        ranked_by_user[user_id] = [item_id for _, item_id in scored]
        for rank, (score, item_id) in enumerate(scored, start=1):
            rows.append({"user_id": user_id, "item_id": item_id, "rank": rank, "score": round(score, 8), "source": "two_tower_diagnostic", "sources": ["two_tower_diagnostic"]})
    write_jsonl(output_path, rows)
    return len(rows), _diagnostic_metrics(targets_by_user, in_universe_targets_by_user, ranked_by_user, metric_ks)


def _embedding_map(path: Path, id_key: str) -> dict[str, list[float]]:
    rows = {}
    for row in iter_jsonl(path):
        row_id = str(row.get(id_key) or row.get("parent_asin") or "")
        vector = row.get("embedding") or row.get("vector")
        if row_id and isinstance(vector, list):
            rows[row_id] = [float(value) for value in vector]
    return rows


def _targets_by_user(samples: list[dict[str, Any]]) -> dict[str, set[str]]:
    targets: dict[str, set[str]] = defaultdict(set)
    for row in samples:
        user_id = str(row.get("user_id") or "")
        item_id = str(row.get("target_item") or row.get("positive_item_id") or "")
        if user_id and item_id:
            targets[user_id].add(item_id)
    return dict(targets)


def _diagnostic_metrics(targets_by_user: dict[str, set[str]], in_universe_targets_by_user: dict[str, set[str]], ranked_by_user: dict[str, list[str]], metric_ks: list[int]) -> dict[str, Any]:
    user_ids = sorted(targets_by_user)
    payload: dict[str, Any] = {
        "schema_version": f"{SCHEMA_VERSION}.metrics",
        "metric_ks": metric_ks,
        "user_count": len(user_ids),
        "all_target_denominator": sum(len(targets_by_user[user_id]) for user_id in user_ids),
        "in_universe_target_denominator": sum(len(in_universe_targets_by_user[user_id]) for user_id in user_ids),
    }
    for k in metric_ks:
        all_hits = 0
        in_universe_hits = 0
        hit_users = 0
        in_universe_hit_users = 0
        for user_id in user_ids:
            top_items = set(ranked_by_user.get(user_id, [])[:k])
            user_all_hits = len(targets_by_user[user_id] & top_items)
            user_in_universe_hits = len(in_universe_targets_by_user[user_id] & top_items)
            all_hits += user_all_hits
            in_universe_hits += user_in_universe_hits
            hit_users += int(user_all_hits > 0)
            in_universe_hit_users += int(user_in_universe_hits > 0)
        all_denominator = int(payload["all_target_denominator"])
        in_universe_denominator = int(payload["in_universe_target_denominator"])
        payload[f"all_target_recall_at_{k}"] = round(all_hits / all_denominator, 6) if all_denominator else 0.0
        payload[f"in_universe_recall_at_{k}"] = round(in_universe_hits / in_universe_denominator, 6) if in_universe_denominator else 0.0
        payload[f"all_target_hit_rate_at_{k}"] = round(hit_users / len(user_ids), 6) if user_ids else 0.0
        payload[f"in_universe_hit_rate_at_{k}"] = round(in_universe_hit_users / len(user_ids), 6) if user_ids else 0.0
    return payload


def main() -> None:
    args = parse_args()
    report = run_pool500_two_tower_diagnostic_loop(
        method_dataset_manifest_path=Path(args.method_dataset_manifest),
        output_dir=Path(args.output_dir),
        limit_users=args.limit_users,
        top_k=args.top_k,
        metric_ks=args.metric_ks,
        embedding_dim=args.embedding_dim,
        hidden_dim=args.hidden_dim,
        epochs=args.epochs,
        negative_samples=args.negative_samples,
        batch_size=args.batch_size,
        gradient_accumulation_steps=args.gradient_accumulation_steps,
        mixed_precision=args.mixed_precision,
        min_user_positives=args.min_user_positives,
        max_samples_per_user=args.max_samples_per_user,
        negative_sampling_power=args.negative_sampling_power,
        overwrite=args.overwrite,
        enforce_venv=not args.skip_venv_check,
    )
    print(json.dumps({"status": report["status"], "diagnostic_manifest_path": str(Path(args.output_dir) / "diagnostic_manifest.json"), "diagnostic_report_path": str(Path(args.output_dir) / "diagnostic_report.json")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
