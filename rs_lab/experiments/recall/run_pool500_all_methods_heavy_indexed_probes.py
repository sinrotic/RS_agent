from __future__ import annotations

import argparse
import itertools
import shutil
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rs_core.common.io import iter_jsonl, read_json, write_json
from rs_lab.experiments.recall.run_full_lightweight_recall_e2e import MIN_FREE_BYTES
from rs_lab.experiments.recall.run_phase1_itemcf_covisit_representative_merge_eval import (
    _enforce_project_venv,
    _existing_ancestor,
    _file_signature,
)

SCHEMA_VERSION = "pool500_all_methods_heavy_indexed_probes_v1"
DEFAULT_CUSTOM_INDEX_DIR = ROOT / "outputs" / "recall" / "pool500_all_methods_representative" / "custom_index"
DEFAULT_OUTPUT_DIR = ROOT / "outputs" / "recall" / "pool500_all_methods_representative" / "heavy_indexed_probes"
FORBIDDEN_PATH_MARKERS = (
    "amazon_2023_recall_clean_10000",
    "amazon_2023_recall_views_10000",
    "pool1000",
)
FORBIDDEN_CANDIDATE_FILES = (
    "canonical_interactions.valid.jsonl",
    "canonical_interactions.test.jsonl",
    "user_sequences.valid.jsonl",
    "user_sequences.test.jsonl",
    "holdout.jsonl",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run bounded custom-index graph/MF/two-tower feasibility probes for pool500 all-method recall.")
    parser.add_argument("--custom-index-dir", default=str(DEFAULT_CUSTOM_INDEX_DIR))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--min-free-bytes", type=int, default=MIN_FREE_BYTES)
    parser.add_argument("--skip-venv-check", action="store_true")
    return parser.parse_args()


def run_pool500_all_methods_heavy_indexed_probes(
    *,
    custom_index_dir: Path = DEFAULT_CUSTOM_INDEX_DIR,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    min_free_bytes: int = MIN_FREE_BYTES,
    enforce_venv: bool = True,
) -> dict[str, Any]:
    started = perf_counter()
    if enforce_venv:
        _enforce_project_venv()

    custom_index_dir = custom_index_dir.resolve()
    output_dir = output_dir.resolve()
    _precheck(custom_index_dir, output_dir, min_free_bytes)

    disk_free_start = shutil.disk_usage(_existing_ancestor(output_dir.parent)).free
    user_index = read_json(custom_index_dir / "custom_user_index.json")
    item_index = read_json(custom_index_dir / "custom_item_index.json")
    custom_manifest = read_json(custom_index_dir / "manifest.json")
    custom_source_audit = read_json(custom_index_dir / "source_audit.json")
    item_to_index = {str(item["item_id"]): int(item["item_index"]) for item in item_index["items"]}
    sequences = _load_indexed_sequences(custom_index_dir / "indexed_train_sequences.jsonl", item_to_index)

    graph_probe = _graph_probe(sequences, user_index["user_count"], item_index["item_count"])
    mf_probe = _mf_probe(sequences, user_index["user_count"], item_index["item_count"])
    two_tower_probe = _two_tower_probe(sequences, user_index, item_index)
    source_audit = _source_audit(custom_index_dir, custom_source_audit)
    resource_audit = _resource_audit(
        output_dir=output_dir,
        min_free_bytes=min_free_bytes,
        disk_free_start=disk_free_start,
        user_count=user_index["user_count"],
        item_count=item_index["item_count"],
        sequences=sequences,
        graph_probe=graph_probe,
        mf_probe=mf_probe,
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "graph_probe_metrics.json", graph_probe)
    write_json(output_dir / "mf_probe_metrics.json", mf_probe)
    write_json(output_dir / "two_tower_probe_metrics.json", two_tower_probe)
    write_json(output_dir / "source_audit.json", source_audit)
    write_json(output_dir / "resource_audit.json", resource_audit)

    status = "PASS" if _artifacts_pass(graph_probe, mf_probe, two_tower_probe, source_audit, resource_audit) else "FAIL"
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scope": "pool500_all_methods_representative_custom_index_heavy_method_probes_recall_only",
        "custom_index_dir": str(custom_index_dir),
        "output_dir": str(output_dir),
        "runtime_seconds": round(perf_counter() - started, 6),
        "project_venv_required": enforce_venv,
        "custom_index_status": custom_manifest.get("status"),
        "bounded_user_count": user_index["user_count"],
        "bounded_item_count": item_index["item_count"],
        "candidate_generation_executed": False,
        "no_model_training_executed": True,
        "no_full_graph_mf_two_tower_training": True,
        "ranking_input_modified": False,
        "pool1000_generated": False,
        "required_artifacts": {
            "graph_probe_metrics": str(output_dir / "graph_probe_metrics.json"),
            "mf_probe_metrics": str(output_dir / "mf_probe_metrics.json"),
            "two_tower_probe_metrics": str(output_dir / "two_tower_probe_metrics.json"),
            "source_audit": str(output_dir / "source_audit.json"),
            "resource_audit": str(output_dir / "resource_audit.json"),
            "manifest": str(output_dir / "manifest.json"),
        },
        "input_signatures": {
            "custom_manifest": _file_signature(custom_index_dir / "manifest.json"),
            "custom_user_index": _file_signature(custom_index_dir / "custom_user_index.json"),
            "custom_item_index": _file_signature(custom_index_dir / "custom_item_index.json"),
            "indexed_train_sequences": _file_signature(custom_index_dir / "indexed_train_sequences.jsonl"),
            "custom_source_audit": _file_signature(custom_index_dir / "source_audit.json"),
        },
        "artifact_signatures": {
            "graph_probe_metrics": _file_signature(output_dir / "graph_probe_metrics.json"),
            "mf_probe_metrics": _file_signature(output_dir / "mf_probe_metrics.json"),
            "two_tower_probe_metrics": _file_signature(output_dir / "two_tower_probe_metrics.json"),
            "source_audit": _file_signature(output_dir / "source_audit.json"),
            "resource_audit": _file_signature(output_dir / "resource_audit.json"),
        },
    }
    write_json(output_dir / "manifest.json", manifest)
    return manifest


def _precheck(custom_index_dir: Path, output_dir: Path, min_free_bytes: int) -> None:
    for path in (custom_index_dir, output_dir):
        lowered = str(path).replace("\\", "/").lower()
        if any(marker in lowered for marker in FORBIDDEN_PATH_MARKERS):
            raise ValueError(f"Forbidden heavy probe path marker in {path}")
    required = [
        custom_index_dir / "manifest.json",
        custom_index_dir / "source_audit.json",
        custom_index_dir / "resource_audit.json",
        custom_index_dir / "custom_user_index.json",
        custom_index_dir / "custom_item_index.json",
        custom_index_dir / "indexed_train_sequences.jsonl",
    ]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"Missing custom-index inputs: {missing}")
    if output_dir.exists() and (output_dir / "manifest.json").exists():
        raise FileExistsError(f"Completed output directory already exists: {output_dir}")
    free_bytes = shutil.disk_usage(_existing_ancestor(output_dir.parent)).free
    if free_bytes < min_free_bytes:
        raise RuntimeError(f"D drive free bytes below threshold: {free_bytes} < {min_free_bytes}")


def _load_indexed_sequences(path: Path, item_to_index: dict[str, int]) -> list[dict[str, Any]]:
    sequences = []
    for row in iter_jsonl(path):
        item_ids = [str(item_id) for item_id in row.get("item_ids", []) if item_id]
        item_indices = [item_to_index[item_id] for item_id in item_ids if item_id in item_to_index]
        unique_item_indices = sorted(set(item_indices))
        sequences.append(
            {
                "user_index": int(row["user_index"]),
                "item_ids": item_ids,
                "item_indices": item_indices,
                "unique_item_indices": unique_item_indices,
                "positive_item_ids": [str(item_id) for item_id in row.get("positive_item_ids", []) if item_id],
                "strong_positive_item_ids": [str(item_id) for item_id in row.get("strong_positive_item_ids", []) if item_id],
            }
        )
    return sequences


def _graph_probe(sequences: list[dict[str, Any]], user_count: int, item_count: int) -> dict[str, Any]:
    item_degree: Counter[int] = Counter()
    transition_edges: Counter[tuple[int, int]] = Counter()
    cooccurrence_edges: Counter[tuple[int, int]] = Counter()
    nonempty_users = 0
    for row in sequences:
        item_indices = row["item_indices"]
        unique_item_indices = row["unique_item_indices"]
        if item_indices:
            nonempty_users += 1
        item_degree.update(unique_item_indices)
        transition_edges.update(zip(item_indices, item_indices[1:]))
        for left, right in itertools.combinations(unique_item_indices, 2):
            cooccurrence_edges[(left, right)] += 1

    total_nodes = user_count + item_count
    bipartite_edges = sum(len(row["unique_item_indices"]) for row in sequences)
    projected_edge_count = len(cooccurrence_edges)
    transition_edge_count = len(transition_edges)
    max_item_degree = max(item_degree.values(), default=0)
    isolated_items = item_count - len(item_degree)
    memory_estimate_bytes = (bipartite_edges + projected_edge_count + transition_edge_count) * 24
    propagation_ready = nonempty_users == user_count and bipartite_edges > 0 and memory_estimate_bytes < 512 * 1024**2
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS" if propagation_ready else "FAIL",
        "method": "graph",
        "probe_type": "custom_index_graph_stats_and_propagation_feasibility_no_training",
        "training_executed": False,
        "user_nodes": user_count,
        "item_nodes": item_count,
        "total_nodes": total_nodes,
        "nonempty_user_nodes": nonempty_users,
        "bipartite_user_item_edges": bipartite_edges,
        "projected_item_cooccurrence_edges": projected_edge_count,
        "directed_sequence_transition_edges": transition_edge_count,
        "max_item_degree": max_item_degree,
        "isolated_custom_items": isolated_items,
        "estimated_sparse_edge_memory_bytes": memory_estimate_bytes,
        "top_item_degrees": _counter_top(item_degree, 10),
        "top_transition_edges": _edge_counter_top(transition_edges, 10),
        "decision": "FEASIBLE_FOR_SEPARATE_BOUNDED_GRAPH_EXPERIMENT_APPROVAL" if propagation_ready else "NOT_READY",
    }


def _mf_probe(sequences: list[dict[str, Any]], user_count: int, item_count: int) -> dict[str, Any]:
    item_frequency: Counter[int] = Counter()
    user_nnz = []
    duplicate_events = 0
    for row in sequences:
        item_indices = row["item_indices"]
        unique_item_indices = row["unique_item_indices"]
        item_frequency.update(unique_item_indices)
        user_nnz.append(len(unique_item_indices))
        duplicate_events += len(item_indices) - len(unique_item_indices)

    nnz = sum(user_nnz)
    density = nnz / (user_count * item_count) if user_count and item_count else 0.0
    csr_memory_estimate_bytes = (nnz * 8) + ((user_count + 1) * 8)
    cold_item_count = item_count - len(item_frequency)
    nonempty_user_count = sum(1 for value in user_nnz if value > 0)
    proxy_ready = nonempty_user_count == user_count and nnz > 0 and csr_memory_estimate_bytes < 256 * 1024**2
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS" if proxy_ready else "FAIL",
        "method": "mf",
        "probe_type": "custom_index_sparse_matrix_shape_and_deterministic_proxy_no_training",
        "training_executed": False,
        "matrix_shape": [user_count, item_count],
        "nnz_unique_user_item": nnz,
        "duplicate_train_events_within_user": duplicate_events,
        "density": round(density, 12),
        "nonempty_user_count": nonempty_user_count,
        "cold_item_count_within_custom_index": cold_item_count,
        "user_nnz_summary": _summary(user_nnz),
        "estimated_csr_memory_bytes": csr_memory_estimate_bytes,
        "top_popularity_proxy_items": _counter_top(item_frequency, 20),
        "deterministic_proxy": {
            "name": "train_popularity_within_custom_index",
            "candidate_generation_executed": False,
            "model_factors_learned": False,
        },
        "decision": "FEASIBLE_FOR_SEPARATE_BOUNDED_MF_TRAINING_APPROVAL" if proxy_ready else "NOT_READY",
    }


def _two_tower_probe(sequences: list[dict[str, Any]], user_index: dict[str, Any], item_index: dict[str, Any]) -> dict[str, Any]:
    user_lengths = [len(row["item_indices"]) for row in sequences]
    positive_lengths = [len(row["positive_item_ids"]) for row in sequences]
    strong_positive_lengths = [len(row["strong_positive_item_ids"]) for row in sequences]
    items = item_index["items"]
    train_item_count = sum(1 for item in items if int(item.get("train_occurrence_count") or 0) > 0)
    pool_only_item_count = sum(
        1
        for item in items
        if int(item.get("train_occurrence_count") or 0) == 0 and int(item.get("pool500_occurrence_count") or 0) > 0
    )
    nonempty_users = sum(1 for length in user_lengths if length > 0)
    positive_users = sum(1 for length in positive_lengths if length > 0)
    strong_positive_users = sum(1 for length in strong_positive_lengths if length > 0)
    readiness = nonempty_users == user_index["user_count"] and train_item_count > 0 and positive_users > 0
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS" if readiness else "FAIL",
        "method": "two_tower",
        "probe_type": "custom_index_feature_readiness_and_proxy_feasibility_no_gpu_no_training",
        "training_executed": False,
        "gpu_used": False,
        "user_count": user_index["user_count"],
        "item_count": item_index["item_count"],
        "nonempty_user_sequence_count": nonempty_users,
        "positive_user_count": positive_users,
        "strong_positive_user_count": strong_positive_users,
        "train_observed_item_count": train_item_count,
        "pool_only_item_count": pool_only_item_count,
        "user_sequence_length_summary": _summary(user_lengths),
        "positive_sequence_length_summary": _summary(positive_lengths),
        "strong_positive_sequence_length_summary": _summary(strong_positive_lengths),
        "available_feature_groups": {
            "user_sequence_ids": True,
            "positive_sequence_ids": positive_users > 0,
            "strong_positive_sequence_ids": strong_positive_users > 0,
            "item_id_embedding_keys": True,
            "text_or_image_features": False,
        },
        "deterministic_proxy": {
            "name": "id_only_readiness_with_train_positive_availability",
            "candidate_generation_executed": False,
            "model_training_executed": False,
        },
        "decision": "FEASIBLE_FOR_SEPARATE_BOUNDED_TWO_TOWER_TRAINING_APPROVAL" if readiness else "NOT_READY",
    }


def _source_audit(custom_index_dir: Path, custom_source_audit: dict[str, Any]) -> dict[str, Any]:
    read_files = [
        custom_index_dir / "manifest.json",
        custom_index_dir / "source_audit.json",
        custom_index_dir / "resource_audit.json",
        custom_index_dir / "custom_user_index.json",
        custom_index_dir / "custom_item_index.json",
        custom_index_dir / "indexed_train_sequences.jsonl",
    ]
    forbidden_reads = [
        str(path)
        for path in read_files
        if path.name in FORBIDDEN_CANDIDATE_FILES or any(marker in str(path).replace("\\", "/").lower() for marker in FORBIDDEN_PATH_MARKERS)
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS" if not forbidden_reads and custom_source_audit.get("status") == "PASS" else "FAIL",
        "candidate_generation_executed": False,
        "candidate_generation_uses_valid_test_holdout": False,
        "evaluation_only_read_files": [],
        "probe_read_only_inputs": [str(path) for path in read_files],
        "forbidden_read_paths_found": forbidden_reads,
        "upstream_custom_index_source_status": custom_source_audit.get("status"),
        "upstream_candidate_generation_read_files": custom_source_audit.get("candidate_generation_read_files", []),
        "no_10k_source": custom_source_audit.get("no_10k_source") is True,
        "no_full_clean_copy": custom_source_audit.get("no_full_clean_copy") is True,
        "ranking_isolation": {
            "ranking_default_input_modified": False,
            "pool500_as_ranking_input": False,
            "pool1000_generated": False,
            "frozen_pool200_ranking_input_modified": False,
        },
        "disabled_outputs": {
            "pool1000": True,
            "candidate_generation": True,
            "graph_training": True,
            "mf_training": True,
            "two_tower_training": True,
            "gpu_training": True,
            "ranking": True,
        },
        "source_signatures": {path.name: _file_signature(path) for path in read_files},
    }


def _resource_audit(
    *,
    output_dir: Path,
    min_free_bytes: int,
    disk_free_start: int,
    user_count: int,
    item_count: int,
    sequences: list[dict[str, Any]],
    graph_probe: dict[str, Any],
    mf_probe: dict[str, Any],
) -> dict[str, Any]:
    usage = shutil.disk_usage(_existing_ancestor(output_dir.parent))
    train_event_count = sum(len(row["item_indices"]) for row in sequences)
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS" if usage.free >= min_free_bytes else "FAIL",
        "disk_free_bytes_start": disk_free_start,
        "disk_free_bytes_end": usage.free,
        "disk_free_gib_end": round(usage.free / (1024**3), 3),
        "min_free_bytes": min_free_bytes,
        "min_free_gib": round(min_free_bytes / (1024**3), 3),
        "bounded_user_count": user_count,
        "bounded_item_count": item_count,
        "train_event_count": train_event_count,
        "graph_estimated_sparse_edge_memory_bytes": graph_probe["estimated_sparse_edge_memory_bytes"],
        "mf_estimated_csr_memory_bytes": mf_probe["estimated_csr_memory_bytes"],
        "full_training_executed": False,
        "gpu_used": False,
        "resource_summary": "bounded custom-index probes stayed above 50GiB free-space threshold" if usage.free >= min_free_bytes else "D drive free space is below threshold",
    }


def _summary(values: list[int]) -> dict[str, float | int]:
    sorted_values = sorted(values)
    if not sorted_values:
        return {"min": 0, "max": 0, "avg": 0.0, "p50": 0, "p95": 0}
    return {
        "min": sorted_values[0],
        "max": sorted_values[-1],
        "avg": round(sum(sorted_values) / len(sorted_values), 6),
        "p50": sorted_values[len(sorted_values) // 2],
        "p95": sorted_values[min(len(sorted_values) - 1, int(len(sorted_values) * 0.95))],
    }


def _counter_top(counter: Counter[int], limit: int) -> list[dict[str, int]]:
    return [{"item_index": key, "count": value} for key, value in counter.most_common(limit)]


def _edge_counter_top(counter: Counter[tuple[int, int]], limit: int) -> list[dict[str, int]]:
    return [
        {"source_item_index": left, "target_item_index": right, "count": value}
        for (left, right), value in counter.most_common(limit)
    ]


def _artifacts_pass(*artifacts: dict[str, Any]) -> bool:
    return all(artifact.get("status") == "PASS" for artifact in artifacts)


def main() -> None:
    args = parse_args()
    manifest = run_pool500_all_methods_heavy_indexed_probes(
        custom_index_dir=Path(args.custom_index_dir),
        output_dir=Path(args.output_dir),
        min_free_bytes=args.min_free_bytes,
        enforce_venv=not args.skip_venv_check,
    )
    print({"status": manifest["status"], "manifest_path": manifest["required_artifacts"]["manifest"]})


if __name__ == "__main__":
    main()
