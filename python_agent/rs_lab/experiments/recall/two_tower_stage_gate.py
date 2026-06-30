from __future__ import annotations

import argparse
import math
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from rs_core.common.io import read_json, write_json

SCHEMA_VERSION = "two_tower_stage_gate_v1"
STAGES = {"1k", "5k", "10k", "20k"}
GIB = 1024**3

DEFAULT_THRESHOLDS: dict[str, dict[str, Any]] = {
    "1k": {
        "sample_count_min": 1,
        "loss_must_be_finite": True,
        "variant": "youtube_dnn",
        "train_inputs_only": True,
        "eval_paths_rejected": True,
        "direct_artifact_load_blocked": True,
    },
    "5k": {
        "peak_cuda_memory_mb_max": 10000,
        "peak_rss_mb_max": 24576,
        "free_disk_gib_after_stage_min": 50,
        "training_seconds_per_epoch_max": 90 * 60,
        "negative_sampling_ratio_max": 0.4,
    },
    "10k": {
        "row_counts_must_match": True,
        "candidate_generation_qps_min": 5,
        "underfilled_user_rate_max": 0.2,
        "embedding_index_size_gib_max": 40,
        "single_generation_elapsed_seconds_max": 4 * 60 * 60,
    },
    "20k": {
        "hit_at_500_non_degradation": True,
        "raw_two_tower_unique_positive_hits_min": 1,
        "marginal_unique_positive_hits_min": 1,
    },
}


def build_two_tower_stage_gate_manifest(
    *,
    stage: str,
    training_run_dir: str | Path,
    output_path: str | Path,
    metrics_manifest: str | Path | None = None,
    source_index_manifest: str | Path | None = None,
    raw_eval_manifest: str | Path | None = None,
    ablation_manifest: str | Path | None = None,
    previous_gate_manifest: str | Path | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    if stage not in STAGES:
        raise ValueError(f"stage must be one of {sorted(STAGES)}")
    ensure_stage_not_blocked(stage=stage, previous_gate_manifest=previous_gate_manifest)

    output = Path(output_path).resolve()
    if output.exists() and not overwrite:
        raise ValueError(f"output already exists; pass --overwrite to replace: {output}")

    training_dir = Path(training_run_dir).resolve()
    metrics = _collect_metrics(training_dir, metrics_manifest)
    source_manifest = _read_optional(source_index_manifest)
    raw_eval = _read_optional(raw_eval_manifest)
    ablation = _read_optional(ablation_manifest)
    metrics.update(_source_index_metrics(source_manifest))
    metrics.update(_raw_eval_metrics(raw_eval))
    metrics.update(_ablation_metrics(ablation))

    thresholds = dict(DEFAULT_THRESHOLDS[stage])
    failure_reasons = _evaluate_stage(stage, metrics, thresholds)
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "created_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "stage": stage,
        "status": "PASS" if not failure_reasons else "STOP",
        "training_run_dir": str(training_dir),
        "source_index_manifest": str(Path(source_index_manifest).resolve()) if source_index_manifest else None,
        "raw_eval_manifest": str(Path(raw_eval_manifest).resolve()) if raw_eval_manifest else None,
        "ablation_manifest": str(Path(ablation_manifest).resolve()) if ablation_manifest else None,
        "previous_gate_manifest": str(Path(previous_gate_manifest).resolve()) if previous_gate_manifest else None,
        "metrics": metrics,
        "thresholds": thresholds,
        "failure_reasons": failure_reasons,
    }
    write_json(output, manifest)
    return manifest


def ensure_stage_not_blocked(*, stage: str, previous_gate_manifest: str | Path | None) -> None:
    if stage != "20k" or previous_gate_manifest is None:
        return
    previous = read_json(previous_gate_manifest)
    if previous.get("stage") == "10k" and previous.get("status") == "STOP":
        reasons = previous.get("failure_reasons") or []
        detail = "; ".join(str(reason) for reason in reasons) or "10k gate status is STOP"
        raise RuntimeError(f"20k stage blocked by 10k STOP manifest: {detail}")


def _collect_metrics(training_run_dir: Path, metrics_manifest: str | Path | None) -> dict[str, Any]:
    metrics: dict[str, Any] = _default_metrics()
    if metrics_manifest is not None:
        metrics.update(read_json(metrics_manifest))
    for filename in ("train_metrics.json", "two_tower_train_dataset_manifest.json", "negative_sampling_manifest.json"):
        path = training_run_dir / filename
        if path.exists():
            _merge_known_metrics(metrics, read_json(path))
    return metrics


def _merge_known_metrics(metrics: dict[str, Any], payload: dict[str, Any]) -> None:
    for key in metrics:
        if key in payload:
            metrics[key] = payload[key]
    if "total_sample_count" in payload:
        metrics["sample_count"] = payload["total_sample_count"]
    if "elapsed_seconds" in payload and "negative_sampling" in str(payload.get("schema_version", "")):
        metrics["negative_sampling_seconds"] = payload["elapsed_seconds"]
    if "elapsed_ratio_of_training" in payload:
        metrics["negative_sampling_ratio"] = payload["elapsed_ratio_of_training"]
    leakage_checks = payload.get("leakage_checks")
    if isinstance(leakage_checks, dict):
        for key in ("train_inputs_only", "eval_paths_rejected"):
            if key in leakage_checks:
                metrics[key] = leakage_checks[key]


def _source_index_metrics(manifest: dict[str, Any] | None) -> dict[str, Any]:
    if manifest is None:
        return {}
    row_count = manifest.get("row_count")
    embedding_row_count = manifest.get("embedding_row_count", manifest.get("item_embedding_row_count"))
    index_row_count = manifest.get("index_row_count", manifest.get("recall_index_row_count"))
    item_vocab_count = manifest.get("item_vocab_count", row_count)
    embedding_bytes = manifest.get("item_embeddings_bytes", manifest.get("embedding_bytes", 0))
    index_bytes = manifest.get("recall_index_bytes", manifest.get("index_bytes", 0))
    artifact_size_gib = manifest.get("artifact_size_gib")
    if artifact_size_gib is not None and not embedding_bytes and not index_bytes:
        embedding_bytes = float(artifact_size_gib) * GIB
    return {
        "row_count": row_count,
        "embedding_row_count": embedding_row_count,
        "index_row_count": index_row_count,
        "item_vocab_count": item_vocab_count,
        "item_embeddings_bytes": embedding_bytes,
        "recall_index_bytes": index_bytes,
    }


def _raw_eval_metrics(manifest: dict[str, Any] | None) -> dict[str, Any]:
    if manifest is None:
        return {}
    return {
        "candidate_generation_qps": manifest.get("candidate_generation_qps", 0),
        "underfilled_user_rate": manifest.get("underfilled_user_rate", 0),
        "single_generation_elapsed_seconds": manifest.get("single_generation_elapsed_seconds", 0),
    }


def _ablation_metrics(manifest: dict[str, Any] | None) -> dict[str, Any]:
    if manifest is None:
        return {}
    without_metrics = manifest.get("without_two_tower") or {}
    with_metrics = manifest.get("with_two_tower") or {}
    return {
        "without_two_tower_hit_at_500": without_metrics.get("hit_at_500"),
        "with_two_tower_hit_at_500": with_metrics.get("hit_at_500"),
        "raw_two_tower_unique_positive_hits": manifest.get("raw_two_tower_unique_positive_hits", 0),
        "marginal_unique_positive_hits": manifest.get("marginal_unique_positive_hits", 0),
    }


def _evaluate_stage(stage: str, metrics: dict[str, Any], thresholds: dict[str, Any]) -> list[str]:
    checks = {
        "1k": _evaluate_1k,
        "5k": _evaluate_5k,
        "10k": _evaluate_10k,
        "20k": _evaluate_20k,
    }
    return checks[stage](metrics, thresholds)


def _evaluate_1k(metrics: dict[str, Any], thresholds: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    if _number(metrics.get("sample_count")) < thresholds["sample_count_min"]:
        failures.append("sample_count must be > 0")
    if metrics.get("variant") != thresholds["variant"]:
        failures.append("variant must be youtube_dnn")
    for key in ("train_inputs_only", "eval_paths_rejected", "direct_artifact_load_blocked"):
        if metrics.get(key) is not thresholds[key]:
            failures.append(f"{key} must be {thresholds[key]}")
    losses = metrics.get("loss_history") or []
    if not losses:
        failures.append("loss_history must be present")
    elif any(not math.isfinite(_number(loss)) for loss in losses):
        failures.append("loss_history must not contain NaN or infinite values")
    return failures


def _evaluate_5k(metrics: dict[str, Any], thresholds: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    _max_check(failures, metrics, thresholds, "peak_cuda_memory_mb", "peak_cuda_memory_mb_max")
    _max_check(failures, metrics, thresholds, "peak_rss_mb", "peak_rss_mb_max")
    _min_check(failures, metrics, thresholds, "free_disk_gib_after_stage", "free_disk_gib_after_stage_min")
    seconds_per_epoch = metrics.get("training_seconds_per_epoch")
    if seconds_per_epoch is None:
        epochs = max(_number(metrics.get("epochs")), 1.0)
        seconds_per_epoch = _number(metrics.get("training_seconds")) / epochs
        metrics["training_seconds_per_epoch"] = seconds_per_epoch
    if _number(seconds_per_epoch) > thresholds["training_seconds_per_epoch_max"]:
        failures.append("training_seconds_per_epoch exceeds threshold")
    ratio = metrics.get("negative_sampling_ratio")
    if ratio is None:
        training_seconds = _number(metrics.get("training_seconds"))
        ratio = _number(metrics.get("negative_sampling_seconds")) / training_seconds if training_seconds > 0 else math.inf
        metrics["negative_sampling_ratio"] = ratio
    if _number(ratio) > thresholds["negative_sampling_ratio_max"]:
        failures.append("negative_sampling_ratio exceeds threshold")
    return failures


def _evaluate_10k(metrics: dict[str, Any], thresholds: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    row_counts = [metrics.get("row_count"), metrics.get("embedding_row_count"), metrics.get("index_row_count"), metrics.get("item_vocab_count")]
    if any(value is None for value in row_counts) or len({int(_number(value)) for value in row_counts}) != 1:
        failures.append("row counts must match item vocab, embedding, and index counts")
    _min_check(failures, metrics, thresholds, "candidate_generation_qps", "candidate_generation_qps_min")
    _max_check(failures, metrics, thresholds, "underfilled_user_rate", "underfilled_user_rate_max")
    size_gib = (_number(metrics.get("item_embeddings_bytes")) + _number(metrics.get("recall_index_bytes"))) / GIB
    metrics["embedding_index_size_gib"] = size_gib
    if size_gib > thresholds["embedding_index_size_gib_max"]:
        failures.append("embedding_index_size_gib exceeds threshold")
    _max_check(failures, metrics, thresholds, "single_generation_elapsed_seconds", "single_generation_elapsed_seconds_max")
    return failures


def _evaluate_20k(metrics: dict[str, Any], thresholds: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    if _number(metrics.get("with_two_tower_hit_at_500")) < _number(metrics.get("without_two_tower_hit_at_500")):
        failures.append("with_two_tower hit_at_500 must not degrade from without_two_tower")
    _min_check(failures, metrics, thresholds, "raw_two_tower_unique_positive_hits", "raw_two_tower_unique_positive_hits_min")
    _min_check(failures, metrics, thresholds, "marginal_unique_positive_hits", "marginal_unique_positive_hits_min")
    return failures


def _min_check(failures: list[str], metrics: dict[str, Any], thresholds: dict[str, Any], metric_key: str, threshold_key: str) -> None:
    if _number(metrics.get(metric_key)) < _number(thresholds.get(threshold_key)):
        failures.append(f"{metric_key} below threshold")


def _max_check(failures: list[str], metrics: dict[str, Any], thresholds: dict[str, Any], metric_key: str, threshold_key: str) -> None:
    if _number(metrics.get(metric_key)) > _number(thresholds.get(threshold_key)):
        failures.append(f"{metric_key} exceeds threshold")


def _number(value: Any) -> float:
    if value is None:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _read_optional(path: str | Path | None) -> dict[str, Any] | None:
    return read_json(path) if path else None


def _default_metrics() -> dict[str, Any]:
    return {
        "loss_history": [],
        "sample_count": 0,
        "item_vocab_size": 0,
        "negative_sampling_seconds": 0,
        "training_seconds": 0,
        "peak_cuda_memory_mb": 0,
        "peak_rss_mb": 0,
        "free_disk_gib_after_stage": 0,
        "item_embeddings_bytes": 0,
        "recall_index_bytes": 0,
        "candidate_generation_qps": 0,
        "underfilled_user_rate": 0.0,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build two_tower staged gate manifest")
    parser.add_argument("--stage", required=True, choices=sorted(STAGES))
    parser.add_argument("--training-run-dir", required=True)
    parser.add_argument("--output-path", required=True)
    parser.add_argument("--metrics-manifest")
    parser.add_argument("--source-index-manifest")
    parser.add_argument("--raw-eval-manifest")
    parser.add_argument("--ablation-manifest")
    parser.add_argument("--previous-gate-manifest")
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    manifest = build_two_tower_stage_gate_manifest(
        stage=args.stage,
        training_run_dir=args.training_run_dir,
        output_path=args.output_path,
        metrics_manifest=args.metrics_manifest,
        source_index_manifest=args.source_index_manifest,
        raw_eval_manifest=args.raw_eval_manifest,
        ablation_manifest=args.ablation_manifest,
        previous_gate_manifest=args.previous_gate_manifest,
        overwrite=args.overwrite,
    )
    if manifest["status"] == "STOP":
        raise RuntimeError(f"stage gate STOP: {manifest['failure_reasons']}")
    print(f"Two-tower stage gate {manifest['stage']} status: {manifest['status']}")


if __name__ == "__main__":
    main()
