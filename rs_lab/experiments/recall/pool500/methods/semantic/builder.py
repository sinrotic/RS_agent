from __future__ import annotations

import shutil
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any

from rs_core.common.io import read_json, write_json, write_jsonl
from rs_core.recsys.candidate_merge import semantic_candidates_for_user
from rs_lab.experiments.recall.pool500.common.source_layout import FORBIDDEN_EVIDENCE_SCOPES, REQUIRED_SOURCE_OUTPUTS
from rs_lab.experiments.recall.pool500.methods.semantic_title_category_expansion.builder import (
    _candidate_ids_from_inverted_index,
    _file_signature,
    _input_dataset_rows,
    _load_records_by_ids,
    _load_target_sequences,
    _record_tokens,
    _resolve_repo_path,
    _seed_items_by_user,
    _target_user_ids,
    _with_semantic_tokens,
)

ROOT = Path(__file__).resolve().parents[6]
SOURCE = "semantic"
SOURCE_STATUS = "TARGET_SLICE_DIAGNOSTIC"
SCHEMA_VERSION = "pool500_semantic_source_v1"
DEFAULT_CLEAN_MANIFEST = ROOT / "data" / "processed" / "amazon_2023_recall_clean_full" / "manifest.json"
DEFAULT_LIGHTWEIGHT_VIEWS_MANIFEST = ROOT / "data" / "processed" / "amazon_2023_recall_views_full_lightweight" / "manifest.json"
DEFAULT_ELIGIBLE_USER_MANIFEST = ROOT / "outputs" / "recall" / "pool500_main_route_direct_recall_full_promoted" / "eligible_user_manifest.json"
GOVERNANCE_FIELDS = {
    "candidate_generation_allowed": False,
    "ranking_input_replacement_allowed": False,
    "pool1000_allowed": False,
    "promotion_allowed": False,
    "full_pool500_ready_declared": False,
    "final_pool500_ready_claimed": False,
}


def build_semantic_method_source(*, config: dict[str, Any], run_id: str, output_dir: Path, overwrite: bool) -> dict[str, Any]:
    started = perf_counter()
    _precheck_output(output_dir, overwrite)
    output_dir.mkdir(parents=True, exist_ok=False)

    input_contract = config.get("input_contract") if isinstance(config.get("input_contract"), dict) else {}
    method_config = config.get("method_config") if isinstance(config.get("method_config"), dict) else {}
    clean_manifest_path = _config_path(input_contract, DEFAULT_CLEAN_MANIFEST, "clean_manifest", "clean_manifest_path")
    lightweight_views_manifest_path = _config_path(input_contract, DEFAULT_LIGHTWEIGHT_VIEWS_MANIFEST, "lightweight_views_manifest", "lightweight_views_manifest_path")
    eligible_user_manifest_path = _config_path(input_contract, DEFAULT_ELIGIBLE_USER_MANIFEST, "eligible_user_manifest", "eligible_user_manifest_path")
    limit_users = int(method_config.get("limit_users", 500))
    seed_window = int(method_config.get("seed_window", 20))
    per_user = int(method_config.get("per_user", 80))
    per_token_item_limit = int(method_config.get("per_token_item_limit", 2000))
    max_candidate_items = int(method_config.get("max_candidate_items", 80000))
    min_overlap = int(method_config.get("min_overlap", method_config.get("semantic_min_overlap", 2)))

    clean_manifest = read_json(clean_manifest_path)
    views_manifest = read_json(lightweight_views_manifest_path)
    train_sequences_path = _resolve_repo_path(clean_manifest["train_user_sequences_path"])
    canonical_items_path = _resolve_repo_path(clean_manifest["canonical_items_path"])
    view_outputs = views_manifest.get("outputs") if isinstance(views_manifest.get("outputs"), dict) else {}
    semantic_inputs_path = _resolve_repo_path(view_outputs["semantic_recall_inputs"])
    semantic_inverted_index_path = _resolve_repo_path(view_outputs["semantic_inverted_index"])

    target_user_ids = _target_user_ids(eligible_user_manifest_path, limit_users)
    sequences = _load_target_sequences(train_sequences_path, target_user_ids, limit_users)
    seed_items_by_user = _seed_items_by_user(sequences, seed_window)
    seed_items = {item for items in seed_items_by_user.values() for item in items}
    seed_records = _load_records_by_ids(semantic_inputs_path, seed_items)
    seed_tokens = _record_tokens(seed_records.values())
    candidate_item_ids, token_bucket_stats = _candidate_ids_from_inverted_index(
        semantic_inverted_index_path,
        seed_tokens,
        per_token_item_limit=per_token_item_limit,
        max_candidate_items=max_candidate_items,
    )
    candidate_records = _load_records_by_ids(semantic_inputs_path, candidate_item_ids | seed_items)
    semantic_index = {item_id: _with_semantic_tokens(record) for item_id, record in candidate_records.items()}

    input_dataset_path = output_dir / "semantic_input_dataset.jsonl"
    write_jsonl(input_dataset_path, _input_dataset_rows(semantic_index))
    rows = _candidate_rows(sequences, semantic_index, per_user, min_overlap)
    candidates_path = output_dir / "candidates.jsonl"
    write_jsonl(candidates_path, rows)

    input_paths = [
        clean_manifest_path,
        lightweight_views_manifest_path,
        eligible_user_manifest_path,
        train_sequences_path,
        canonical_items_path,
        semantic_inputs_path,
        semantic_inverted_index_path,
    ]
    signatures = {
        "clean_manifest": _file_signature(clean_manifest_path),
        "lightweight_views_manifest": _file_signature(lightweight_views_manifest_path),
        "train_user_sequences": _file_signature(train_sequences_path),
        "canonical_items": _file_signature(canonical_items_path),
        "semantic_recall_inputs": _file_signature(semantic_inputs_path),
        "semantic_inverted_index": _file_signature(semantic_inverted_index_path),
        "semantic_input_dataset": _file_signature(input_dataset_path),
        "candidates": _file_signature(candidates_path),
    }
    target_user_list = [str(sequence.get("user_id", "")) for sequence in sequences]
    per_user_counts = _counts_by_user(rows, target_user_list)
    coverage_audit = _coverage_audit(
        sequences=sequences,
        semantic_index=semantic_index,
        seed_items=seed_items,
        seed_records=seed_records,
        rows=rows,
        per_user_counts=list(per_user_counts.values()),
        token_bucket_stats=token_bucket_stats,
    )
    undercoverage_audit = _undercoverage_audit(target_user_list, per_user_counts, per_user)
    resource_audit = {
        "schema_version": f"{SCHEMA_VERSION}.resource_audit",
        "status": "PASS",
        "source": SOURCE,
        "canonical_source": SOURCE,
        "source_status": SOURCE_STATUS,
        "heavy_job": False,
        "checkpoint_enabled": True,
        "runtime_seconds": round(perf_counter() - started, 6),
        "resource_profile": "train_only_semantic_inverted_index_slice",
        "batching": {
            "limit_users": limit_users,
            "seed_window": seed_window,
            "per_token_item_limit": per_token_item_limit,
            "max_candidate_items": max_candidate_items,
        },
        "source_signatures": signatures,
        **GOVERNANCE_FIELDS,
    }
    no_holdout_audit = _no_holdout_audit(input_paths)
    method_dataset_manifest = {
        "schema_version": f"{SCHEMA_VERSION}.method_dataset_manifest",
        "status": "PASS",
        "source": SOURCE,
        "canonical_source": SOURCE,
        "source_status": SOURCE_STATUS,
        "run_id": run_id,
        "created_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "output_dir": str(output_dir),
        "dataset_name": "semantic_input_dataset",
        "input_dataset_path": str(input_dataset_path),
        "declared_input_paths": [str(path) for path in input_paths],
        "train_only": True,
        "target_user_count": len(sequences),
        "seed_item_count": len(seed_items),
        "seed_item_metadata_count": len(seed_records),
        "semantic_index_record_count": len(semantic_index),
        "candidate_row_count": len(rows),
        "user_coverage_count": coverage_audit["user_coverage_count"],
        **GOVERNANCE_FIELDS,
    }
    source_index_manifest = {
        "schema_version": f"{SCHEMA_VERSION}.source_index_manifest",
        "status": "PASS",
        "source": SOURCE,
        "canonical_source": SOURCE,
        "source_status": SOURCE_STATUS,
        "run_id": run_id,
        "created_at": method_dataset_manifest["created_at"],
        "output_dir": str(output_dir),
        "index_scope": "TRAIN_ONLY_SEMANTIC_TOKEN_INDEX_SLICE",
        "train_only": True,
        "method_dataset_manifest_path": str(output_dir / "method_dataset_manifest.json"),
        "source_index_manifest_path": str(output_dir / "source_index_manifest.json"),
        "candidates_path": str(candidates_path),
        "candidate_row_count": len(rows),
        "user_coverage_count": coverage_audit["user_coverage_count"],
        "candidate_count_min": coverage_audit["candidate_count_min"],
        "candidate_count_p50": coverage_audit["candidate_count_p50"],
        "candidate_count_p90": coverage_audit["candidate_count_p90"],
        "candidate_count_max": coverage_audit["candidate_count_max"],
        "required_artifacts": {name: str(output_dir / name) for name in REQUIRED_SOURCE_OUTPUTS},
        "outputs": {name.removesuffix(".json").removesuffix(".jsonl"): str(output_dir / name) for name in REQUIRED_SOURCE_OUTPUTS},
        "audit_statuses": {
            "coverage_audit": coverage_audit["status"],
            "undercoverage_audit": undercoverage_audit["status"],
            "resource_audit": resource_audit["status"],
            "no_holdout_audit": no_holdout_audit["status"],
            "method_dataset_manifest": method_dataset_manifest["status"],
        },
        "source_signatures": signatures,
        **GOVERNANCE_FIELDS,
    }

    write_json(output_dir / "method_dataset_manifest.json", method_dataset_manifest)
    write_json(output_dir / "source_index_manifest.json", source_index_manifest)
    write_json(output_dir / "coverage_audit.json", coverage_audit)
    write_json(output_dir / "undercoverage_audit.json", undercoverage_audit)
    write_json(output_dir / "resource_audit.json", resource_audit)
    write_json(output_dir / "no_holdout_audit.json", no_holdout_audit)
    _assert_required_outputs(output_dir)
    return source_index_manifest


def _candidate_rows(sequences: list[dict[str, Any]], semantic_index: dict[str, dict[str, Any]], per_user: int, min_overlap: int) -> list[dict[str, Any]]:
    config = {
        "semantic_enabled": True,
        "semantic_per_user": per_user,
        "semantic_min_overlap": min_overlap,
        "semantic_category_weight": 2.0,
    }
    rows: list[dict[str, Any]] = []
    for sequence in sequences:
        user_id = str(sequence.get("user_id", ""))
        candidates = semantic_candidates_for_user(sequence, semantic_index, config)
        for rank, candidate in enumerate(candidates, start=1):
            metadata = dict(candidate.metadata)
            metadata["canonical_source"] = SOURCE
            metadata["source_status"] = SOURCE_STATUS
            metadata["source_scores"] = {SOURCE: candidate.score}
            rows.append({
                "user_id": user_id,
                "item_id": candidate.item_id,
                "source": SOURCE,
                "canonical_source": SOURCE,
                "sources": [SOURCE],
                "score": candidate.score,
                "rank": rank,
                "metadata": metadata,
            })
    return rows


def _coverage_audit(
    *,
    sequences: list[dict[str, Any]],
    semantic_index: dict[str, dict[str, Any]],
    seed_items: set[str],
    seed_records: dict[str, dict[str, Any]],
    rows: list[dict[str, Any]],
    per_user_counts: list[int],
    token_bucket_stats: dict[str, Any],
) -> dict[str, Any]:
    record_count = len(semantic_index)
    return {
        "schema_version": f"{SCHEMA_VERSION}.coverage_audit",
        "status": "PASS" if rows else "EMPTY",
        "source": SOURCE,
        "canonical_source": SOURCE,
        "source_status": SOURCE_STATUS,
        "target_user_count": len(sequences),
        "semantic_index_record_count": record_count,
        "seed_item_count": len(seed_items),
        "seed_item_metadata_count": len(seed_records),
        "seed_item_metadata_coverage": _ratio(len(seed_records), len(seed_items)),
        "candidate_row_count": len(rows),
        "unique_item_count": len({str(row.get("item_id")) for row in rows if row.get("item_id")}),
        "user_coverage_count": sum(1 for count in per_user_counts if count > 0),
        "candidate_count_min": min(per_user_counts) if per_user_counts else 0,
        "candidate_count_p50": _percentile(per_user_counts, 0.5),
        "candidate_count_p90": _percentile(per_user_counts, 0.9),
        "candidate_count_max": max(per_user_counts) if per_user_counts else 0,
        "token_bucket_stats": token_bucket_stats,
        **GOVERNANCE_FIELDS,
    }


def _undercoverage_audit(target_user_ids: list[str], counts: dict[str, int], per_user: int) -> dict[str, Any]:
    undercovered = [user_id for user_id in target_user_ids if counts.get(user_id, 0) < per_user]
    empty = [user_id for user_id in target_user_ids if counts.get(user_id, 0) <= 0]
    return {
        "schema_version": f"{SCHEMA_VERSION}.undercoverage_audit",
        "status": "DIAGNOSTIC_ONLY_AUDIT",
        "source": SOURCE,
        "canonical_source": SOURCE,
        "source_status": SOURCE_STATUS,
        "target_user_count": len(target_user_ids),
        "method_target_per_user": per_user,
        "user_coverage_count": len(target_user_ids) - len(empty),
        "undercovered_user_count": len(undercovered),
        "empty_user_count": len(empty),
        "undercovered_user_sample": undercovered[:20],
        **GOVERNANCE_FIELDS,
    }


def _no_holdout_audit(paths: list[Path]) -> dict[str, Any]:
    forbidden = [str(path) for path in paths if _is_forbidden_path(path)]
    return {
        "schema_version": f"{SCHEMA_VERSION}.no_holdout_audit",
        "status": "PASS" if not forbidden else "BLOCKED",
        "source": SOURCE,
        "canonical_source": SOURCE,
        "source_status": SOURCE_STATUS,
        "train_only": not forbidden,
        "candidate_generation_uses_holdout": bool(forbidden),
        "forbidden_inputs": forbidden,
        "declared_inputs": [str(path) for path in paths],
        **GOVERNANCE_FIELDS,
    }


def _config_path(config: dict[str, Any], default: Path, *keys: str) -> Path:
    for key in keys:
        value = config.get(key)
        if value:
            path = Path(str(value))
            return path if path.is_absolute() else ROOT / path
    return default


def _precheck_output(output_dir: Path, overwrite: bool) -> None:
    if output_dir.exists():
        if not overwrite:
            raise FileExistsError(f"output directory already exists: {output_dir}")
        shutil.rmtree(output_dir)


def _counts_by_user(rows: list[dict[str, Any]], target_user_ids: list[str]) -> dict[str, int]:
    counts = {user_id: 0 for user_id in target_user_ids}
    observed = Counter(str(row.get("user_id", "")) for row in rows)
    for user_id in counts:
        counts[user_id] = observed[user_id]
    return counts


def _is_forbidden_path(path: Path) -> bool:
    parts = [part.lower() for part in path.parts]
    tokens = {token.lower() for token in FORBIDDEN_EVIDENCE_SCOPES}
    return any(token in part for part in parts for token in tokens)


def _ratio(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 6) if denominator else 0.0


def _percentile(values: list[int], percentile: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(len(ordered) * percentile + 0.999999) - 1))
    return ordered[index]


def _assert_required_outputs(output_dir: Path) -> None:
    missing = [name for name in REQUIRED_SOURCE_OUTPUTS if not (output_dir / name).is_file()]
    if missing:
        raise RuntimeError(f"missing required semantic source outputs: {missing}")
