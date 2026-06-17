from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[4]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rs_core.common.io import iter_jsonl, read_json, write_json
from rs_core.common.runtime import enforce_project_venv

SCHEMA_VERSION = "pool500_method_source_overlap_v1"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze overlap between one method source artifact and baseline source artifacts.")
    parser.add_argument("--primary-source-index-manifest", type=Path, required=True)
    parser.add_argument("--baseline-source-index-manifest", type=Path, action="append", default=[])
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--target-per-user", type=int, default=120)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--skip-venv-check", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    report = analyze_method_source_overlap(
        primary_source_index_manifest=args.primary_source_index_manifest,
        baseline_source_index_manifests=args.baseline_source_index_manifest,
        output_dir=args.output_dir,
        target_per_user=args.target_per_user,
        overwrite=args.overwrite,
        enforce_venv=not args.skip_venv_check,
    )
    print(json.dumps({"status": report["status"], "report_path": report["report_path"]}, ensure_ascii=False, indent=2))


def analyze_method_source_overlap(
    *,
    primary_source_index_manifest: Path,
    baseline_source_index_manifests: list[Path],
    output_dir: Path,
    target_per_user: int = 120,
    overwrite: bool = False,
    enforce_venv: bool = True,
) -> dict[str, Any]:
    if enforce_venv:
        enforce_project_venv(ROOT)
    primary_source_index_manifest = _resolve_path(primary_source_index_manifest)
    output_dir = _resolve_path(output_dir)
    if output_dir.exists() and any(output_dir.iterdir()) and not overwrite:
        raise FileExistsError(f"Output directory already exists and is non-empty: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)

    primary_manifest = read_json(primary_source_index_manifest)
    primary_candidates_path = _manifest_candidates_path(primary_manifest, primary_source_index_manifest)
    primary_by_user, primary_item_union = _load_primary_candidates(primary_candidates_path)
    primary_counts = [len(items) for items in primary_by_user.values()]
    primary_user_set = set(primary_by_user)

    baseline_reports = []
    for baseline_manifest_path in baseline_source_index_manifests:
        baseline_path = _resolve_path(baseline_manifest_path)
        baseline_manifest = read_json(baseline_path)
        candidates_path = _manifest_candidates_path(baseline_manifest, baseline_path)
        baseline_reports.append(_overlap_with_baseline(primary_by_user, primary_item_union, primary_user_set, baseline_manifest, candidates_path))

    report_path = output_dir / "source_overlap_report.json"
    report = {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "primary_source": primary_manifest.get("source"),
        "primary_source_index_manifest": str(primary_source_index_manifest),
        "primary_candidates_path": str(primary_candidates_path),
        "primary_user_count": len(primary_by_user),
        "primary_candidate_row_count": sum(primary_counts),
        "primary_unique_item_count": len(primary_item_union),
        "primary_candidate_count_stats": _count_stats(primary_counts),
        "target_per_user": target_per_user,
        "primary_underfilled_user_count": sum(1 for count in primary_counts if count < target_per_user),
        "primary_filled_user_count": sum(1 for count in primary_counts if count >= target_per_user),
        "baseline_overlap": baseline_reports,
        "interpretation_scope": "diagnostic_overlap_only_not_promotion_gate_by_itself",
        "candidate_generation_allowed": bool(primary_manifest.get("candidate_generation_allowed", False)),
        "ranking_input_replacement_allowed": bool(primary_manifest.get("ranking_input_replacement_allowed", False)),
        "pool1000_allowed": bool(primary_manifest.get("pool1000_allowed", False)),
        "report_path": str(report_path),
    }
    write_json(report_path, report)
    return report


def _load_primary_candidates(path: Path) -> tuple[dict[str, set[str]], set[str]]:
    by_user: dict[str, set[str]] = defaultdict(set)
    item_union: set[str] = set()
    for row in iter_jsonl(path):
        user_id = _string_value(row, "user_id")
        item_id = _string_value(row, "item_id", "parent_asin")
        if not user_id or not item_id:
            continue
        by_user[user_id].add(item_id)
        item_union.add(item_id)
    return dict(by_user), item_union


def _overlap_with_baseline(
    primary_by_user: dict[str, set[str]],
    primary_item_union: set[str],
    primary_user_set: set[str],
    baseline_manifest: dict[str, Any],
    candidates_path: Path,
) -> dict[str, Any]:
    source = str(baseline_manifest.get("source") or baseline_manifest.get("canonical_source") or candidates_path.parent.name)
    user_overlap_rows = 0
    user_comparable_rows = 0
    user_comparable_users: set[str] = set()
    baseline_rows = 0
    baseline_user_rows = 0
    baseline_item_union: set[str] = set()
    baseline_users: set[str] = set()
    for row in iter_jsonl(candidates_path):
        item_id = _string_value(row, "item_id", "parent_asin")
        user_id = _string_value(row, "user_id")
        if not item_id:
            continue
        baseline_rows += 1
        baseline_item_union.add(item_id)
        if user_id:
            baseline_user_rows += 1
            baseline_users.add(user_id)
        if user_id in primary_by_user:
            user_comparable_rows += 1
            user_comparable_users.add(user_id)
            if item_id in primary_by_user[user_id]:
                user_overlap_rows += 1
    item_overlap_count = len(primary_item_union & baseline_item_union)
    return {
        "baseline_source": source,
        "baseline_candidates_path": str(candidates_path),
        "baseline_row_count": baseline_rows,
        "baseline_user_row_count": baseline_user_rows,
        "baseline_user_count": len(baseline_users),
        "comparable_user_count": len(primary_user_set & baseline_users),
        "user_comparable_row_count": user_comparable_rows,
        "user_level_overlap_row_count": user_overlap_rows,
        "user_level_overlap_ratio": round(user_overlap_rows / user_comparable_rows, 6) if user_comparable_rows else 0.0,
        "item_union_overlap_count": item_overlap_count,
        "item_union_overlap_ratio_vs_primary": round(item_overlap_count / len(primary_item_union), 6) if primary_item_union else 0.0,
        "item_union_overlap_ratio_vs_baseline": round(item_overlap_count / len(baseline_item_union), 6) if baseline_item_union else 0.0,
        "overlap_scope": "user_level" if user_comparable_rows else "item_union_only",
    }


def _manifest_candidates_path(manifest: dict[str, Any], manifest_path: Path) -> Path:
    for key in ("candidates_path", "candidate_artifact_path"):
        value = manifest.get(key)
        if value:
            return _resolve_path(value)
    outputs = manifest.get("outputs") if isinstance(manifest.get("outputs"), dict) else {}
    for key in ("candidates", "candidate_rows", "candidate_artifact"):
        value = outputs.get(key)
        if value:
            return _resolve_path(value)
    required = manifest.get("required_artifacts") if isinstance(manifest.get("required_artifacts"), dict) else {}
    value = required.get("candidates") or required.get("candidates.jsonl")
    if value:
        return _resolve_path(value)
    return manifest_path.parent / "candidates.jsonl"


def _resolve_path(value: Any) -> Path:
    raw_path = str(value).replace("\\", "/")
    path = Path(raw_path)
    return path if path.is_absolute() else ROOT / path


def _string_value(row: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = row.get(key)
        if value is not None and str(value):
            return str(value)
    return ""


def _count_stats(values: list[int]) -> dict[str, int | float]:
    if not values:
        return {"min": 0, "p50": 0, "p90": 0, "max": 0, "avg": 0.0}
    ordered = sorted(values)
    return {
        "min": ordered[0],
        "p50": _percentile(ordered, 0.5),
        "p90": _percentile(ordered, 0.9),
        "max": ordered[-1],
        "avg": round(sum(ordered) / len(ordered), 6),
    }


def _percentile(ordered: list[int], percentile: float) -> int:
    if not ordered:
        return 0
    index = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * percentile))))
    return ordered[index]


if __name__ == "__main__":
    main()
