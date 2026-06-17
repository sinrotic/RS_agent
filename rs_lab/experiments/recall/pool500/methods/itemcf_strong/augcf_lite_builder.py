from __future__ import annotations

import hashlib
import json
import math
import shutil
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any, Iterable

from rs_lab.experiments.recall.pool500.governance.itemcf_p0_contracts import (
    build_pool_ranking_freeze_assertions,
    is_forbidden_itemcf_input,
)

SCHEMA_VERSION = "pool500_itemcf_strong_augcf_lite_method_dataset_v1"
ROW_SCHEMA_VERSION = "itemcf_strong_augcf_lite_edge_features_v1"
PROJECT_ROOT = Path(__file__).resolve().parents[6]
DEFAULT_DATA_ROOT = Path("data/processed/amazon_2023_recall_recent_2y_1m_3m")
DEFAULT_ALLOWED_USER_BUCKETS = ("sequence_sufficient", "collaborative_rich")
DEFAULT_ALLOWED_ITEM_BUCKETS = ("cf_ready", "embedding_ready")
FORBIDDEN_INPUT_TOKENS = ("valid", "test", "holdout", "lopo", "oracle", "eval_label", "label_artifact", "pool1000")
DEFAULT_SOURCE_VARIANT = "itemcf_strong_augcf_lite_recent2y_v1"
DEFAULT_SOURCE_STATUS = "EXPERIMENTAL_DIAGNOSTIC_ONLY"
DEFAULT_HOT_BUDGET_POLICY = "per_src_optional_controlled_then_route_user_final_cap"
DEFAULT_FINAL_USER_HOT_BUDGET_POLICY = "route_level_hot_share_cap_required_for_gate"
DEFAULT_PSEUDO_CONFIDENCE_POLICY = "pseudo_augcf_lite_metadata_category_prior_v1"
DEFAULT_AUGMENTATION_USER_ELIGIBILITY = "sequence_sufficient_or_collaborative_rich_train_only"


@dataclass(frozen=True)
class AugCFLiteConfig:
    data_root: Path
    output_dir: Path
    run_id: str
    limit_users: int = 0
    max_src_items: int = 0
    top_k_per_src: int = 100
    pseudo_per_src: int = 40
    category_pool_size: int = 2000
    max_pseudo_scan_per_key: int = 200
    max_items_per_user: int = 80
    max_pairs_per_user: int = 2000
    min_pair_support: int = 1
    edge_mode: str = "observed_plus_pseudo"
    allow_hot_dst: bool = True
    max_hot_share_per_src: float = 1.0
    controlled_hot_budget: bool = False
    source_variant: str = DEFAULT_SOURCE_VARIANT
    max_final_hot_share_per_user: float = 0.3
    max_pseudo_per_user: int = 100
    seed: int = 20260604


def build_itemcf_strong_augcf_lite_method_dataset(config: AugCFLiteConfig) -> dict[str, Any]:
    started = perf_counter()
    data_root = config.data_root
    output_dir = config.output_dir
    if config.edge_mode not in {"observed_plus_pseudo", "observed_only", "pseudo_only"}:
        raise ValueError(f"unsupported edge_mode: {config.edge_mode}")
    if config.top_k_per_src <= 0:
        raise ValueError("top_k_per_src must be positive")
    if config.pseudo_per_src < 0:
        raise ValueError("pseudo_per_src must be non-negative")

    _prepare_output_dir(output_dir)

    paths = _input_paths(data_root)
    read_files = [
        str(paths[key])
        for key in (
            "user_sequences_train",
            "canonical_items",
            "user_quality_profile",
            "item_quality_profile",
            "item_frequency_train",
        )
    ]
    leakage_audit = _leakage_audit(read_files)
    if leakage_audit["status"] != "PASS":
        raise ValueError(f"forbidden input detected: {leakage_audit}")

    user_buckets = _load_user_buckets(paths["user_quality_profile"], set(DEFAULT_ALLOWED_USER_BUCKETS))
    item_profiles = _load_item_profiles(paths)
    category_pools = _build_category_pools(item_profiles, config.category_pool_size, config.allow_hot_dst)
    sequence_result = _collect_observed_pairs(
        paths["user_sequences_train"],
        user_buckets,
        item_profiles,
        config,
    )
    rows, feature_summary = _rank_edges(
        item_profiles=item_profiles,
        category_pools=category_pools,
        observed_by_src=sequence_result["observed_by_src"],
        pair_support=sequence_result["pair_support"],
        pair_weighted_cooc=sequence_result["pair_weighted_cooc"],
        src_items=sequence_result["src_items"],
        config=config,
    )

    hot_budget_diagnostics = _hot_budget_diagnostics(rows, item_profiles, config)

    rows_path = output_dir / "method_dataset_rows.jsonl"
    with rows_path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    rows_signature = _file_signature(rows_path)
    feature_audit = {
        "schema_version": "itemcf_strong_augcf_lite_feature_audit_v1",
        "status": "PASS",
        "feature_sources": {
            "user_sequence_features": str(paths["user_sequences_train"]),
            "item_quality_features": str(paths["item_quality_profile"]),
            "item_frequency_features": str(paths["item_frequency_train"]),
            "item_metadata_features": str(paths["canonical_items"]),
        },
        "edge_mode": config.edge_mode,
        "feature_summary": feature_summary,
        "per_src_hot_budget_only": True,
        "user_level_hot_share_not_guaranteed_by_builder": True,
        "route_level_hot_budget_required": True,
        "hot_budget_diagnostics": hot_budget_diagnostics,
    }
    resource_audit = {
        "schema_version": "itemcf_strong_augcf_lite_resource_audit_v1",
        "status": "PASS",
        "runtime_seconds": round(perf_counter() - started, 6),
        "row_count": len(rows),
        "src_item_count": len({row["src_item_id"] for row in rows}),
        "dst_item_count": len({row["dst_item_id"] for row in rows}),
        "per_src_hot_budget_only": True,
        "user_level_hot_share_not_guaranteed_by_builder": True,
        "route_level_hot_budget_required": True,
        "hot_budget_diagnostics": hot_budget_diagnostics,
        "config": _config_dict(config),
    }
    _write_json(output_dir / "leakage_audit.json", leakage_audit)
    _write_json(output_dir / "feature_audit.json", feature_audit)
    _write_json(output_dir / "resource_audit.json", resource_audit)

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS",
        "source": "itemcf_strong",
        "canonical_source": "itemcf_strong",
        "variant": "itemcf_strong_augcf_lite_v1",
        "source_variant": config.source_variant,
        "source_status": DEFAULT_SOURCE_STATUS,
        "diagnostic_only": True,
        "run_id": config.run_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "train_only": True,
        "index_scope": "RECENT_2Y_DERIVED_INDEX",
        "dataset_scope": "recent_2y_train_only_governed",
        "data_root": str(data_root),
        "dataset_role": "train_only_augcf_lite_itemcf_edge_method_dataset",
        "output_dir": str(output_dir),
        "method_dataset_rows_path": str(rows_path),
        "row_count": len(rows),
        "edge_count": len(rows),
        "src_item_count": resource_audit["src_item_count"],
        "dst_item_count": resource_audit["dst_item_count"],
        "observed_edge_count": feature_summary["observed_edge_count"],
        "pseudo_edge_count": feature_summary["pseudo_edge_count"],
        "edge_mode": config.edge_mode,
        "hot_budget_policy": DEFAULT_HOT_BUDGET_POLICY,
        "controlled_hot_budget": config.controlled_hot_budget,
        "max_hot_share_per_src": config.max_hot_share_per_src,
        "final_user_hot_budget_policy": DEFAULT_FINAL_USER_HOT_BUDGET_POLICY,
        "max_final_hot_share_per_user": config.max_final_hot_share_per_user,
        "max_pseudo_per_user": config.max_pseudo_per_user,
        "pseudo_confidence_policy": DEFAULT_PSEUDO_CONFIDENCE_POLICY,
        "augmentation_user_eligibility": DEFAULT_AUGMENTATION_USER_ELIGIBILITY,
        "score_policy": "augcf_lite_train_only_metadata_cooc_scorer_v1",
        "rank_policy": "per_src_item_by_itemcf_score_desc_edge_type_priority_dst_item_id_asc",
        "read_files": read_files,
        "forbidden_inputs": sorted(FORBIDDEN_INPUT_TOKENS),
        "leakage_audit": leakage_audit,
        "feature_audit": feature_audit,
        "resource_audit": resource_audit,
        "outputs": {
            "method_dataset_rows": str(rows_path),
            "method_dataset_manifest": str(output_dir / "method_dataset_manifest.json"),
            "leakage_audit": str(output_dir / "leakage_audit.json"),
            "feature_audit": str(output_dir / "feature_audit.json"),
            "resource_audit": str(output_dir / "resource_audit.json"),
        },
        "method_dataset_rows_sha256": rows_signature["sha256"],
        "candidate_generation_allowed": False,
        "ranking_input_replacement_allowed": False,
        "pool1000_allowed": False,
        "promotion_allowed": False,
        "final_pool500_ready_claimed": False,
        "labels_role": "none_in_training_or_candidate_generation",
        "pool_ranking_freeze_assertions": build_pool_ranking_freeze_assertions(),
    }
    _write_json(output_dir / "method_dataset_manifest.json", manifest)
    return manifest


def _prepare_output_dir(output_dir: Path) -> None:
    resolved = output_dir.resolve()
    project = PROJECT_ROOT.resolve()
    allowed_root = (project / "outputs" / "recall" / "pool500_method_datasets").resolve()
    spill_root = Path("/tmp/rs_agent_spill").resolve()
    allowed_roots = (allowed_root, spill_root)
    if not any(_is_relative_to(resolved, root) for root in allowed_roots):
        raise ValueError(f"unsafe output_dir outside generated method dataset roots: {output_dir}")
    if resolved in {project, project / "data", allowed_root, spill_root}:
        raise ValueError(f"unsafe output_dir: {output_dir}")
    if resolved.exists():
        marker = resolved / ".augcf_lite_builder_owned"
        manifest = resolved / "method_dataset_manifest.json"
        if not marker.exists() and not manifest.exists():
            raise ValueError(f"refusing to remove non AugCF-lite output directory: {output_dir}")
        shutil.rmtree(resolved)
    resolved.mkdir(parents=True, exist_ok=True)
    (resolved / ".augcf_lite_builder_owned").write_text("itemcf_strong_augcf_lite\n", encoding="utf-8")


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _input_paths(data_root: Path) -> dict[str, Path]:
    governance_root = data_root / "train_only_governance"
    return {
        "train_governance_manifest": governance_root / "manifest.json",
        "user_sequences_train": data_root / "user_sequences.train.jsonl",
        "canonical_interactions_train": data_root / "canonical_interactions.train.jsonl",
        "canonical_items": data_root / "canonical_items.jsonl",
        "user_quality_profile": governance_root / "user_quality_profile.jsonl",
        "item_quality_profile": governance_root / "item_quality_profile.jsonl",
        "item_frequency_train": governance_root / "item_frequency_train.jsonl",
    }


def _load_user_buckets(path: Path, allowed_buckets: set[str]) -> dict[str, str]:
    users: dict[str, str] = {}
    for row in _iter_jsonl(path):
        user_id = str(row.get("user_id") or "")
        bucket = str(row.get("quality_bucket_v2") or row.get("quality_bucket") or "")
        if user_id and bucket in allowed_buckets:
            users[user_id] = bucket
    return users


def _load_item_profiles(paths: dict[str, Path]) -> dict[str, dict[str, Any]]:
    profiles: dict[str, dict[str, Any]] = {}
    for row in _iter_jsonl(paths["item_frequency_train"]):
        item_id = str(row.get("parent_asin") or "")
        if not item_id:
            continue
        profiles.setdefault(item_id, {}).update(
            {
                "item_id": item_id,
                "frequency": int(row.get("frequency") or 0),
                "user_count": int(row.get("user_count") or 0),
                "category": str(row.get("category") or ""),
                "store": str(row.get("store") or row.get("brand") or ""),
                "is_long_tail": row.get("is_long_tail"),
            }
        )
    for row in _iter_jsonl(paths["item_quality_profile"]):
        item_id = str(row.get("parent_asin") or "")
        if not item_id:
            continue
        profiles.setdefault(item_id, {"item_id": item_id}).update(
            {
                "positive_event_count": int(row.get("positive_event_count") or 0),
                "unique_positive_user_count": int(row.get("unique_positive_user_count") or 0),
                "train_interaction_count": int(row.get("train_interaction_count") or 0),
                "train_positive_count": int(row.get("train_positive_count") or 0),
                "train_strong_positive_count": int(row.get("train_strong_positive_count") or 0),
                "global_pop_rank": int(row.get("global_pop_rank") or 0),
                "category_pop_rank": int(row.get("category_pop_rank") or 0),
                "category": str(row.get("category") or profiles.get(item_id, {}).get("category") or ""),
                "main_category": str(row.get("main_category") or ""),
                "hotness_bucket": str(row.get("hotness_bucket") or ""),
                "quality_bucket_v2": str(row.get("quality_bucket_v2") or row.get("quality_bucket") or ""),
                "cf_ready": row.get("cf_ready") is True,
                "embedding_ready": row.get("embedding_ready") is True,
            }
        )
    # Metadata fills missing taxonomy/store fields. It is train-scope canonical_items.jsonl.
    for row in _iter_jsonl(paths["canonical_items"]):
        item_id = str(row.get("parent_asin") or "")
        if not item_id or item_id not in profiles:
            continue
        profile = profiles[item_id]
        if not profile.get("category"):
            profile["category"] = str(row.get("category") or "")
        if not profile.get("main_category"):
            profile["main_category"] = str(row.get("main_category") or "")
        if not profile.get("store"):
            profile["store"] = str(row.get("store") or "")
    return profiles


def _build_category_pools(
    item_profiles: dict[str, dict[str, Any]], category_pool_size: int, allow_hot_dst: bool
) -> dict[str, list[str]]:
    by_key: dict[str, list[tuple[float, str]]] = defaultdict(list)
    for item_id, profile in item_profiles.items():
        if not _item_allowed(profile, allow_hot=allow_hot_dst):
            continue
        score = _item_prior_score(profile)
        for key in _category_keys(profile):
            by_key[key].append((score, item_id))
    pools: dict[str, list[str]] = {}
    for key, values in by_key.items():
        ranked = sorted(values, key=lambda value: (-value[0], value[1]))
        pools[key] = [item_id for _score, item_id in ranked[:category_pool_size]]
    return pools


def _collect_observed_pairs(
    path: Path,
    user_buckets: dict[str, str],
    item_profiles: dict[str, dict[str, Any]],
    config: AugCFLiteConfig,
) -> dict[str, Any]:
    pair_support: Counter[tuple[str, str]] = Counter()
    pair_weighted_cooc: Counter[tuple[str, str]] = Counter()
    observed_by_src: dict[str, list[tuple[str, int, float]]] = defaultdict(list)
    src_items: set[str] = set()
    contributing_users = 0
    for sequence in _iter_jsonl(path):
        user_id = str(sequence.get("user_id") or "")
        if user_id not in user_buckets:
            continue
        strong = _recent_unique(sequence.get("recent_strong_positive_item_sequence"), config.max_items_per_user)
        positives = _recent_unique(sequence.get("recent_positive_item_sequence"), config.max_items_per_user)
        strong = [item_id for item_id in strong if _item_allowed(item_profiles.get(item_id))]
        positives = [item_id for item_id in positives if _item_allowed(item_profiles.get(item_id), allow_hot=config.allow_hot_dst)]
        if not strong or not positives:
            continue
        pair_budget = config.max_pairs_per_user if config.max_pairs_per_user > 0 else len(strong) * len(positives)
        if len(strong) * len(positives) > pair_budget:
            dst_cap = max(1, pair_budget // max(1, len(strong)))
            positives = positives[-dst_cap:]
        active_len = len(set(strong) | set(positives))
        if active_len < 2:
            continue
        weight = round(1 / math.log1p(active_len), 6)
        contributed = False
        emitted_pairs = 0
        for src in strong:
            src_items.add(src)
            for dst in positives:
                if src == dst:
                    continue
                pair = (src, dst)
                pair_support[pair] += 1
                pair_weighted_cooc[pair] += weight
                contributed = True
                emitted_pairs += 1
                if emitted_pairs >= pair_budget:
                    break
            if emitted_pairs >= pair_budget:
                break
        if contributed:
            contributing_users += 1
            if config.limit_users > 0 and contributing_users >= config.limit_users:
                break
    for (src, dst), support in pair_support.items():
        observed_by_src[src].append((dst, support, pair_weighted_cooc[(src, dst)]))
    for src in observed_by_src:
        observed_by_src[src].sort(key=lambda item: (-item[2], -item[1], item[0]))
    return {
        "pair_support": pair_support,
        "pair_weighted_cooc": pair_weighted_cooc,
        "observed_by_src": observed_by_src,
        "src_items": src_items,
        "contributing_users": contributing_users,
    }


def _rank_edges(
    *,
    item_profiles: dict[str, dict[str, Any]],
    category_pools: dict[str, list[str]],
    observed_by_src: dict[str, list[tuple[str, int, float]]],
    pair_support: Counter[tuple[str, str]],
    pair_weighted_cooc: Counter[tuple[str, str]],
    src_items: set[str],
    config: AugCFLiteConfig,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if config.max_src_items > 0:
        src_iter = sorted(src_items, key=lambda item_id: (-_item_prior_score(item_profiles.get(item_id) or {}), item_id))[: config.max_src_items]
    else:
        src_iter = sorted(src_items)
    rows: list[dict[str, Any]] = []
    edge_type_counts: Counter[str] = Counter()
    candidate_counts: Counter[str] = Counter()
    for src in src_iter:
        src_profile = item_profiles.get(src) or {}
        edge_candidates: dict[str, dict[str, Any]] = {}
        if config.edge_mode in {"observed_plus_pseudo", "observed_only"}:
            for dst, support, weighted_cooc in observed_by_src.get(src, []):
                if support < config.min_pair_support:
                    continue
                row = _observed_edge_row(src, dst, support, weighted_cooc, item_profiles, config)
                if row:
                    edge_candidates[dst] = row
                    candidate_counts["observed_candidate"] += 1
        if config.edge_mode in {"observed_plus_pseudo", "pseudo_only"} and config.pseudo_per_src > 0:
            pseudo_candidates = _pseudo_candidates_for_src(src, src_profile, category_pools, item_profiles, config)
            added = 0
            for dst in pseudo_candidates:
                if dst == src or dst in edge_candidates:
                    continue
                row = _pseudo_edge_row(src, dst, item_profiles, config)
                if not row:
                    continue
                edge_candidates[dst] = row
                candidate_counts["pseudo_candidate"] += 1
                added += 1
                if added >= config.pseudo_per_src:
                    break
        ranked = sorted(edge_candidates.values(), key=lambda row: (-float(row["itemcf_score"]), _edge_type_priority(str(row["edge_type"])), row["dst_item_id"]))
        selected = _apply_hot_budget(ranked, item_profiles, config)
        for rank, row in enumerate(selected, start=1):
            row["edge_rank"] = rank
            rows.append(row)
            edge_type_counts[str(row["edge_type"])] += 1
    summary = {
        "src_item_count_before_cap": len(src_items),
        "src_item_count_after_cap": len(set(row["src_item_id"] for row in rows)),
        "observed_pair_count_before_rank": len(pair_support),
        "observed_edge_count": edge_type_counts.get("observed_strong", 0),
        "pseudo_edge_count": edge_type_counts.get("pseudo_augcf_lite", 0),
        "edge_type_counts": dict(edge_type_counts),
        "candidate_counts": dict(candidate_counts),
        "top_k_per_src": config.top_k_per_src,
        "pseudo_per_src": config.pseudo_per_src,
        "controlled_hot_budget": config.controlled_hot_budget,
        "max_hot_share_per_src": config.max_hot_share_per_src,
        "selected_hot_edge_count": sum(1 for row in rows if _row_is_hot(row, item_profiles)),
    }
    return rows, summary


def _apply_hot_budget(
    ranked_rows: list[dict[str, Any]], item_profiles: dict[str, dict[str, Any]], config: AugCFLiteConfig
) -> list[dict[str, Any]]:
    if not config.controlled_hot_budget or config.max_hot_share_per_src >= 1.0:
        return ranked_rows[: config.top_k_per_src]
    if config.max_hot_share_per_src <= 0:
        hot_limit = 0
    else:
        hot_limit = max(1, int(config.top_k_per_src * config.max_hot_share_per_src))
    selected: list[dict[str, Any]] = []
    deferred_hot: list[dict[str, Any]] = []
    hot_count = 0
    for row in ranked_rows:
        is_hot = _row_is_hot(row, item_profiles)
        if is_hot and hot_count >= hot_limit:
            deferred_hot.append(row)
            continue
        selected.append(row)
        if is_hot:
            hot_count += 1
        if len(selected) >= config.top_k_per_src:
            break
    if len(selected) < config.top_k_per_src and not config.controlled_hot_budget:
        for row in deferred_hot:
            selected.append(row)
            if len(selected) >= config.top_k_per_src:
                break
    return selected[: config.top_k_per_src]


def _row_is_hot(row: dict[str, Any], item_profiles: dict[str, dict[str, Any]]) -> bool:
    bucket = row.get("dst_hotness_bucket")
    if bucket is None:
        bucket = (item_profiles.get(str(row.get("dst_item_id") or "")) or {}).get("hotness_bucket")
    return str(bucket or "") == "hot"


def _hot_budget_diagnostics(
    rows: list[dict[str, Any]], item_profiles: dict[str, dict[str, Any]], config: AugCFLiteConfig
) -> dict[str, Any]:
    per_src_counts: dict[str, Counter[str]] = defaultdict(Counter)
    for row in rows:
        src = str(row.get("src_item_id") or "")
        if not src:
            continue
        per_src_counts[src]["total"] += 1
        if _row_is_hot(row, item_profiles):
            per_src_counts[src]["hot"] += 1
    hot_shares = [counts["hot"] / counts["total"] for counts in per_src_counts.values() if counts["total"] > 0]
    violations = [src for src, counts in per_src_counts.items() if counts["total"] > 0 and counts["hot"] / counts["total"] > config.max_hot_share_per_src]
    return {
        "schema_version": "itemcf_strong_augcf_lite_hot_budget_diagnostics_v1",
        "per_src_hot_budget_only": True,
        "user_level_hot_share_not_guaranteed_by_builder": True,
        "route_level_hot_budget_required": True,
        "hot_budget_policy": DEFAULT_HOT_BUDGET_POLICY,
        "controlled_hot_budget": config.controlled_hot_budget,
        "max_hot_share_per_src": config.max_hot_share_per_src,
        "final_user_hot_budget_policy": DEFAULT_FINAL_USER_HOT_BUDGET_POLICY,
        "max_final_hot_share_per_user": config.max_final_hot_share_per_user,
        "src_item_count": len(per_src_counts),
        "src_with_hot_edges_count": sum(1 for counts in per_src_counts.values() if counts["hot"] > 0),
        "selected_hot_edge_count": sum(counts["hot"] for counts in per_src_counts.values()),
        "selected_edge_count": sum(counts["total"] for counts in per_src_counts.values()),
        "max_observed_hot_share_per_src": round(max(hot_shares), 6) if hot_shares else 0.0,
        "per_src_hot_share_violation_count": len(violations) if config.controlled_hot_budget else 0,
        "per_src_hot_share_violation_examples": violations[:20] if config.controlled_hot_budget else [],
    }


def _observed_edge_row(
    src: str,
    dst: str,
    support: int,
    weighted_cooc: float,
    item_profiles: dict[str, dict[str, Any]],
    config: AugCFLiteConfig,
) -> dict[str, Any] | None:
    src_profile = item_profiles.get(src) or {}
    dst_profile = item_profiles.get(dst) or {}
    if not _item_allowed(src_profile) or not _item_allowed(dst_profile, allow_hot=config.allow_hot_dst):
        return None
    src_user_count = _user_count(src_profile)
    dst_user_count = _user_count(dst_profile)
    if src_user_count <= 0 or dst_user_count <= 0:
        return None
    base_score = weighted_cooc / math.sqrt(src_user_count * dst_user_count)
    aug_score = _metadata_pair_score(src_profile, dst_profile, base_score=base_score, observed=True)
    score = round(max(base_score, 0.2 + 0.2 * aug_score), 6)
    return {
        "schema_version": ROW_SCHEMA_VERSION,
        "source_method": "itemcf_strong",
        "source_variant": config.source_variant,
        "train_only": True,
        "dataset_role": "augcf_lite_itemcf_edge_feature",
        "src_item_id": src,
        "dst_item_id": dst,
        "item_i": src,
        "item_j": dst,
        "edge_type": "observed_strong",
        "pair_support": support,
        "cooc_cnt": support,
        "weighted_cooc": round(weighted_cooc, 6),
        "base_itemcf_score": round(base_score, 6),
        "augcf_lite_score": round(aug_score, 6),
        "itemcf_score": score,
        "score_policy": "observed_strong_augcf_lite_metadata_fusion_v1",
        "src_user_count": src_user_count,
        "dst_user_count": dst_user_count,
        "same_category": _same(src_profile.get("category"), dst_profile.get("category")),
        "same_main_category": _same(src_profile.get("main_category"), dst_profile.get("main_category")),
        "same_store": _same(src_profile.get("store"), dst_profile.get("store")),
        "src_hotness_bucket": src_profile.get("hotness_bucket"),
        "src_quality_bucket_v2": src_profile.get("quality_bucket_v2"),
        "dst_hotness_bucket": dst_profile.get("hotness_bucket"),
        "dst_quality_bucket_v2": dst_profile.get("quality_bucket_v2"),
        "dst_global_pop_rank": int(dst_profile.get("global_pop_rank") or 0),
        "dst_category_pop_rank": int(dst_profile.get("category_pop_rank") or 0),
        "pseudo_confidence": 1.0,
        "pseudo_confidence_reason": "observed_strong_train_cooccurrence",
        "edge_rank": 0,
        "seed": config.seed,
    }


def _pseudo_edge_row(src: str, dst: str, item_profiles: dict[str, dict[str, Any]], config: AugCFLiteConfig) -> dict[str, Any] | None:
    src_profile = item_profiles.get(src) or {}
    dst_profile = item_profiles.get(dst) or {}
    if not _item_allowed(src_profile) or not _item_allowed(dst_profile, allow_hot=config.allow_hot_dst):
        return None
    src_user_count = _user_count(src_profile)
    dst_user_count = _user_count(dst_profile)
    if src_user_count <= 0 or dst_user_count <= 0:
        return None
    aug_score = _metadata_pair_score(src_profile, dst_profile, base_score=0.0, observed=False)
    if aug_score <= 0:
        return None
    score = round(0.02 + 0.16 * aug_score, 6)
    confidence = round(min(0.95, max(0.05, aug_score)), 6)
    confidence_reasons = []
    if _same(src_profile.get("category"), dst_profile.get("category")):
        confidence_reasons.append("same_category")
    if _same(src_profile.get("main_category"), dst_profile.get("main_category")):
        confidence_reasons.append("same_main_category")
    if _same(src_profile.get("store"), dst_profile.get("store")):
        confidence_reasons.append("same_store")
    if dst_profile.get("quality_bucket_v2") in DEFAULT_ALLOWED_ITEM_BUCKETS:
        confidence_reasons.append("dst_quality_allowed")
    confidence_reason = "metadata_prior:" + "+".join(confidence_reasons or ["positive_metadata_score"])
    return {
        "schema_version": ROW_SCHEMA_VERSION,
        "source_method": "itemcf_strong",
        "source_variant": config.source_variant,
        "train_only": True,
        "dataset_role": "augcf_lite_itemcf_edge_feature",
        "src_item_id": src,
        "dst_item_id": dst,
        "item_i": src,
        "item_j": dst,
        "edge_type": "pseudo_augcf_lite",
        "pair_support": 0,
        "cooc_cnt": 0,
        "weighted_cooc": 0.0,
        "base_itemcf_score": 0.0,
        "augcf_lite_score": round(aug_score, 6),
        "itemcf_score": score,
        "score_policy": "pseudo_augcf_lite_train_only_metadata_scorer_v1",
        "src_user_count": src_user_count,
        "dst_user_count": dst_user_count,
        "same_category": _same(src_profile.get("category"), dst_profile.get("category")),
        "same_main_category": _same(src_profile.get("main_category"), dst_profile.get("main_category")),
        "same_store": _same(src_profile.get("store"), dst_profile.get("store")),
        "src_hotness_bucket": src_profile.get("hotness_bucket"),
        "src_quality_bucket_v2": src_profile.get("quality_bucket_v2"),
        "dst_hotness_bucket": dst_profile.get("hotness_bucket"),
        "dst_quality_bucket_v2": dst_profile.get("quality_bucket_v2"),
        "dst_global_pop_rank": int(dst_profile.get("global_pop_rank") or 0),
        "dst_category_pop_rank": int(dst_profile.get("category_pop_rank") or 0),
        "pseudo_confidence": confidence,
        "pseudo_confidence_reason": confidence_reason,
        "edge_rank": 0,
        "seed": config.seed,
    }


def _pseudo_candidates_for_src(
    src: str,
    src_profile: dict[str, Any],
    category_pools: dict[str, list[str]],
    item_profiles: dict[str, dict[str, Any]],
    config: AugCFLiteConfig,
) -> list[str]:
    candidates: dict[str, float] = {}
    scan_limit = max(config.pseudo_per_src * 4, config.top_k_per_src, 50)
    if config.max_pseudo_scan_per_key > 0:
        scan_limit = min(scan_limit, config.max_pseudo_scan_per_key)
    for key in _category_keys(src_profile):
        for dst in category_pools.get(key, [])[:scan_limit]:
            if dst == src:
                continue
            dst_profile = item_profiles.get(dst) or {}
            score = _metadata_pair_score(src_profile, dst_profile, base_score=0.0, observed=False)
            if score > candidates.get(dst, -1.0):
                candidates[dst] = score
    return [item_id for item_id, _score in sorted(candidates.items(), key=lambda item: (-item[1], item[0]))]


def _metadata_pair_score(src_profile: dict[str, Any], dst_profile: dict[str, Any], *, base_score: float, observed: bool) -> float:
    same_category = _same(src_profile.get("category"), dst_profile.get("category"))
    same_main_category = _same(src_profile.get("main_category"), dst_profile.get("main_category"))
    same_store = _same(src_profile.get("store"), dst_profile.get("store"))
    dst_strong = math.log1p(int(dst_profile.get("train_strong_positive_count") or 0)) / 8.0
    dst_positive = math.log1p(int(dst_profile.get("train_positive_count") or dst_profile.get("positive_event_count") or 0)) / 10.0
    dst_users = math.log1p(_user_count(dst_profile)) / 12.0
    quality_boost = 0.06 if dst_profile.get("quality_bucket_v2") in DEFAULT_ALLOWED_ITEM_BUCKETS else 0.0
    hot_penalty = 0.08 if dst_profile.get("hotness_bucket") == "hot" else 0.0
    score = 0.0
    score += 0.24 if same_category else 0.0
    score += 0.12 if same_main_category else 0.0
    score += 0.06 if same_store else 0.0
    score += min(dst_strong, 0.20)
    score += min(dst_positive, 0.16)
    score += min(dst_users, 0.10)
    score += quality_boost
    score += min(base_score * 20.0, 0.15)
    score += 0.10 if observed else 0.0
    score -= hot_penalty
    return max(0.0, min(score, 1.0))


def _item_prior_score(profile: dict[str, Any]) -> float:
    strong = math.log1p(int(profile.get("train_strong_positive_count") or 0))
    positive = math.log1p(int(profile.get("train_positive_count") or profile.get("positive_event_count") or 0))
    users = math.log1p(_user_count(profile))
    quality = 2.0 if profile.get("quality_bucket_v2") in DEFAULT_ALLOWED_ITEM_BUCKETS else 0.0
    hot_penalty = 0.5 if profile.get("hotness_bucket") == "hot" else 0.0
    return strong * 3.0 + positive * 1.5 + users + quality - hot_penalty


def _category_keys(profile: dict[str, Any]) -> list[str]:
    keys = []
    category = str(profile.get("category") or "")
    main_category = str(profile.get("main_category") or "")
    store = str(profile.get("store") or "")
    if category:
        keys.append(f"category:{category}")
    if main_category:
        keys.append(f"main:{main_category}")
    if store:
        keys.append(f"store:{store}")
    return keys


def _item_allowed(profile: dict[str, Any] | None, *, allow_hot: bool = True) -> bool:
    if not profile:
        return False
    if not allow_hot and profile.get("hotness_bucket") == "hot":
        return False
    bucket = str(profile.get("quality_bucket_v2") or "")
    return bool(profile.get("cf_ready") or profile.get("embedding_ready") or bucket in DEFAULT_ALLOWED_ITEM_BUCKETS)


def _user_count(profile: dict[str, Any]) -> int:
    return int(profile.get("unique_positive_user_count") or profile.get("user_count") or profile.get("frequency") or 0)


def _recent_unique(values: Any, limit: int) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    raw = [str(value) for value in (values or []) if value]
    for item_id in reversed(raw):
        if item_id in seen:
            continue
        seen.add(item_id)
        out.append(item_id)
        if limit > 0 and len(out) >= limit:
            break
    return list(reversed(out))


def _same(left: Any, right: Any) -> bool:
    return bool(left) and bool(right) and str(left) == str(right)


def _edge_type_priority(edge_type: str) -> int:
    return 0 if edge_type == "observed_strong" else 1


def _iter_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                yield json.loads(line)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _file_signature(path: Path) -> dict[str, Any]:
    digest = hashlib.sha256()
    row_count = 0
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
            row_count += chunk.count(b"\n")
    return {"path": str(path), "sha256": digest.hexdigest(), "size_bytes": path.stat().st_size, "row_count": row_count}


def _leakage_audit(read_files: list[str]) -> dict[str, Any]:
    forbidden = [path for path in read_files if is_forbidden_itemcf_input(path) or _contains_forbidden_token(path)]
    return {
        "schema_version": "itemcf_strong_augcf_lite_leakage_audit_v1",
        "status": "PASS" if not forbidden else "FAIL",
        "train_only": True,
        "labels_role": "none_in_training_or_candidate_generation",
        "forbidden_read_files": forbidden,
        "read_files": read_files,
    }


def _contains_forbidden_token(path: str) -> bool:
    normalized = str(path).replace("\\", "/").lower()
    filename = normalized.rsplit("/", 1)[-1]
    if filename in {"canonical_interactions.train.jsonl", "user_sequences.train.jsonl"}:
        return False
    return any(token in normalized for token in FORBIDDEN_INPUT_TOKENS)


def _config_dict(config: AugCFLiteConfig) -> dict[str, Any]:
    return {
        "data_root": str(config.data_root),
        "output_dir": str(config.output_dir),
        "run_id": config.run_id,
        "limit_users": config.limit_users,
        "max_src_items": config.max_src_items,
        "top_k_per_src": config.top_k_per_src,
        "pseudo_per_src": config.pseudo_per_src,
        "category_pool_size": config.category_pool_size,
        "max_pseudo_scan_per_key": config.max_pseudo_scan_per_key,
        "max_items_per_user": config.max_items_per_user,
        "max_pairs_per_user": config.max_pairs_per_user,
        "min_pair_support": config.min_pair_support,
        "edge_mode": config.edge_mode,
        "allow_hot_dst": config.allow_hot_dst,
        "max_hot_share_per_src": config.max_hot_share_per_src,
        "controlled_hot_budget": config.controlled_hot_budget,
        "source_variant": config.source_variant,
        "max_final_hot_share_per_user": config.max_final_hot_share_per_user,
        "max_pseudo_per_user": config.max_pseudo_per_user,
        "hot_budget_policy": DEFAULT_HOT_BUDGET_POLICY,
        "final_user_hot_budget_policy": DEFAULT_FINAL_USER_HOT_BUDGET_POLICY,
        "pseudo_confidence_policy": DEFAULT_PSEUDO_CONFIDENCE_POLICY,
        "augmentation_user_eligibility": DEFAULT_AUGMENTATION_USER_ELIGIBILITY,
        "candidate_generation_allowed": False,
        "ranking_input_replacement_allowed": False,
        "promotion_allowed": False,
        "final_pool500_ready_claimed": False,
        "seed": config.seed,
    }
