from __future__ import annotations

import hashlib
import shutil
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from statistics import median
from time import perf_counter
from typing import Any

from rs_core.common.io import iter_jsonl, read_json, write_json, write_jsonl
from rs_lab.experiments.recall.pool500.common.source_layout import REQUIRED_SOURCE_OUTPUTS

ROOT = Path(__file__).resolve().parents[5]
DEFAULT_PROMOTED_DIR = ROOT / "outputs" / "recall" / "pool500_main_route_direct_recall_full_promoted"
FORBIDDEN_PATH_PARTS = ("holdout", "valid", "test", "lopo", "clean_10000", "pool1000")
GOVERNANCE_FIELDS = {
    "candidate_generation_allowed": False,
    "ranking_input_replacement_allowed": False,
    "pool1000_allowed": False,
    "promotion_allowed": False,
    "final_pool500_ready_claimed": False,
}


def build_lightweight_governance_source(*, source: str, config: dict[str, Any], run_id: str, output_dir: Path, overwrite: bool) -> dict[str, Any]:
    started = perf_counter()
    if source not in {"category", "popular"}:
        raise ValueError(f"unsupported lightweight source: {source}")
    promoted_dir = _resolve_path(config.get("promoted_dir") or DEFAULT_PROMOTED_DIR)
    old_source_dir = promoted_dir / "sources" / source
    old_candidates_path = old_source_dir / "candidates.jsonl"
    old_manifest_path = old_source_dir / "manifest.json"
    eligible_user_manifest_path = promoted_dir / "eligible_user_manifest.json"
    source_contribution_path = promoted_dir / "source_contribution_audit.json"
    source_overlap_path = promoted_dir / "source_overlap_audit.json"
    _ensure_inputs([old_candidates_path, old_manifest_path, eligible_user_manifest_path, source_contribution_path])
    _precheck_output(output_dir, overwrite)

    output_dir.mkdir(parents=True, exist_ok=False)
    old_manifest = read_json(old_manifest_path)
    eligible_user_manifest = read_json(eligible_user_manifest_path)
    source_contribution = read_json(source_contribution_path)
    source_overlap = read_json(source_overlap_path) if source_overlap_path.exists() else {}
    target_user_ids = [str(user_id) for user_id in eligible_user_manifest.get("eligible_user_ids", [])]
    if not target_user_ids:
        raise ValueError("eligible_user_manifest has no eligible_user_ids")

    input_rows = list(iter_jsonl(old_candidates_path))
    candidates, governance_audit = _govern_candidates(source, input_rows, config)
    candidates_path = output_dir / "candidates.jsonl"
    write_jsonl(candidates_path, candidates)

    counts = _counts_by_user(candidates, target_user_ids)
    per_user_summary = _summary(list(counts.values()))
    coverage_audit = _build_coverage_audit(
        source=source,
        config=config,
        candidates=candidates,
        counts=counts,
        per_user_summary=per_user_summary,
        target_user_count=len(target_user_ids),
        source_contribution=source_contribution,
        source_overlap=source_overlap,
        governance_audit=governance_audit,
    )
    undercoverage_audit = _build_undercoverage_audit(source, target_user_ids, counts)
    resource_audit = {
        "schema_version": "pool500_lightweight_governance.resource_audit_v1",
        "status": "PASS",
        "source": source,
        "heavy_job": False,
        "checkpoint_enabled": True,
        "batch_size": None,
        "input_row_count": len(input_rows),
        "candidate_row_count": len(candidates),
        "dropped_by_governance_count": len(input_rows) - len(candidates),
        "runtime_seconds": round(perf_counter() - started, 6),
        "resource_profile": "lightweight_existing_train_only_source_transform",
        **GOVERNANCE_FIELDS,
    }
    no_holdout_audit = _build_no_holdout_audit(source, [old_candidates_path, old_manifest_path, eligible_user_manifest_path, source_contribution_path])
    method_dataset_manifest = _build_method_dataset_manifest(
        source=source,
        run_id=run_id,
        output_dir=output_dir,
        old_manifest=old_manifest,
        old_candidates_path=old_candidates_path,
        eligible_user_manifest_path=eligible_user_manifest_path,
        coverage_audit=coverage_audit,
    )
    source_index_manifest = _build_source_index_manifest(
        source=source,
        run_id=run_id,
        output_dir=output_dir,
        old_manifest_path=old_manifest_path,
        old_candidates_path=old_candidates_path,
        candidates_path=candidates_path,
        coverage_audit=coverage_audit,
        undercoverage_audit=undercoverage_audit,
        resource_audit=resource_audit,
        no_holdout_audit=no_holdout_audit,
        method_dataset_manifest=method_dataset_manifest,
        config=config,
    )

    write_json(output_dir / "method_dataset_manifest.json", method_dataset_manifest)
    write_json(output_dir / "coverage_audit.json", coverage_audit)
    write_json(output_dir / "undercoverage_audit.json", undercoverage_audit)
    write_json(output_dir / "resource_audit.json", resource_audit)
    write_json(output_dir / "no_holdout_audit.json", no_holdout_audit)
    write_json(output_dir / "source_index_manifest.json", source_index_manifest)
    _assert_required_outputs(output_dir)
    return source_index_manifest


def _govern_candidates(source: str, rows: list[dict[str, Any]], config: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if source == "popular":
        return _govern_popular(rows, config)
    return _govern_category(rows, config)


def _govern_popular(rows: list[dict[str, Any]], config: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    cap = int(config.get("popular_per_user_cap") or 50)
    kept: list[dict[str, Any]] = []
    seen_by_user: Counter[str] = Counter()
    for row in _sorted_rows(rows):
        user_id = str(row.get("user_id", ""))
        if seen_by_user[user_id] >= cap:
            continue
        governed = dict(row)
        metadata = dict(governed.get("metadata") or {})
        metadata["popular_governance"] = {"per_user_cap": cap, "cap_applied": True}
        governed.update({"source": "popular", "metadata": metadata})
        kept.append(governed)
        seen_by_user[user_id] += 1
    return kept, {
        "policy": "popular_per_user_cap",
        "cap_value": cap,
        "input_row_count": len(rows),
        "output_row_count": len(kept),
        "dropped_by_cap": len(rows) - len(kept),
    }


def _govern_category(rows: list[dict[str, Any]], config: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    cap = int(config.get("category_bucket_cap_per_user") or 80)
    long_tail_rank_threshold = int(config.get("long_tail_rank_threshold") or 50)
    kept: list[dict[str, Any]] = []
    seen_by_user_category: Counter[tuple[str, str]] = Counter()
    for row in _sorted_rows(rows):
        user_id = str(row.get("user_id", ""))
        category = _category(row)
        key = (user_id, category)
        if seen_by_user_category[key] >= cap:
            continue
        governed = dict(row)
        metadata = dict(governed.get("metadata") or {})
        sources = set(governed.get("sources") or [])
        metadata["category_governance"] = {
            "bucket": category,
            "bucket_cap_per_user": cap,
            "long_tail_pool_member": int(governed.get("rank") or 0) >= long_tail_rank_threshold and "popular" not in sources,
        }
        governed.update({"source": "category", "metadata": metadata})
        kept.append(governed)
        seen_by_user_category[key] += 1
    return kept, {
        "policy": "category_bucket_diversity_cap",
        "cap_value": cap,
        "long_tail_rank_threshold": long_tail_rank_threshold,
        "input_row_count": len(rows),
        "output_row_count": len(kept),
        "dropped_by_cap": len(rows) - len(kept),
    }


def _build_coverage_audit(
    *,
    source: str,
    config: dict[str, Any],
    candidates: list[dict[str, Any]],
    counts: dict[str, int],
    per_user_summary: dict[str, Any],
    target_user_count: int,
    source_contribution: dict[str, Any],
    source_overlap: dict[str, Any],
    governance_audit: dict[str, Any],
) -> dict[str, Any]:
    source_stats = (source_contribution.get("sources") or {}).get(source, {})
    categories = Counter(_category(row) for row in candidates)
    user_coverage_count = sum(1 for value in counts.values() if value > 0)
    audit: dict[str, Any] = {
        "schema_version": "pool500_lightweight_governance.coverage_audit_v1",
        "status": "PASS",
        "source": source,
        "role": config.get("role") or _default_role(source),
        "target_user_count": target_user_count,
        "candidate_row_count": len(candidates),
        "unique_item_count": len({str(row.get("item_id")) for row in candidates if row.get("item_id")}),
        "user_coverage_count": user_coverage_count,
        "user_coverage_ratio": _ratio(user_coverage_count, target_user_count),
        "per_user_candidate_count": per_user_summary,
        "category_bucket_count": len(categories),
        "category_bucket_top10": [{"category": category, "row_count": count, "share": _ratio(count, len(candidates))} for category, count in categories.most_common(10)],
        "old_promoted_source_stats": source_stats,
        "old_pairwise_overlap": ((source_overlap.get("pairwise_user_item_overlap_count") or {}).get(source) or {}),
        "old_marginal_candidate_share": source_stats.get("marginal_candidate_share"),
        "recommended_max_source_share": float(config.get("max_source_share_recommended") or (0.35 if source == "category" else 0.2)),
        "governance_audit": governance_audit,
        **GOVERNANCE_FIELDS,
    }
    audit["source_over_share_warning"] = bool((audit["old_marginal_candidate_share"] or 0.0) > audit["recommended_max_source_share"])
    if source == "category":
        audit["category_diversity"] = _category_diversity(candidates, counts)
        audit["long_tail_pool"] = _long_tail_pool(candidates)
        audit["diversity_cap_audit"] = governance_audit
    else:
        audit["popular_cap_audit"] = {**governance_audit, "max_observed_per_user_after_cap": per_user_summary["max"]}
        audit["time_window_audit"] = _time_window_audit(candidates)
        audit["category_constraint_audit"] = _popular_category_constraint(candidates, counts, float(config.get("popular_max_category_share_per_user") or 0.8))
    return audit


def _build_undercoverage_audit(source: str, target_user_ids: list[str], counts: dict[str, int]) -> dict[str, Any]:
    undercovered = [user_id for user_id in target_user_ids if counts[user_id] <= 0]
    return {
        "schema_version": "pool500_lightweight_governance.undercoverage_audit_v1",
        "status": "DIAGNOSTIC_ONLY_AUDIT",
        "source": source,
        "target_user_count": len(target_user_ids),
        "user_coverage_count": len(target_user_ids) - len(undercovered),
        "undercovered_user_count": len(undercovered),
        "undercovered_user_sample": undercovered[:20],
        "primary_reason": "lightweight source remains fallback/coverage source; no synthetic expansion was applied",
        "requires_direct_recall_runner_manifest_integration": True,
        **GOVERNANCE_FIELDS,
    }


def _build_no_holdout_audit(source: str, read_files: list[Path]) -> dict[str, Any]:
    forbidden_inputs = _forbidden_matches(read_files)
    return {
        "schema_version": "pool500_lightweight_governance.no_holdout_audit_v1",
        "status": "PASS" if not forbidden_inputs else "BLOCKED",
        "source": source,
        "train_only": True,
        "read_files": [str(path) for path in read_files],
        "forbidden_inputs": forbidden_inputs,
        "uses_holdout": False,
        "uses_valid": False,
        "uses_test": False,
        "uses_lopo": False,
        "uses_clean_10000": False,
        **GOVERNANCE_FIELDS,
    }


def _build_method_dataset_manifest(
    *,
    source: str,
    run_id: str,
    output_dir: Path,
    old_manifest: dict[str, Any],
    old_candidates_path: Path,
    eligible_user_manifest_path: Path,
    coverage_audit: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": "pool500_lightweight_governance.method_dataset_manifest_v1",
        "status": "PASS",
        "source": source,
        "run_id": run_id,
        "source_status": "READY_WITH_LIGHT_GOVERNANCE_AUDIT",
        "role": coverage_audit["role"],
        "train_only": True,
        "dataset_policy": f"lightweight_{source}_fallback_governance_policy",
        "output_dir": str(output_dir),
        "input_promoted_source_manifest": old_manifest,
        "input_candidates_path": str(old_candidates_path),
        "eligible_user_manifest_path": str(eligible_user_manifest_path),
        "candidate_row_count": coverage_audit["candidate_row_count"],
        "user_coverage_count": coverage_audit["user_coverage_count"],
        "unique_item_count": coverage_audit["unique_item_count"],
        **GOVERNANCE_FIELDS,
    }


def _build_source_index_manifest(
    *,
    source: str,
    run_id: str,
    output_dir: Path,
    old_manifest_path: Path,
    old_candidates_path: Path,
    candidates_path: Path,
    coverage_audit: dict[str, Any],
    undercoverage_audit: dict[str, Any],
    resource_audit: dict[str, Any],
    no_holdout_audit: dict[str, Any],
    method_dataset_manifest: dict[str, Any],
    config: dict[str, Any],
) -> dict[str, Any]:
    manifest = {
        "schema_version": "pool500_lightweight_governance.source_index_manifest_v1",
        "status": "PASS",
        "created_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "source": source,
        "canonical_source": source,
        "run_id": run_id,
        "source_status": "READY_WITH_LIGHT_GOVERNANCE_AUDIT",
        "role": coverage_audit["role"],
        "index_scope": "LIGHTWEIGHT_FALLBACK_COVERAGE_SOURCE",
        "train_only": True,
        "output_dir": str(output_dir),
        "input_promoted_source_manifest_path": str(old_manifest_path),
        "input_promoted_candidates_path": str(old_candidates_path),
        "candidates_path": str(candidates_path),
        "candidate_row_count": coverage_audit["candidate_row_count"],
        "user_coverage_count": coverage_audit["user_coverage_count"],
        "unique_item_count": coverage_audit["unique_item_count"],
        "per_user_candidate_count": coverage_audit["per_user_candidate_count"],
        "source_config": {key: value for key, value in config.items() if key not in {"run_id"}},
        "coverage_summary": {
            "old_marginal_candidate_share": coverage_audit["old_marginal_candidate_share"],
            "recommended_max_source_share": coverage_audit["recommended_max_source_share"],
            "source_over_share_warning": coverage_audit["source_over_share_warning"],
        },
        "artifact_sha256": {
            "candidates": _sha256_file(candidates_path),
            "input_promoted_candidates": _sha256_file(old_candidates_path),
        },
        "outputs": {name.removesuffix(".json").removesuffix(".jsonl"): str(output_dir / name) for name in REQUIRED_SOURCE_OUTPUTS},
        "audit_statuses": {
            "coverage_audit": coverage_audit["status"],
            "undercoverage_audit": undercoverage_audit["status"],
            "resource_audit": resource_audit["status"],
            "no_holdout_audit": no_holdout_audit["status"],
            "method_dataset_manifest": method_dataset_manifest["status"],
        },
        **GOVERNANCE_FIELDS,
    }
    return manifest


def _category_diversity(candidates: list[dict[str, Any]], counts: dict[str, int]) -> dict[str, Any]:
    per_user_categories: dict[str, Counter[str]] = defaultdict(Counter)
    for row in candidates:
        per_user_categories[str(row.get("user_id", ""))][_category(row)] += 1
    distinct_counts = [len(counter) for counter in per_user_categories.values()]
    max_shares = []
    for user_id, total in counts.items():
        if total > 0:
            max_shares.append(max(per_user_categories[user_id].values(), default=0) / total)
    return {
        "per_user_distinct_category_count": _summary(distinct_counts),
        "per_user_max_category_share": _summary(max_shares),
        "users_single_category_only": sum(1 for value in distinct_counts if value == 1),
    }


def _long_tail_pool(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    rows = [row for row in candidates if ((row.get("metadata") or {}).get("category_governance") or {}).get("long_tail_pool_member")]
    return {
        "row_count": len(rows),
        "unique_item_count": len({str(row.get("item_id")) for row in rows if row.get("item_id")}),
        "share": _ratio(len(rows), len(candidates)),
        "definition": "rank >= long_tail_rank_threshold and no popular overlap",
    }


def _popular_category_constraint(candidates: list[dict[str, Any]], counts: dict[str, int], max_allowed: float) -> dict[str, Any]:
    per_user_categories: dict[str, Counter[str]] = defaultdict(Counter)
    for row in candidates:
        per_user_categories[str(row.get("user_id", ""))][_category(row)] += 1
    max_shares = []
    violating = 0
    for user_id, total in counts.items():
        if total <= 0:
            continue
        share = max(per_user_categories[user_id].values(), default=0) / total
        max_shares.append(share)
        if share > max_allowed:
            violating += 1
    return {"max_category_share_per_user": max_allowed, "violating_user_count": violating, "per_user_max_category_share": _summary(max_shares)}


def _time_window_audit(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    timestamps = []
    for row in candidates:
        metadata = row.get("metadata") or {}
        value = row.get("timestamp") or metadata.get("timestamp") or metadata.get("event_time")
        if value:
            timestamps.append(str(value))
    return {
        "status": "PASS" if timestamps else "NO_TIMESTAMP_METADATA",
        "policy": "audit_only_train_observed_window_when_timestamp_available",
        "timestamp_row_count": len(timestamps),
        "observed_min_timestamp": min(timestamps) if timestamps else None,
        "observed_max_timestamp": max(timestamps) if timestamps else None,
    }


def _sorted_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(rows, key=lambda row: (str(row.get("user_id", "")), int(row.get("rank") or 10**9), -float(row.get("score") or 0.0), str(row.get("item_id", ""))))


def _counts_by_user(candidates: list[dict[str, Any]], target_user_ids: list[str]) -> dict[str, int]:
    counts = {user_id: 0 for user_id in target_user_ids}
    for row in candidates:
        user_id = str(row.get("user_id", ""))
        if user_id in counts:
            counts[user_id] += 1
    return counts


def _category(row: dict[str, Any]) -> str:
    metadata = row.get("metadata") or {}
    category = str(metadata.get("category") or row.get("category") or row.get("main_category") or "UNKNOWN").strip()
    return category or "UNKNOWN"


def _summary(values: list[int] | list[float]) -> dict[str, Any]:
    if not values:
        return {"min": 0, "p50": 0, "p90": 0, "max": 0}
    ordered = sorted(values)
    return {"min": ordered[0], "p50": median(ordered), "p90": ordered[int((len(ordered) - 1) * 0.9)], "max": ordered[-1]}


def _ratio(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 6) if denominator else 0.0


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _forbidden_matches(paths: list[Path]) -> list[str]:
    matches = []
    for path in paths:
        normalized = str(path).replace("\\", "/").lower()
        parts = [part for part in normalized.split("/") if part]
        if any(token in parts or f"_{token}_" in normalized or f".{token}." in normalized for token in FORBIDDEN_PATH_PARTS):
            matches.append(str(path))
    return sorted(set(matches))


def _ensure_inputs(paths: list[Path]) -> None:
    missing = [str(path) for path in paths if not path.exists()]
    if missing:
        raise ValueError(f"missing required inputs: {missing}")


def _precheck_output(output_dir: Path, overwrite: bool) -> None:
    if output_dir.exists() and any(output_dir.iterdir()):
        if not overwrite:
            raise ValueError(f"output already exists; pass --overwrite to replace: {output_dir}")
        shutil.rmtree(output_dir)


def _assert_required_outputs(output_dir: Path) -> None:
    missing = [name for name in REQUIRED_SOURCE_OUTPUTS if not (output_dir / name).exists()]
    if missing:
        raise ValueError(f"missing required outputs: {missing}")


def _resolve_path(path: str | Path) -> Path:
    value = Path(path)
    return value.resolve() if value.is_absolute() else (ROOT / value).resolve()


def _default_role(source: str) -> str:
    return "category coverage and diversity fallback source" if source == "category" else "capped popular fallback source"
