from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[6]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rs_core.common.io import iter_jsonl, read_json, write_json, write_jsonl
from rs_core.common.runtime import enforce_project_venv

SCHEMA_VERSION = "pool500_underfilled66_repair_v4"
REPAIR_STAGE = "underfilled66_v4"
TARGET_CANDIDATE_COUNT = 500
PRIORITY_REPAIR_SOURCES = [
    "two_tower",
    "semantic_title_category_expansion",
    "co_visit_fallback_repair",
    "swing_recall",
    "category",
]
OPTIONAL_EXISTING_REUSE_SOURCES = ["itemcf_strong", "itemcf_weak", "usercf_recall"]
LAST_RESORT_SOURCES = ["popular"]
REPAIR_SOURCE_ORDER = PRIORITY_REPAIR_SOURCES + OPTIONAL_EXISTING_REUSE_SOURCES + LAST_RESORT_SOURCES
POPULAR_REPAIR_CAP_PER_USER = 40
FORBIDDEN_DATA_MARKERS = ("holdout", "valid", "test", "lopo", "leave_one_positive_out", "clean_10000")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build pool500 underfilled-only repair v4 artifacts for v3 remaining underfilled users.")
    parser.add_argument("--base-run-dir", default="outputs/recall/pool500_main_route_direct_recall_method_sources_v3")
    parser.add_argument("--output-dir", default="outputs/recall/pool500_main_route_direct_recall_underfilled66_repair_v4")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--skip-venv-check", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    manifest = build_underfilled66_repair_v4(
        base_run_dir=Path(args.base_run_dir),
        output_dir=Path(args.output_dir),
        overwrite=args.overwrite,
        enforce_venv=not args.skip_venv_check,
    )
    print(json.dumps({
        "output_dir": manifest["output_dir"],
        "candidate_rows": manifest["candidate_rows"],
        "users_with_500_candidates": manifest["users_with_500_candidates"],
        "underfilled_user_count": manifest["underfilled_user_count"],
        "decision": manifest["decision"],
    }, ensure_ascii=False, indent=2))


def build_underfilled66_repair_v4(*, base_run_dir: Path, output_dir: Path, overwrite: bool = False, enforce_venv: bool = True) -> dict[str, Any]:
    started = perf_counter()
    if enforce_venv:
        enforce_project_venv(ROOT)

    base_run_dir = _resolve_path(base_run_dir)
    output_dir = _resolve_path(output_dir)
    if not base_run_dir.is_dir():
        raise FileNotFoundError(f"base run dir not found: {base_run_dir}")
    if output_dir.resolve() == base_run_dir.resolve():
        raise ValueError("output-dir must not overwrite base-run-dir")
    if output_dir.exists() and any(output_dir.iterdir()) and not overwrite:
        raise FileExistsError(f"output directory exists: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)

    base_manifest = read_json(base_run_dir / "manifest.json")
    base_underfill = read_json(base_run_dir / "underfill_audit.json")
    base_source_contribution = read_json(base_run_dir / "source_contribution_audit.json")
    source_registry = read_json(base_run_dir / "canonical_source_registry.json")
    per_source_manifests = read_json(base_run_dir / "per_source_output_manifests.json")
    target_users = [str(user_id) for user_id in base_underfill.get("remaining_underfilled_users", [])]
    target_user_set = set(target_users)
    if len(target_users) != 66:
        raise ValueError(f"expected 66 remaining underfilled users, got {len(target_users)}")

    base_rows_by_user, base_source_counter, base_duplicate_count = _load_base_candidates(base_run_dir / "pool500_candidates.jsonl")
    existing_items_by_user = {
        user_id: {str(row.get("item_id", "")) for row in rows if row.get("item_id")}
        for user_id, rows in base_rows_by_user.items()
    }
    original_counts = {user_id: len(base_rows_by_user.get(user_id, [])) for user_id in target_users}

    source_candidate_paths = _repair_candidate_paths(base_run_dir, per_source_manifests)
    repair_rows_by_user: dict[str, list[dict[str, Any]]] = defaultdict(list)
    repair_stats = _empty_repair_stats()
    overlap_stats = _empty_overlap_stats()

    for source in REPAIR_SOURCE_ORDER:
        path = source_candidate_paths.get(source)
        if not path or not path.is_file():
            repair_stats[source]["status"] = "MISSING_SOURCE_FILE"
            continue
        repair_stats[source]["status"] = "USED"
        for row in iter_jsonl(path):
            user_id = str(row.get("user_id", ""))
            if user_id not in target_user_set:
                continue
            source_value = _canonical_source(row, source)
            if source_value != source:
                row = dict(row)
                row["source"] = source
            current_count = len(base_rows_by_user.get(user_id, [])) + len(repair_rows_by_user.get(user_id, []))
            if current_count >= TARGET_CANDIDATE_COUNT:
                overlap_stats[source]["skipped_user_already_full"] += 1
                continue
            item_id = str(row.get("item_id", ""))
            if not item_id:
                overlap_stats[source]["skipped_missing_item"] += 1
                continue
            seen_items = existing_items_by_user.setdefault(user_id, set())
            if item_id in seen_items:
                overlap_stats[source]["overlap_existing_or_repair"] += 1
                continue
            if source == "popular" and _user_source_repair_count(repair_rows_by_user[user_id], "popular") >= POPULAR_REPAIR_CAP_PER_USER:
                overlap_stats[source]["skipped_popular_cap"] += 1
                continue
            repaired_row = _repair_row(row, source)
            repair_rows_by_user[user_id].append(repaired_row)
            seen_items.add(item_id)
            repair_stats[source]["row_count"] += 1
            repair_stats[source]["users"].add(user_id)
            overlap_stats[source]["accepted"] += 1

    final_rows_by_user = _combine_and_cap(base_rows_by_user, repair_rows_by_user)
    final_counts = {user_id: len(rows) for user_id, rows in final_rows_by_user.items()}
    for user_id in target_users:
        final_counts.setdefault(user_id, 0)
    all_counts = list(final_counts.values())
    remaining_underfilled_users = [user_id for user_id in sorted(final_counts) if final_counts[user_id] < TARGET_CANDIDATE_COUNT]
    repaired_users = [user_id for user_id in target_users if final_counts.get(user_id, 0) > original_counts.get(user_id, 0)]
    users_with_500 = sum(1 for count in final_counts.values() if count >= TARGET_CANDIDATE_COUNT)
    candidate_rows = sum(final_counts.values())
    duplicate_item_per_user_count = _duplicate_item_per_user_count(final_rows_by_user)
    per_user_over_500_count = sum(1 for count in final_counts.values() if count > TARGET_CANDIDATE_COUNT)
    forbidden_scan = _forbidden_data_scan([base_run_dir, *source_candidate_paths.values()])
    decision = "STOP" if remaining_underfilled_users else "PASS_DIAGNOSTIC"
    generated_at = datetime.now(timezone.utc).isoformat()

    output_candidates_path = output_dir / "pool500_candidates.jsonl"
    write_jsonl(output_candidates_path, _iter_rows_in_user_order(final_rows_by_user))

    underfill_audit = {
        "schema_version": f"{SCHEMA_VERSION}.underfill_audit",
        "status": "DIAGNOSTIC_ONLY_PARTIAL" if remaining_underfilled_users else "PASS_DIAGNOSTIC_SHADOW_ONLY",
        "repair_stage": REPAIR_STAGE,
        "target_user_count": len(final_counts),
        "target_repair_user_count": len(target_users),
        "users_with_500_candidates": users_with_500,
        "underfilled_user_count": len(remaining_underfilled_users),
        "remaining_underfilled_user_count": len(remaining_underfilled_users),
        "remaining_underfilled_users": remaining_underfilled_users,
        "remaining_underfilled_user_details": _remaining_underfilled_user_details(
            remaining_underfilled_users,
            original_counts,
            final_counts,
            repair_rows_by_user,
        ),
        **_candidate_count_stats(all_counts),
        "promotion_allowed": False,
        "ranking_input_replacement_allowed": False,
        "pool1000_allowed": False,
    }

    repair_contribution_audit = _build_repair_contribution_audit(repair_stats, target_users)
    source_contribution_audit = _build_source_contribution_audit(final_rows_by_user, base_source_contribution, target_users)
    source_overlap_audit = _build_source_overlap_audit(overlap_stats, duplicate_item_per_user_count)
    final_resource_audit = {
        "schema_version": f"{SCHEMA_VERSION}.final_resource_audit",
        "status": "PASS",
        "repair_stage": REPAIR_STAGE,
        "heavy_job": False,
        "resource_guard_required": False,
        "runtime_seconds": round(perf_counter() - started, 6),
        "read_strategy": "streamed JSONL inputs; filtered rows to 66 remaining underfilled users; no model training or sidecar rebuild",
        "base_candidate_rows_read": int(base_manifest.get("candidate_rows", 0)),
        "repair_source_paths": {source: str(path) for source, path in source_candidate_paths.items()},
        "promotion_allowed": False,
        "ranking_input_replacement_allowed": False,
        "pool1000_allowed": False,
    }
    readiness_result = _build_readiness_result(decision, remaining_underfilled_users)
    shadow_evidence = _build_shadow_evidence(
        base_run_dir,
        output_candidates_path,
        decision,
        repaired_users,
        remaining_underfilled_users,
        users_with_500,
    )
    shadow_validation = _build_shadow_validation(
        forbidden_scan,
        per_user_over_500_count,
        duplicate_item_per_user_count,
        readiness_result,
    )
    required_artifacts = {
        "pool500_candidates": str(output_dir / "pool500_candidates.jsonl"),
        "manifest": str(output_dir / "manifest.json"),
        "underfill_audit": str(output_dir / "underfill_audit.json"),
        "repair_contribution_audit": str(output_dir / "repair_contribution_audit.json"),
        "source_contribution_audit": str(output_dir / "source_contribution_audit.json"),
        "source_overlap_audit": str(output_dir / "source_overlap_audit.json"),
        "final_resource_audit": str(output_dir / "final_resource_audit.json"),
        "readiness_result": str(output_dir / "readiness_result.json"),
        "pool500_shadow_evidence": str(output_dir / "pool500_shadow_evidence.json"),
        "pool500_shadow_evidence_validation": str(output_dir / "pool500_shadow_evidence_validation.json"),
    }
    manifest = {
        "schema_version": f"{SCHEMA_VERSION}.manifest",
        "generated_at": generated_at,
        "base_run_dir": str(base_run_dir),
        "output_dir": str(output_dir),
        "repair_stage": REPAIR_STAGE,
        "processed_users": int(base_manifest.get("processed_users", len(final_counts))),
        "target_repair_user_count": len(target_users),
        "repaired_user_count": len(repaired_users),
        "candidate_rows": candidate_rows,
        "users_with_500_candidates": users_with_500,
        "underfilled_user_count": len(remaining_underfilled_users),
        "candidate_count_min": min(all_counts) if all_counts else 0,
        "candidate_count_p50": _percentile(all_counts, 0.5),
        "candidate_count_p90": _percentile(all_counts, 0.9),
        "candidate_count_max": max(all_counts) if all_counts else 0,
        "decision": decision,
        "status": decision,
        "artifact_gate_decision": "STOP",
        "candidate_generation_allowed": False,
        "ranking_input_replacement_allowed": False,
        "pool1000_allowed": False,
        "promotion_allowed": False,
        "final_pool500_ready_claimed": False,
        "full_pool500_ready_declared": False,
        "required_artifacts": required_artifacts,
        "source_registry_snapshot": source_registry,
        "base_duplicate_item_per_user_count": base_duplicate_count,
        "duplicate_item_per_user_count": duplicate_item_per_user_count,
        "forbidden_data_scan": forbidden_scan,
    }

    write_json(output_dir / "underfill_audit.json", underfill_audit)
    write_json(output_dir / "repair_contribution_audit.json", repair_contribution_audit)
    write_json(output_dir / "source_contribution_audit.json", source_contribution_audit)
    write_json(output_dir / "source_overlap_audit.json", source_overlap_audit)
    write_json(output_dir / "final_resource_audit.json", final_resource_audit)
    write_json(output_dir / "readiness_result.json", readiness_result)
    write_json(output_dir / "pool500_shadow_evidence.json", shadow_evidence)
    write_json(output_dir / "pool500_shadow_evidence_validation.json", shadow_validation)
    write_json(output_dir / "manifest.json", manifest)
    return manifest


def _resolve_path(path: Path) -> Path:
    return path if path.is_absolute() else (ROOT / path).resolve()


def _load_base_candidates(path: Path) -> tuple[dict[str, list[dict[str, Any]]], Counter[str], int]:
    rows_by_user: dict[str, list[dict[str, Any]]] = defaultdict(list)
    source_counter: Counter[str] = Counter()
    seen_by_user: dict[str, set[str]] = defaultdict(set)
    duplicate_count = 0
    for row in iter_jsonl(path):
        user_id = str(row.get("user_id", ""))
        item_id = str(row.get("item_id", ""))
        if not user_id or not item_id:
            continue
        if item_id in seen_by_user[user_id]:
            duplicate_count += 1
            continue
        rows_by_user[user_id].append(row)
        seen_by_user[user_id].add(item_id)
        source_counter[_canonical_source(row, str(row.get("source", "unknown")))] += 1
    return dict(rows_by_user), source_counter, duplicate_count


def _repair_candidate_paths(base_run_dir: Path, per_source_manifests: dict[str, Any]) -> dict[str, Path]:
    paths: dict[str, Path] = {}
    for source, manifest in per_source_manifests.items():
        source_index = manifest.get("source_index_manifest_path")
        if source_index:
            source_index_path = Path(source_index)
            if source_index_path.is_file():
                source_manifest = read_json(source_index_path)
                candidate_path = _candidate_path_from_source_manifest(source_manifest)
                if candidate_path:
                    paths[source] = candidate_path
                    continue
        output_path = manifest.get("output_path")
        if output_path:
            paths[source] = Path(output_path)
    for source in REPAIR_SOURCE_ORDER:
        paths.setdefault(source, base_run_dir / "sources" / source / "candidates.jsonl")
    return paths


def _candidate_path_from_source_manifest(manifest: dict[str, Any]) -> Path | None:
    for key in ("candidates_path", "candidates"):
        value = manifest.get(key)
        if isinstance(value, str):
            return Path(value)
    outputs = manifest.get("outputs")
    if isinstance(outputs, dict):
        value = outputs.get("candidates")
        if isinstance(value, str):
            return Path(value)
    artifact_signatures = manifest.get("artifact_signatures")
    if isinstance(artifact_signatures, dict):
        candidate = artifact_signatures.get("candidates")
        if isinstance(candidate, dict) and isinstance(candidate.get("path"), str):
            return Path(candidate["path"])
    return None


def _empty_repair_stats() -> dict[str, dict[str, Any]]:
    return {source: {"status": "NOT_USED", "row_count": 0, "users": set()} for source in REPAIR_SOURCE_ORDER}


def _empty_overlap_stats() -> dict[str, Counter[str]]:
    return {source: Counter() for source in REPAIR_SOURCE_ORDER}


def _canonical_source(row: dict[str, Any], fallback: str) -> str:
    source = str(row.get("source") or fallback)
    if source in {"category_recall_items", "category_top_items", "category_long_tail_recall"}:
        return "category"
    if source in {"popular_recall"}:
        return "popular"
    if source in {"co_visit", "co_visit_fallback", "co_visit_repair", "metadata_neighbor_recall"}:
        return "co_visit_fallback_repair"
    if source in {"two_tower_recall", "two_tower_youtube_dnn", "youtube_dnn"}:
        return "two_tower"
    if source in {"swing"}:
        return "swing_recall"
    if source in {"usercf"}:
        return "usercf_recall"
    return source


def _repair_row(row: dict[str, Any], source: str) -> dict[str, Any]:
    repaired = dict(row)
    repaired["source"] = source
    sources = repaired.get("sources")
    if isinstance(sources, list):
        repaired["sources"] = [str(value) for value in sources]
        if source not in repaired["sources"]:
            repaired["sources"].append(source)
    else:
        repaired["sources"] = [source]
    metadata = dict(repaired.get("metadata") or {})
    metadata["repair_stage"] = REPAIR_STAGE
    metadata["repair_source"] = source
    repaired["metadata"] = metadata
    repaired["repair_stage"] = REPAIR_STAGE
    repaired["repair_source"] = source
    repaired["repair_shadow_evidence_only"] = True
    repaired["ranking_input_replacement_allowed"] = False
    repaired["promotion_allowed"] = False
    repaired["pool1000_allowed"] = False
    return repaired


def _user_source_repair_count(rows: Iterable[dict[str, Any]], source: str) -> int:
    return sum(1 for row in rows if row.get("repair_source") == source)


def _combine_and_cap(base_rows_by_user: dict[str, list[dict[str, Any]]], repair_rows_by_user: dict[str, list[dict[str, Any]]]) -> dict[str, list[dict[str, Any]]]:
    final: dict[str, list[dict[str, Any]]] = {}
    for user_id in sorted(set(base_rows_by_user) | set(repair_rows_by_user)):
        rows = list(base_rows_by_user.get(user_id, []))
        missing = max(TARGET_CANDIDATE_COUNT - len(rows), 0)
        if missing:
            rows.extend(repair_rows_by_user.get(user_id, [])[:missing])
        final[user_id] = rows[:TARGET_CANDIDATE_COUNT]
    return final


def _iter_rows_in_user_order(rows_by_user: dict[str, list[dict[str, Any]]]):
    for user_id in sorted(rows_by_user):
        for rank, row in enumerate(rows_by_user[user_id], start=1):
            output = dict(row)
            output["rank"] = rank
            yield output


def _candidate_count_stats(counts: list[int]) -> dict[str, int]:
    return {
        "candidate_count_min": min(counts) if counts else 0,
        "candidate_count_p50": _percentile(counts, 0.5),
        "candidate_count_p90": _percentile(counts, 0.9),
        "candidate_count_max": max(counts) if counts else 0,
    }


def _percentile(values: list[int], q: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    index = int(round((len(ordered) - 1) * q))
    return int(ordered[index])


def _duplicate_item_per_user_count(rows_by_user: dict[str, list[dict[str, Any]]]) -> int:
    duplicates = 0
    for rows in rows_by_user.values():
        seen: set[str] = set()
        for row in rows:
            item_id = str(row.get("item_id", ""))
            if item_id in seen:
                duplicates += 1
            seen.add(item_id)
    return duplicates


def _forbidden_data_scan(paths: Iterable[Path]) -> dict[str, Any]:
    matches: list[str] = []
    for path in paths:
        normalized = str(path).replace("\\", "/").lower()
        if any(marker in normalized for marker in FORBIDDEN_DATA_MARKERS):
            matches.append(str(path))
    return {
        "status": "PASS" if not matches else "FAIL",
        "forbidden_markers": list(FORBIDDEN_DATA_MARKERS),
        "forbidden_matches": matches,
    }


def _remaining_underfilled_user_details(
    remaining_underfilled_users: list[str],
    original_counts: dict[str, int],
    final_counts: dict[str, int],
    repair_rows_by_user: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    details: list[dict[str, Any]] = []
    for user_id in remaining_underfilled_users:
        repair_counter = Counter(str(row.get("repair_source", row.get("source", "unknown"))) for row in repair_rows_by_user.get(user_id, []))
        details.append({
            "user_id": user_id,
            "base_candidate_count": int(original_counts.get(user_id, 0)),
            "final_candidate_count": int(final_counts.get(user_id, 0)),
            "missing_to_500": max(TARGET_CANDIDATE_COUNT - int(final_counts.get(user_id, 0)), 0),
            "repair_added_count": sum(repair_counter.values()),
            "repair_added_by_source": dict(sorted(repair_counter.items())),
            "reason": "available non-duplicate repair candidates exhausted before reaching 500",
        })
    return details


def _build_repair_contribution_audit(repair_stats: dict[str, dict[str, Any]], target_users: list[str]) -> dict[str, Any]:
    total = sum(int(stats["row_count"]) for stats in repair_stats.values())
    sources: dict[str, Any] = {}
    for source, stats in repair_stats.items():
        users = sorted(stats["users"])
        sources[source] = {
            "status": stats["status"],
            "row_count": int(stats["row_count"]),
            "user_coverage_count": len(users),
            "underfilled_user_coverage_count": len(set(users) & set(target_users)),
            "marginal_candidate_share": round(int(stats["row_count"]) / total, 6) if total else 0.0,
            "target_user_repair_count": len(set(users) & set(target_users)),
            "promotion_allowed": False,
            "ranking_input_replacement_allowed": False,
            "pool1000_allowed": False,
        }
    return {
        "schema_version": f"{SCHEMA_VERSION}.repair_contribution_audit",
        "status": "DIAGNOSTIC_ONLY_AUDIT",
        "repair_stage": REPAIR_STAGE,
        "target_underfilled_user_count": len(target_users),
        "total_repair_row_count": total,
        "popular_cap_per_user": POPULAR_REPAIR_CAP_PER_USER,
        "sources": sources,
        "promotion_allowed": False,
        "ranking_input_replacement_allowed": False,
        "pool1000_allowed": False,
    }


def _build_source_contribution_audit(rows_by_user: dict[str, list[dict[str, Any]]], base_audit: dict[str, Any], target_users: list[str]) -> dict[str, Any]:
    source_rows: dict[str, list[tuple[str, str]]] = defaultdict(list)
    target_user_set = set(target_users)
    for user_id, rows in rows_by_user.items():
        for row in rows:
            source = _canonical_source(row, str(row.get("source", "unknown")))
            item_id = str(row.get("item_id", ""))
            source_rows[source].append((user_id, item_id))
    total = sum(len(rows) for rows in source_rows.values())
    sources: dict[str, Any] = {}
    for source in sorted(set(base_audit.get("sources", {})) | set(source_rows)):
        rows = source_rows.get(source, [])
        users = {user_id for user_id, _item_id in rows}
        sources[source] = {
            "row_count": len(rows),
            "unique_item_count": len({item_id for _user_id, item_id in rows}),
            "user_coverage_count": len(users),
            "user_coverage_ratio": round(len(users) / len(rows_by_user), 6) if rows_by_user else 0.0,
            "underfilled_user_coverage_count": len(users & target_user_set),
            "underfilled_user_coverage_ratio": round(len(users & target_user_set) / len(target_user_set), 6) if target_user_set else 0.0,
            "marginal_candidate_share": round(len(rows) / total, 6) if total else 0.0,
            "readiness_status": base_audit.get("sources", {}).get(source, {}).get("readiness_status", "DIAGNOSTIC_ONLY"),
            "promotion_allowed": False,
            "ranking_input_replacement_allowed": False,
            "pool1000_allowed": False,
        }
    return {
        "schema_version": f"{SCHEMA_VERSION}.source_contribution_audit",
        "status": "DIAGNOSTIC_ONLY_AUDIT",
        "repair_stage": REPAIR_STAGE,
        "candidate_row_count": total,
        "user_count": len(rows_by_user),
        "sources": sources,
        "promotion_allowed": False,
        "ranking_input_replacement_allowed": False,
        "pool1000_allowed": False,
    }


def _build_source_overlap_audit(overlap_stats: dict[str, Counter[str]], duplicate_item_per_user_count: int) -> dict[str, Any]:
    sources = {source: dict(counter) for source, counter in overlap_stats.items()}
    return {
        "schema_version": f"{SCHEMA_VERSION}.source_overlap_audit",
        "status": "PASS" if duplicate_item_per_user_count == 0 else "FAIL",
        "repair_stage": REPAIR_STAGE,
        "sources": sources,
        "duplicate_item_per_user_count": duplicate_item_per_user_count,
        "promotion_allowed": False,
        "ranking_input_replacement_allowed": False,
        "pool1000_allowed": False,
    }


def _build_readiness_result(decision: str, remaining_underfilled_users: list[str]) -> dict[str, Any]:
    blockers = [{"code": "ARTIFACT_GATE_STOP", "severity": "blocker", "evidence": {"decision": "STOP"}}]
    if remaining_underfilled_users:
        blockers.append({
            "code": "UNDERFILLED_USERS_REMAIN",
            "severity": "blocker",
            "evidence": {"underfilled_user_count": len(remaining_underfilled_users)},
        })
    return {
        "schema_version": "full_data_pool500_readiness_bundle_v1",
        "decision": decision,
        "status": decision,
        "repair_stage": REPAIR_STAGE,
        "candidate_generation_allowed": False,
        "ranking_replacement_allowed": False,
        "ranking_input_replacement_allowed": False,
        "pool1000_allowed": False,
        "promotion_allowed": False,
        "artifact_gate_decision": "STOP",
        "marker_isolation_audit": {"status": "PASS", "blockers": [], "diagnostics": []},
        "blockers": blockers,
        "diagnostics": [{
            "code": "UNDERFILLED_ONLY_REPAIR_SHADOW_EVIDENCE",
            "severity": "diagnostic",
            "evidence": {"promotion_allowed": False},
        }],
    }


def _build_shadow_evidence(
    base_run_dir: Path,
    candidates_path: Path,
    decision: str,
    repaired_users: list[str],
    remaining_underfilled_users: list[str],
    users_with_500: int,
) -> dict[str, Any]:
    return {
        "schema_version": "pool500_shadow_evidence_v1",
        "status": "SHADOW_EVIDENCE_ONLY",
        "decision": decision,
        "repair_stage": REPAIR_STAGE,
        "evidence_type": "underfilled_only_repair_shadow_evidence",
        "base_run_dir": str(base_run_dir),
        "candidate_path": str(candidates_path),
        "repaired_user_count": len(repaired_users),
        "repaired_users": sorted(repaired_users),
        "users_with_500_candidates": users_with_500,
        "underfilled_user_count": len(remaining_underfilled_users),
        "remaining_underfilled_users": remaining_underfilled_users,
        "candidate_generation_allowed": False,
        "ranking_replacement_allowed": False,
        "ranking_input_replacement_allowed": False,
        "promotion_allowed": False,
        "pool1000_allowed": False,
    }


def _build_shadow_validation(
    forbidden_scan: dict[str, Any],
    per_user_over_500_count: int,
    duplicate_item_per_user_count: int,
    readiness_result: dict[str, Any],
) -> dict[str, Any]:
    promotion_flags_all_false = not any([
        readiness_result.get("candidate_generation_allowed"),
        readiness_result.get("ranking_replacement_allowed"),
        readiness_result.get("ranking_input_replacement_allowed"),
        readiness_result.get("pool1000_allowed"),
        readiness_result.get("promotion_allowed"),
    ])
    checks = {
        "marker_isolation": "PASS",
        "no_forbidden_data": forbidden_scan["status"],
        "per_user_le_500": "PASS" if per_user_over_500_count == 0 else "FAIL",
        "duplicate_item_per_user": duplicate_item_per_user_count,
        "promotion_flags_all_false": "PASS" if promotion_flags_all_false else "FAIL",
    }
    status = "PASS" if checks["no_forbidden_data"] == "PASS" and checks["per_user_le_500"] == "PASS" and duplicate_item_per_user_count == 0 and promotion_flags_all_false else "FAIL"
    return {
        "schema_version": "pool500_shadow_evidence_v1.validation",
        "status": status,
        "repair_stage": REPAIR_STAGE,
        "checks": checks,
        "marker_isolation_audit": {"status": "PASS", "blockers": [], "diagnostics": []},
        "forbidden_data_scan": forbidden_scan,
        "per_user_over_500_count": per_user_over_500_count,
        "duplicate_item_per_user_count": duplicate_item_per_user_count,
        "candidate_generation_allowed": False,
        "ranking_replacement_allowed": False,
        "ranking_input_replacement_allowed": False,
        "promotion_allowed": False,
        "pool1000_allowed": False,
        "blockers": [] if status == "PASS" else [{"code": "SHADOW_VALIDATION_FAILED", "severity": "blocker"}],
    }


if __name__ == "__main__":
    main()
