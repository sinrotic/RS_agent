from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_RECENT_DIR = ROOT / "data" / "processed" / "amazon_2023_recall_recent_2y_1m_3m"
DEFAULT_OUTPUT_ROOT = ROOT / "outputs" / "recall" / "pool500_method_sources_newdata"
DEFAULT_CONFIG_DIR = ROOT / "configs" / "recall" / "full_data_pool500" / "co_visit_fallback_repair"

ELIGIBLE_BUCKETS = ["fallback_only", "medium_behavior", "sequence_sufficient", "collaborative_rich"]
FORBIDDEN_TOKENS = ("valid", "test", "holdout", "lopo", "oracle", "eval_label")
GOVERNANCE = {
    "train_only": True,
    "valid_used": False,
    "test_used": False,
    "holdout_used": False,
    "lopo_used": False,
    "oracle_used": False,
    "eval_label_used": False,
    "candidate_generation_allowed": False,
    "ranking_input_replacement_allowed": False,
    "promotion_allowed": False,
    "pool1000_allowed": False,
    "full_pool500_ready_declared": False,
    "final_pool500_ready_claimed": False,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build isolated recent2y smoke/formal co-visit dataset manifests."
    )
    parser.add_argument("--recent-dir", type=Path, default=DEFAULT_RECENT_DIR)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--config-dir", type=Path, default=DEFAULT_CONFIG_DIR)
    parser.add_argument(
        "--smoke-user-limit",
        type=int,
        default=10_000,
        help="Resource-validation smoke target count. Formal keeps the full eligible set.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = build_manifests(
        recent_dir=args.recent_dir,
        output_root=args.output_root,
        config_dir=args.config_dir,
        smoke_user_limit=args.smoke_user_limit,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


def build_manifests(
    *,
    recent_dir: Path,
    output_root: Path,
    config_dir: Path,
    smoke_user_limit: int,
) -> dict[str, Any]:
    recent_dir = recent_dir.resolve()
    output_root = output_root.resolve()
    config_dir = config_dir.resolve()

    clean_manifest_path = recent_dir / "manifest.json"
    governance_manifest_path = recent_dir / "train_only_governance" / "manifest.json"
    views_manifest_path = recent_dir / "recall_views" / "manifest.json"
    user_quality_path = recent_dir / "train_only_governance" / "user_quality_profile.jsonl"

    clean = _read_json(clean_manifest_path)
    governance_manifest = _read_json(governance_manifest_path)
    views_manifest = _read_json(views_manifest_path)

    source_dir = output_root / "co_visit_recent2y_train_only_source_v1"
    smoke_dir = output_root / "co_visit_recent2y_smoke_dataset_v1"
    formal_dir = output_root / "co_visit_recent2y_formal_dataset_v1"
    for directory in (source_dir, smoke_dir, formal_dir, config_dir):
        directory.mkdir(parents=True, exist_ok=True)

    generated_at = datetime.now(UTC).isoformat()
    train_interactions_path = Path(clean["split_paths"]["train"])
    train_sequences_path = Path(clean["train_user_sequences_path"])
    canonical_items_path = Path(clean["canonical_items_path"])
    semantic_inputs_path = _resolve_repo_path(views_manifest["outputs"]["semantic_recall_inputs"])

    source_manifest = _build_source_manifest(
        generated_at=generated_at,
        recent_dir=recent_dir,
        clean=clean,
        governance_manifest=governance_manifest,
        clean_manifest_path=clean_manifest_path,
        governance_manifest_path=governance_manifest_path,
        views_manifest_path=views_manifest_path,
        train_interactions_path=train_interactions_path,
        train_sequences_path=train_sequences_path,
        canonical_items_path=canonical_items_path,
        semantic_inputs_path=semantic_inputs_path,
        user_quality_path=user_quality_path,
    )
    source_manifest_path = source_dir / "manifest.json"
    _write_json(source_manifest_path, source_manifest)

    formal_users, bucket_counts, sequence_len_summary, user_buckets = _load_eligible_users(user_quality_path)
    smoke_users, smoke_bucket_counts = _select_smoke_users(
        formal_users=formal_users,
        bucket_counts=bucket_counts,
        smoke_user_limit=smoke_user_limit,
        user_buckets=user_buckets,
    )

    formal_paths = _write_dataset_pair(
        dataset_dir=formal_dir,
        dataset_class="co_visit_recent2y_formal_dataset_v1",
        dataset_id="amazon_2023_recall_recent2y_co_visit_formal_dataset",
        generated_at=generated_at,
        source_manifest_path=source_manifest_path,
        clean_manifest_path=clean_manifest_path,
        governance_manifest_path=governance_manifest_path,
        views_manifest_path=views_manifest_path,
        user_quality_path=user_quality_path,
        train_interactions_path=train_interactions_path,
        train_sequences_path=train_sequences_path,
        eligible_user_ids=formal_users,
        bucket_counts=bucket_counts,
        sequence_len_summary=sequence_len_summary,
        selection_policy={
            "dataset_role": "formal",
            "max_users": None,
            "sample_count_caps": "none",
            "old_quantity_limits_ignored": True,
            "ordering": "user_quality_profile_file_order",
            "input_scope": "train_only_governance_user_quality_profile",
        },
        source_policy=source_manifest["sciomc_preprocessing_policy"],
        clean=clean,
    )
    smoke_paths = _write_dataset_pair(
        dataset_dir=smoke_dir,
        dataset_class="co_visit_recent2y_smoke_dataset_v1",
        dataset_id="amazon_2023_recall_recent2y_co_visit_smoke_dataset",
        generated_at=generated_at,
        source_manifest_path=source_manifest_path,
        clean_manifest_path=clean_manifest_path,
        governance_manifest_path=governance_manifest_path,
        views_manifest_path=views_manifest_path,
        user_quality_path=user_quality_path,
        train_interactions_path=train_interactions_path,
        train_sequences_path=train_sequences_path,
        eligible_user_ids=smoke_users,
        bucket_counts=smoke_bucket_counts,
        sequence_len_summary=_summarize_selected_sequences(user_quality_path, set(smoke_users)),
        selection_policy={
            "dataset_role": "smoke",
            "max_users": len(smoke_users),
            "sample_count_caps": "resource_validation_only_not_formal_dataset_scale",
            "old_quantity_limits_ignored": True,
            "requested_smoke_user_limit": smoke_user_limit,
            "stratified_by_buckets": ELIGIBLE_BUCKETS,
            "input_scope": "train_only_governance_user_quality_profile",
        },
        source_policy=source_manifest["sciomc_preprocessing_policy"],
        clean=clean,
    )

    smoke_config_path = config_dir / "source_config_newdata_smoke.yaml"
    formal_config_path = config_dir / "source_config_newdata_formal.yaml"
    default_newdata_config_path = config_dir / "source_config_newdata.yaml"
    _write_config(
        config_path=smoke_config_path,
        output_root=output_root,
        clean_manifest_path=clean_manifest_path,
        views_manifest_path=views_manifest_path,
        eligible_manifest_path=smoke_paths["eligible_user_manifest"],
        source_manifest_path=source_manifest_path,
        smoke_manifest_path=smoke_paths["dataset_manifest"],
        formal_manifest_path=formal_paths["dataset_manifest"],
        default_run_id="co_visit_recent2y_smoke",
    )
    _write_config(
        config_path=formal_config_path,
        output_root=output_root,
        clean_manifest_path=clean_manifest_path,
        views_manifest_path=views_manifest_path,
        eligible_manifest_path=formal_paths["eligible_user_manifest"],
        source_manifest_path=source_manifest_path,
        smoke_manifest_path=smoke_paths["dataset_manifest"],
        formal_manifest_path=formal_paths["dataset_manifest"],
        default_run_id="co_visit_recent2y_formal",
    )
    _write_config(
        config_path=default_newdata_config_path,
        output_root=output_root,
        clean_manifest_path=clean_manifest_path,
        views_manifest_path=views_manifest_path,
        eligible_manifest_path=smoke_paths["eligible_user_manifest"],
        source_manifest_path=source_manifest_path,
        smoke_manifest_path=smoke_paths["dataset_manifest"],
        formal_manifest_path=formal_paths["dataset_manifest"],
        default_run_id="co_visit_recent2y_smoke",
    )

    _assert_no_forbidden_paths([source_manifest_path, smoke_paths["dataset_manifest"], smoke_paths["eligible_user_manifest"], formal_paths["dataset_manifest"], formal_paths["eligible_user_manifest"]])

    return {
        "source_manifest": _rel(source_manifest_path),
        "smoke_dataset_manifest": _rel(smoke_paths["dataset_manifest"]),
        "smoke_eligible_user_manifest": _rel(smoke_paths["eligible_user_manifest"]),
        "formal_dataset_manifest": _rel(formal_paths["dataset_manifest"]),
        "formal_eligible_user_manifest": _rel(formal_paths["eligible_user_manifest"]),
        "smoke_config": _rel(smoke_config_path),
        "formal_config": _rel(formal_config_path),
        "default_newdata_config": _rel(default_newdata_config_path),
        "formal_eligible_user_count": len(formal_users),
        "smoke_eligible_user_count": len(smoke_users),
        "formal_bucket_counts": bucket_counts,
        "smoke_bucket_counts": smoke_bucket_counts,
    }


def _build_source_manifest(**kwargs: Any) -> dict[str, Any]:
    clean = kwargs["clean"]
    governance_manifest = kwargs["governance_manifest"]
    return {
        "schema_version": "co_visit_recent2y_train_only_source_v1",
        "dataset_class": "co_visit_recent2y_train_only_source_v1",
        "dataset_id": "amazon_2023_recall_recent2y_train_only_source",
        "generated_at": kwargs["generated_at"],
        "source": "co_visit_fallback_repair",
        "algorithm_scope": "train_transition_metadata_repair_v0",
        "complete_co_visit_graph_claimed": False,
        "materialization_status": "existing_recent_window_train_only_inputs",
        "source_manifests": {
            "clean_manifest": _rel(kwargs["clean_manifest_path"]),
            "train_only_governance_manifest": _rel(kwargs["governance_manifest_path"]),
            "lightweight_views_manifest": _rel(kwargs["views_manifest_path"]),
        },
        "allowed_train_only_inputs": {
            "canonical_interactions_train": _rel(kwargs["train_interactions_path"]),
            "user_sequences_train": _rel(kwargs["train_sequences_path"]),
            "canonical_items_train_universe": _rel(kwargs["canonical_items_path"]),
            "semantic_recall_inputs_train_scope": _rel(kwargs["semantic_inputs_path"]),
            "user_quality_profile": _rel(kwargs["user_quality_path"]),
            "item_frequency_train": _rel(kwargs["recent_dir"] / "train_only_governance" / "item_frequency_train.jsonl"),
            "item_universe_summary": _rel(kwargs["recent_dir"] / "train_only_governance" / "item_universe_summary.json"),
        },
        "time_window": {
            "train": clean["window_policy"]["splits"]["train"],
            "timezone": clean["window_policy"]["timezone"],
            "boundary_policy": clean["window_policy"]["boundary_policy"],
        },
        "counts": {
            "train_interactions": clean["counts"]["interactions"]["train"],
            "canonical_items_train_only": clean["counts"]["canonical_items"]["train_only"],
            "train_user_sequences": clean["counts"]["user_sequences"]["train"],
        },
        "input_hashes": governance_manifest["lineage"]["input_hashes"],
        "sciomc_preprocessing_policy": {
            "candidate_generation_scope": "train_only",
            "preference_signal": "positive_only_label_binary_or_recent_positive_item_sequence",
            "confidence_rule": "implicit_positive_count_and_unique_item_count_from_train_only_governance",
            "dedup_policy": "user_item_train_positive_profile_from_governance_no_eval_label_injection",
            "sequence_order": "chronological_train_sequence_from_recent_window_train_split",
            "session_policy": "current_v0_uses_train_sequence_transition_window; pseudo_session/session_graph_shadow_only_not_claimed",
            "item_universe_policy": "canonical_items_train_only_no_oracle_label_injection",
            "quantity_caps": "formal_has_none; smoke_cap_is_resource_validation_only_not_old_method_scale",
        },
        "forbidden_data_sources": ["valid", "test", "holdout", "lopo", "oracle", "eval_label", "label_injection"],
        "governance": GOVERNANCE,
    }


def _load_eligible_users(
    user_quality_path: Path,
) -> tuple[list[str], dict[str, int], dict[str, int | None], dict[str, str]]:
    bucket_counts = {bucket: 0 for bucket in ELIGIBLE_BUCKETS}
    sequence_len_summary: dict[str, int | None] = {
        "min": None,
        "max": 0,
        "positive_count_sum": 0,
        "unique_item_count_sum": 0,
    }
    eligible_user_ids: list[str] = []
    user_buckets: dict[str, str] = {}
    eligible_set = set(ELIGIBLE_BUCKETS)
    with user_quality_path.open(encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            bucket = str(row.get("quality_bucket_v2") or row.get("quality_bucket") or "")
            if bucket not in eligible_set:
                continue
            user_id = str(row.get("user_id") or "")
            if not user_id:
                continue
            eligible_user_ids.append(user_id)
            user_buckets[user_id] = bucket
            bucket_counts[bucket] += 1
            _update_sequence_summary(sequence_len_summary, row)
    return eligible_user_ids, bucket_counts, sequence_len_summary, user_buckets


def _select_smoke_users(
    *,
    formal_users: list[str],
    bucket_counts: dict[str, int],
    smoke_user_limit: int,
    user_buckets: dict[str, str],
) -> tuple[list[str], dict[str, int]]:
    if smoke_user_limit <= 0:
        raise ValueError("smoke_user_limit must be positive")
    total = len(formal_users)
    if total <= smoke_user_limit:
        return list(formal_users), dict(bucket_counts)

    # Deterministic stratified sample from the existing governance order. The cap is a smoke resource guard,
    # not a revival of the old method-specific max_target_users definitions.
    allocations = {bucket: 0 for bucket in ELIGIBLE_BUCKETS}
    small_bucket_reserve = 0
    for bucket in ELIGIBLE_BUCKETS:
        count = bucket_counts[bucket]
        if count <= max(100, smoke_user_limit // 100):
            allocations[bucket] = count
            small_bucket_reserve += count
    remaining_limit = max(0, smoke_user_limit - small_bucket_reserve)
    remaining_total = sum(bucket_counts[b] for b in ELIGIBLE_BUCKETS if allocations[b] == 0)
    for bucket in ELIGIBLE_BUCKETS:
        if allocations[bucket] > 0:
            continue
        count = bucket_counts[bucket]
        allocations[bucket] = min(count, max(1, round(remaining_limit * count / remaining_total))) if remaining_total else 0

    while sum(allocations.values()) > smoke_user_limit:
        largest = max((b for b in ELIGIBLE_BUCKETS if allocations[b] > 1), key=lambda b: allocations[b])
        allocations[largest] -= 1
    while sum(allocations.values()) < smoke_user_limit:
        candidates = [b for b in ELIGIBLE_BUCKETS if allocations[b] < bucket_counts[b]]
        if not candidates:
            break
        largest_remaining = max(candidates, key=lambda b: bucket_counts[b] - allocations[b])
        allocations[largest_remaining] += 1

    selected: list[str] = []
    selected_counts = {bucket: 0 for bucket in ELIGIBLE_BUCKETS}
    for user_id in formal_users:
        bucket = user_buckets.get(user_id)
        if bucket and selected_counts[bucket] < allocations[bucket]:
            selected.append(user_id)
            selected_counts[bucket] += 1
        if len(selected) >= smoke_user_limit:
            break
    return selected, selected_counts


def _summarize_selected_sequences(user_quality_path: Path, selected_user_ids: set[str]) -> dict[str, int | None]:
    summary: dict[str, int | None] = {"min": None, "max": 0, "positive_count_sum": 0, "unique_item_count_sum": 0}
    with user_quality_path.open(encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            user_id = str(row.get("user_id") or "")
            if user_id in selected_user_ids:
                _update_sequence_summary(summary, row)
    return summary


def _update_sequence_summary(summary: dict[str, int | None], row: dict[str, Any]) -> None:
    sequence_len = int(row.get("sequence_len") or 0)
    current_min = summary["min"]
    summary["min"] = sequence_len if current_min is None else min(int(current_min), sequence_len)
    summary["max"] = max(int(summary["max"] or 0), sequence_len)
    summary["positive_count_sum"] = int(summary["positive_count_sum"] or 0) + int(row.get("positive_count") or 0)
    summary["unique_item_count_sum"] = int(summary["unique_item_count_sum"] or 0) + int(row.get("unique_item_count") or 0)


def _write_dataset_pair(
    *,
    dataset_dir: Path,
    dataset_class: str,
    dataset_id: str,
    generated_at: str,
    source_manifest_path: Path,
    clean_manifest_path: Path,
    governance_manifest_path: Path,
    views_manifest_path: Path,
    user_quality_path: Path,
    train_interactions_path: Path,
    train_sequences_path: Path,
    eligible_user_ids: list[str],
    bucket_counts: dict[str, int],
    sequence_len_summary: dict[str, int | None],
    selection_policy: dict[str, Any],
    source_policy: dict[str, Any],
    clean: dict[str, Any],
) -> dict[str, Path]:
    eligible_manifest_path = dataset_dir / "eligible_user_manifest.json"
    dataset_manifest_path = dataset_dir / "manifest.json"
    eligible_manifest = {
        "schema_version": "full_data_pool500_recall_only_generation_v1.eligible_user_manifest",
        "dataset_class": dataset_class,
        "scope": f"{dataset_class}_train_only",
        "dataset_id": dataset_id,
        "generated_at": generated_at,
        "manifest_role": "train_only_candidate_generation_target_users",
        "source_dataset_manifest": _rel(source_manifest_path),
        "source_train_user_sequences_path": _rel(train_sequences_path),
        "source_train_interactions_path": _rel(train_interactions_path),
        "clean_manifest_path": _rel(clean_manifest_path),
        "lightweight_views_manifest_path": _rel(views_manifest_path),
        "governance_manifest_path": _rel(governance_manifest_path),
        "user_quality_profile_path": _rel(user_quality_path),
        **GOVERNANCE,
        "ranking_replacement_allowed": False,
        "full_pool500_ready_declared": False,
        "eligible_user_policy": "co_visit_fallback_repair_recent2y_train_only_buckets_v1",
        "eligible_user_buckets": ELIGIBLE_BUCKETS,
        "excluded_user_buckets": ["cold_start"],
        "source_eligible_bucket_counts": bucket_counts,
        "selection_policy": selection_policy,
        "eligible_user_count": len(eligible_user_ids),
        "eligible_user_hash": _hash_lines(eligible_user_ids),
        "sequence_profile_summary": sequence_len_summary,
        "eligible_user_ids": eligible_user_ids,
    }
    dataset_manifest = {key: value for key, value in eligible_manifest.items() if key != "eligible_user_ids"}
    dataset_manifest.update(
        {
            "schema_version": dataset_class,
            "dataset_manifest_path": _rel(dataset_manifest_path),
            "eligible_user_manifest_path": _rel(eligible_manifest_path),
            "builder_input_contract": {
                "clean_manifest": _rel(clean_manifest_path),
                "lightweight_views_manifest": _rel(views_manifest_path),
                "eligible_user_manifest": _rel(eligible_manifest_path),
                "train_only": True,
            },
            "method_dataset_policy": {
                "dataset_class": dataset_class,
                "algorithm_scope": "train_transition_metadata_repair_v0",
                "complete_co_visit_graph_claimed": False,
                "positive_behavior_confidence_rules": source_policy,
                "valid_test_usage": "evaluation_only_denominator_report_never_candidate_generation",
            },
            "counts": {
                "target_user_count": len(eligible_user_ids),
                "target_bucket_counts": bucket_counts,
                "train_interaction_count": clean["counts"]["interactions"]["train"]["interaction_count"],
                "train_item_count": clean["counts"]["canonical_items"]["train_only"],
            },
            "manifest_contract": {
                "method_dataset_manifest": "method_dataset_manifest.json",
                "source_index_manifest": "source_index_manifest.json",
                "candidates": "candidates.jsonl",
                "coverage_audit": "coverage_audit.json",
                "undercoverage_audit": "undercoverage_audit.json",
                "resource_audit": "resource_audit.json",
                "no_holdout_audit": "no_holdout_audit.json",
            },
            "governance": GOVERNANCE,
        }
    )
    _write_json(eligible_manifest_path, eligible_manifest)
    _write_json(dataset_manifest_path, dataset_manifest)
    return {"eligible_user_manifest": eligible_manifest_path, "dataset_manifest": dataset_manifest_path}


def _write_config(
    *,
    config_path: Path,
    output_root: Path,
    clean_manifest_path: Path,
    views_manifest_path: Path,
    eligible_manifest_path: Path,
    source_manifest_path: Path,
    smoke_manifest_path: Path,
    formal_manifest_path: Path,
    default_run_id: str,
) -> None:
    content = f"""schema_version: pool500_method_source_config_v1
source: co_visit_fallback_repair
canonical_source: co_visit_fallback_repair
source_status: TARGET_SLICE_DIAGNOSTIC
algorithm_scope: train_transition_metadata_repair_v0
complete_co_visit_graph_claimed: false
dataset_manifests:
  train_only_source: {_rel(source_manifest_path)}
  smoke_dataset: {_rel(smoke_manifest_path)}
  formal_dataset: {_rel(formal_manifest_path)}
tier_aliases:
  dam: diagnostic
  dam(diagnostic): diagnostic
  最终数据集: local_formal
  最终数据集(local_formal): local_formal
defaults:
  output_root: {_rel(output_root)}
  run_id: {default_run_id}
  input_contract:
    clean_manifest: {_rel(clean_manifest_path)}
    lightweight_views_manifest: {_rel(views_manifest_path)}
    eligible_user_manifest: {_rel(eligible_manifest_path)}
    train_only: true
  resource_guard:
    batch_size: 50
    checkpoint_enabled: true
    heavy_job: false
  method_config:
    max_metadata_rows: 250000
    seed_window: 30
    candidate_per_seed: 40
    candidate_per_user: 120
    transition_window: 5
    transition_per_seed: 200
    min_token_overlap: 1
    max_bucket_candidates: 1000
    category_weight: 2.0
    checkpoint_every_users: 50
  follow_up_metrics:
    pair_support: follow_up_only_not_gate
    distinct_user_support: follow_up_only_not_gate
tiers:
  smoke:
    method_config:
      max_metadata_rows: 50000
      seed_window: 10
      candidate_per_seed: 20
      candidate_per_user: 40
      transition_window: 3
      transition_per_seed: 50
      checkpoint_every_users: 20
    resource_guard:
      batch_size: 20
      heavy_job: false
  diagnostic:
    alias: dam(diagnostic)
    method_config:
      max_metadata_rows: 250000
      seed_window: 30
      candidate_per_seed: 40
      candidate_per_user: 120
      transition_window: 5
      transition_per_seed: 200
      checkpoint_every_users: 50
    resource_guard:
      batch_size: 50
      heavy_job: false
  local_formal:
    alias: 最终数据集(local_formal)
    method_config:
      max_metadata_rows: 500000
      seed_window: 30
      candidate_per_seed: 60
      candidate_per_user: 160
      transition_window: 5
      transition_per_seed: 300
      checkpoint_every_users: 50
    resource_guard:
      batch_size: 50
      heavy_job: false
manifest_contract:
  method_dataset_manifest: method_dataset_manifest.json
  source_index_manifest: source_index_manifest.json
  candidates: candidates.jsonl
  coverage_audit: coverage_audit.json
  undercoverage_audit: undercoverage_audit.json
  resource_audit: resource_audit.json
  no_holdout_audit: no_holdout_audit.json
governance:
  candidate_generation_allowed: false
  ranking_input_replacement_allowed: false
  pool1000_allowed: false
  promotion_allowed: false
  full_pool500_ready_declared: false
  final_pool500_ready_claimed: false
  complete_co_visit_graph_claimed: false
"""
    config_path.write_text(content, encoding="utf-8")


def _assert_no_forbidden_paths(paths: list[Path]) -> None:
    violations: list[str] = []
    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        _collect_forbidden(payload, path.as_posix(), violations)
    if violations:
        raise RuntimeError("Forbidden path tokens found in generated manifests: " + "; ".join(violations[:10]))


def _collect_forbidden(value: Any, breadcrumb: str, violations: list[str]) -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            _collect_forbidden(nested, f"{breadcrumb}.{key}", violations)
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            _collect_forbidden(nested, f"{breadcrumb}[{index}]", violations)
    elif isinstance(value, str):
        lower = value.lower().replace("\\", "/")
        if not ("/" in lower or lower.endswith(".json") or lower.endswith(".jsonl") or lower.endswith(".yaml")):
            return
        if "no_holdout_audit.json" in lower:
            return
        for token in FORBIDDEN_TOKENS:
            if token in lower:
                violations.append(f"{breadcrumb}={value}")
                return


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _resolve_repo_path(raw_path: str) -> Path:
    path = Path(raw_path)
    return path if path.is_absolute() else ROOT / path


def _rel(path: Path | str) -> str:
    path = Path(path)
    if path.is_absolute():
        try:
            return path.relative_to(ROOT).as_posix()
        except ValueError:
            return path.as_posix()
    return path.as_posix().replace("\\", "/")


def _hash_lines(values: list[str]) -> str:
    digest = hashlib.sha256()
    for value in values:
        digest.update(value.encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


if __name__ == "__main__":
    main()
