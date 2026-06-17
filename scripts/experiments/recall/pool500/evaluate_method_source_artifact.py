from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[4]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rs_core.common.io import iter_jsonl, read_json, write_json
from rs_core.common.runtime import enforce_project_venv

SCHEMA_VERSION = "pool500_method_source_eval_v1"
DEFAULT_CLEAN_MANIFEST = ROOT / "data" / "processed" / "amazon_2023_recall_recent_2y_1m_3m" / "manifest.json"
POSITIVE_FIELDS = ("label_binary", "label", "holdout_hit", "is_hit", "clicked", "purchased")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate a single pool500 method source artifact with eval-only labels.")
    parser.add_argument("--source-index-manifest", type=Path, required=True)
    parser.add_argument("--baseline-source-index-manifest", type=Path, action="append", default=[])
    parser.add_argument("--clean-manifest", type=Path, default=DEFAULT_CLEAN_MANIFEST)
    parser.add_argument("--eligible-user-manifest", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--label-splits", default="valid,test")
    parser.add_argument("--metric-ks", default="20,50,100,500")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--skip-venv-check", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    manifest = evaluate_method_source_artifact(
        source_index_manifest_path=args.source_index_manifest,
        baseline_source_index_manifest_paths=args.baseline_source_index_manifest,
        clean_manifest_path=args.clean_manifest,
        eligible_user_manifest_path=args.eligible_user_manifest,
        output_dir=args.output_dir,
        label_splits=_split_csv(args.label_splits),
        metric_ks=[int(value) for value in _split_csv(args.metric_ks)],
        overwrite=args.overwrite,
        enforce_venv=not args.skip_venv_check,
    )
    print(json.dumps({"status": manifest["status"], "report_path": manifest["report_path"], "metrics_path": manifest["metrics_path"]}, ensure_ascii=False, indent=2))


def evaluate_method_source_artifact(
    *,
    source_index_manifest_path: Path,
    baseline_source_index_manifest_paths: Iterable[Path] = (),
    clean_manifest_path: Path = DEFAULT_CLEAN_MANIFEST,
    eligible_user_manifest_path: Path | None = None,
    output_dir: Path,
    label_splits: Iterable[str] = ("valid", "test"),
    metric_ks: Iterable[int] = (20, 50, 100, 500),
    overwrite: bool = False,
    enforce_venv: bool = True,
) -> dict[str, Any]:
    if enforce_venv:
        enforce_project_venv(ROOT)
    source_index_manifest_path = _resolve_path(source_index_manifest_path)
    clean_manifest_path = _resolve_path(clean_manifest_path)
    output_dir = _resolve_path(output_dir)
    _precheck_output_dir(output_dir, overwrite)
    output_dir.mkdir(parents=True, exist_ok=True)

    source_manifest = read_json(source_index_manifest_path)
    source = str(source_manifest.get("source") or "")
    clean_manifest = read_json(clean_manifest_path)
    labels_by_user, label_paths = _load_eval_only_labels(clean_manifest, label_splits)
    eval_user_ids = sorted(labels_by_user)
    candidate_rows_by_user, candidates_path = _load_candidates_by_user_for_eval(source_manifest, source_index_manifest_path, eval_user_ids)
    baseline_rows_by_user, baseline_manifests = _load_baseline_candidates_by_user(baseline_source_index_manifest_paths, eval_user_ids)
    skipped_user_count = len(candidate_rows_by_user) - len(set(candidate_rows_by_user) & set(labels_by_user))
    missing_candidate_label_user_count = len([user_id for user_id in eval_user_ids if user_id not in candidate_rows_by_user])
    metric_ks = sorted({int(k) for k in metric_ks if int(k) > 0})
    if not metric_ks:
        raise ValueError("metric_ks must contain positive cutoffs")

    user_buckets = _load_user_buckets(eligible_user_manifest_path)
    metrics, segment_metrics = _score(candidate_rows_by_user, labels_by_user, eval_user_ids, user_buckets, metric_ks)
    marginal_metrics = _score_marginal_candidates(candidate_rows_by_user, baseline_rows_by_user, labels_by_user, eval_user_ids, metric_ks)
    source_audit = _source_audit(candidate_rows_by_user, eval_user_ids, source)

    metrics_path = output_dir / "metrics.json"
    segment_metrics_path = output_dir / "segment_metrics.json"
    marginal_metrics_path = output_dir / "marginal_metrics.json"
    source_audit_path = output_dir / "source_audit.json"
    report_path = output_dir / "method_source_eval_report.json"
    write_json(metrics_path, metrics)
    write_json(segment_metrics_path, segment_metrics)
    write_json(marginal_metrics_path, marginal_metrics)
    write_json(source_audit_path, source_audit)
    report = {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source": source,
        "source_index_manifest_path": str(source_index_manifest_path),
        "candidate_artifact_path": str(candidates_path) if candidates_path is not None else None,
        "clean_manifest_path": str(clean_manifest_path),
        "eval_scope": "evaluation_only",
        "label_inputs_role": "evaluation_only_not_candidate_generation_inputs",
        "label_splits": list(label_splits),
        "label_paths": [str(path) for path in label_paths],
        "baseline_source_index_manifest_paths": [str(item["manifest_path"]) for item in baseline_manifests],
        "baseline_candidate_artifact_paths": [str(item["candidates_path"]) if item["candidates_path"] is not None else None for item in baseline_manifests],
        "baseline_inputs_role": "evaluation_only_marginal_comparison_not_candidate_generation_inputs",
        "candidate_user_count": len(candidate_rows_by_user),
        "eval_label_user_count": len(labels_by_user),
        "scored_user_count": len(eval_user_ids),
        "missing_candidate_label_user_count": missing_candidate_label_user_count,
        "skipped_candidate_user_without_eval_label_count": skipped_user_count,
        "metric_ks": metric_ks,
        "metrics_path": str(metrics_path),
        "segment_metrics_path": str(segment_metrics_path),
        "marginal_metrics_path": str(marginal_metrics_path),
        "source_audit_path": str(source_audit_path),
        "report_path": str(report_path),
        "no_oracle_label_injection": True,
        "candidate_generation_allowed": bool(source_manifest.get("candidate_generation_allowed", False)),
        "ranking_input_replacement_allowed": bool(source_manifest.get("ranking_input_replacement_allowed", False)),
        "pool1000_allowed": bool(source_manifest.get("pool1000_allowed", False)),
    }
    write_json(report_path, report)
    return report


def _split_csv(value: str) -> list[str]:
    return [part.strip() for part in str(value).split(",") if part.strip()]


def _resolve_path(value: Any) -> Path:
    raw_path = str(value).replace("\\", "/")
    repo_marker = f"/{ROOT.name}/"
    if repo_marker in raw_path:
        raw_path = raw_path.split(repo_marker, 1)[1]
    path = Path(raw_path)
    return path if path.is_absolute() else ROOT / path


def _precheck_output_dir(output_dir: Path, overwrite: bool) -> None:
    if output_dir.exists() and any(output_dir.iterdir()) and not overwrite:
        raise FileExistsError(f"Output directory already exists and is non-empty: {output_dir}")


def _load_eval_only_labels(clean_manifest: dict[str, Any], label_splits: Iterable[str]) -> tuple[dict[str, set[str]], list[Path]]:
    split_paths = clean_manifest.get("split_paths") if isinstance(clean_manifest.get("split_paths"), dict) else {}
    labels_by_user: dict[str, set[str]] = defaultdict(set)
    label_paths: list[Path] = []
    for split in label_splits:
        raw_path = split_paths.get(split)
        if not raw_path:
            continue
        path = _resolve_path(raw_path)
        label_paths.append(path)
        for row in iter_jsonl(path):
            if not _is_positive(row):
                continue
            user_id = _string_value(row, "user_id", "user")
            item_id = _string_value(row, "parent_asin", "item_id", "item")
            if user_id and item_id:
                labels_by_user[user_id].add(item_id)
    return dict(labels_by_user), label_paths


def _load_candidates_by_user_for_eval(manifest: dict[str, Any], manifest_path: Path, eval_user_ids: list[str]) -> tuple[dict[str, list[dict[str, Any]]], Path | None]:
    if _is_category_index_only_manifest(manifest):
        from rs_lab.experiments.recall.pool500.methods.category import expand_category_candidates_for_users

        return _dedupe_candidate_rows(expand_category_candidates_for_users(source_index_manifest_path=manifest_path, user_ids=eval_user_ids)), None
    candidates_path = _manifest_candidates_path(manifest, manifest_path)
    return _load_candidates_by_user(candidates_path), candidates_path


def _load_candidates_by_user(candidates_path: Path) -> dict[str, list[dict[str, Any]]]:
    rows_by_user: dict[str, list[dict[str, Any]]] = defaultdict(list)
    seen_pairs: set[tuple[str, str]] = set()
    duplicates = 0
    for row in iter_jsonl(candidates_path):
        user_id = _string_value(row, "user_id")
        item_id = _string_value(row, "item_id", "parent_asin")
        if not user_id or not item_id:
            continue
        pair = (user_id, item_id)
        if pair in seen_pairs:
            duplicates += 1
            continue
        seen_pairs.add(pair)
        rows_by_user[user_id].append(row)
    for rows in rows_by_user.values():
        rows.sort(key=lambda row: (_int_value(row.get("rank"), 10**9), _string_value(row, "item_id", "parent_asin")))
    if duplicates:
        raise ValueError(f"candidate artifact contains duplicate user_id+item_id rows: {duplicates}")
    return dict(rows_by_user)


def _dedupe_candidate_rows(rows: Iterable[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    rows_by_user: dict[str, list[dict[str, Any]]] = defaultdict(list)
    seen_pairs: set[tuple[str, str]] = set()
    for row in rows:
        user_id = _string_value(row, "user_id")
        item_id = _string_value(row, "item_id", "parent_asin")
        if not user_id or not item_id:
            continue
        pair = (user_id, item_id)
        if pair in seen_pairs:
            continue
        seen_pairs.add(pair)
        rows_by_user[user_id].append(dict(row))
    for user_rows in rows_by_user.values():
        user_rows.sort(key=lambda row: (_int_value(row.get("rank"), 10**9), _string_value(row, "item_id", "parent_asin")))
    return dict(rows_by_user)


def _load_baseline_candidates_by_user(baseline_manifest_paths: Iterable[Path], eval_user_ids: list[str]) -> tuple[dict[str, set[str]], list[dict[str, Path | None]]]:
    baseline_items_by_user: dict[str, set[str]] = defaultdict(set)
    manifests: list[dict[str, Path | None]] = []
    for manifest_path in baseline_manifest_paths:
        resolved_manifest_path = _resolve_path(manifest_path)
        manifest = read_json(resolved_manifest_path)
        rows_by_user, candidates_path = _load_candidates_by_user_for_eval(manifest, resolved_manifest_path, eval_user_ids)
        manifests.append({"manifest_path": resolved_manifest_path, "candidates_path": candidates_path})
        for user_id, rows in rows_by_user.items():
            for row in rows:
                item_id = _string_value(row, "item_id", "parent_asin")
                if user_id and item_id:
                    baseline_items_by_user[user_id].add(item_id)
    return dict(baseline_items_by_user), manifests


def _is_category_index_only_manifest(manifest: dict[str, Any]) -> bool:
    return str(manifest.get("source") or "") == "category" and str(manifest.get("candidate_materialization") or "") == "none"


def _manifest_candidates_path(manifest: dict[str, Any], manifest_path: Path) -> Path:
    if _is_category_index_only_manifest(manifest):
        raise ValueError("category index-only manifest has no materialized candidates; use on-demand expansion")
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


def _load_user_buckets(path: Path | None) -> dict[str, str]:
    if path is None:
        return {}
    path = _resolve_path(path)
    if not path.is_file():
        return {}
    manifest = read_json(path)
    buckets = manifest.get("eligible_user_buckets") if isinstance(manifest.get("eligible_user_buckets"), dict) else {}
    result: dict[str, str] = {}
    for bucket, user_ids in buckets.items():
        if not isinstance(user_ids, list):
            continue
        for user_id in user_ids:
            result[str(user_id)] = str(bucket)
    if result:
        return result

    profile_path = manifest.get("user_quality_profile_path")
    if not profile_path:
        return {}
    eligible_ids = {str(user_id) for user_id in manifest.get("eligible_user_ids", []) if user_id}
    for row in iter_jsonl(_resolve_path(profile_path)):
        user_id = _string_value(row, "user_id")
        if not user_id or (eligible_ids and user_id not in eligible_ids):
            continue
        bucket = _string_value(row, "quality_bucket_v2", "quality_bucket")
        if bucket:
            result[user_id] = bucket
    return result


def _score(
    candidate_rows_by_user: dict[str, list[dict[str, Any]]],
    labels_by_user: dict[str, set[str]],
    eval_user_ids: list[str],
    user_buckets: dict[str, str],
    metric_ks: list[int],
) -> tuple[dict[str, Any], dict[str, Any]]:
    per_user_scores: dict[str, dict[str, float]] = {}
    for user_id in eval_user_ids:
        labels = labels_by_user[user_id]
        rows = candidate_rows_by_user.get(user_id, [])
        per_user_scores[user_id] = {}
        for k in metric_ks:
            top_items = {
                _string_value(row, "item_id", "parent_asin")
                for row in rows
                if _int_value(row.get("rank"), 10**9) <= k
            }
            hit_count = len(top_items & labels)
            per_user_scores[user_id][f"Recall@{k}"] = hit_count / len(labels) if labels else 0.0
            per_user_scores[user_id][f"HitRate@{k}"] = 1.0 if hit_count else 0.0
    metrics = _aggregate_scores(eval_user_ids, per_user_scores, metric_ks)
    bucket_to_users: dict[str, list[str]] = defaultdict(list)
    for user_id in eval_user_ids:
        bucket_to_users[user_buckets.get(user_id, "unknown")].append(user_id)
    segment_metrics = {bucket: _aggregate_scores(users, per_user_scores, metric_ks, include_user_count=True) for bucket, users in sorted(bucket_to_users.items())}
    return metrics, segment_metrics


def _aggregate_scores(user_ids: list[str], per_user_scores: dict[str, dict[str, float]], metric_ks: list[int], *, include_user_count: bool = False) -> dict[str, Any]:
    payload: dict[str, Any] = {"user_count": len(user_ids)} if include_user_count else {}
    for k in metric_ks:
        for metric_name in (f"Recall@{k}", f"HitRate@{k}"):
            payload[metric_name] = round(sum(per_user_scores[user_id][metric_name] for user_id in user_ids) / len(user_ids), 6) if user_ids else 0.0
    return payload


def _score_marginal_candidates(
    candidate_rows_by_user: dict[str, list[dict[str, Any]]],
    baseline_items_by_user: dict[str, set[str]],
    labels_by_user: dict[str, set[str]],
    eval_user_ids: list[str],
    metric_ks: list[int],
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": f"{SCHEMA_VERSION}.marginal_metrics",
        "comparison_scope": "source_candidates_minus_baseline_candidates",
        "baseline_inputs_role": "evaluation_only_marginal_comparison_not_candidate_generation_inputs",
        "baseline_user_count": len(baseline_items_by_user),
        "scored_user_count": len(eval_user_ids),
    }
    for k in metric_ks:
        marginal_candidate_count = 0
        marginal_positive_hit_count = 0
        marginal_hit_users = 0
        comparable_users = 0
        for user_id in eval_user_ids:
            labels = labels_by_user[user_id]
            baseline_items = baseline_items_by_user.get(user_id, set())
            if baseline_items:
                comparable_users += 1
            top_items = {
                _string_value(row, "item_id", "parent_asin")
                for row in candidate_rows_by_user.get(user_id, [])
                if _int_value(row.get("rank"), 10**9) <= k
            }
            marginal_items = top_items - baseline_items
            hit_count = len(marginal_items & labels)
            marginal_candidate_count += len(marginal_items)
            marginal_positive_hit_count += hit_count
            if hit_count:
                marginal_hit_users += 1
        payload[f"MarginalCandidateCount@{k}"] = marginal_candidate_count
        payload[f"MarginalPositiveHitCount@{k}"] = marginal_positive_hit_count
        payload[f"MarginalHitRate@{k}"] = round(marginal_hit_users / len(eval_user_ids), 6) if eval_user_ids else 0.0
        payload[f"MarginalHitUserCount@{k}"] = marginal_hit_users
        payload[f"BaselineComparableUserCount@{k}"] = comparable_users
    return payload


def _source_audit(candidate_rows_by_user: dict[str, list[dict[str, Any]]], eval_user_ids: list[str], source: str) -> dict[str, Any]:
    counts = [len(candidate_rows_by_user.get(user_id, [])) for user_id in eval_user_ids]
    source_counts: Counter[str] = Counter()
    for rows in candidate_rows_by_user.values():
        for row in rows:
            source_counts[_string_value(row, "source", "primary_source") or source] += 1
    return {
        "schema_version": f"{SCHEMA_VERSION}.source_audit",
        "source": source,
        "candidate_user_count": len(candidate_rows_by_user),
        "scored_user_count": len(eval_user_ids),
        "candidate_row_count": sum(len(rows) for rows in candidate_rows_by_user.values()),
        "scored_candidate_row_count": sum(counts),
        "candidate_count_min": min(counts) if counts else 0,
        "candidate_count_p50": _percentile(counts, 0.5),
        "candidate_count_p90": _percentile(counts, 0.9),
        "candidate_count_max": max(counts) if counts else 0,
        "source_contribution_counts": dict(sorted(source_counts.items())),
        "no_oracle_label_injection": True,
    }


def _percentile(values: list[int], percentile: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * percentile))))
    return ordered[index]


def _string_value(row: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = row.get(key)
        if value is not None and str(value):
            return str(value)
    return ""


def _int_value(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _is_positive(row: dict[str, Any]) -> bool:
    for field in POSITIVE_FIELDS:
        if field not in row:
            continue
        value = row[field]
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return value > 0
        return str(value).strip().lower() in {"1", "true", "yes", "positive", "purchased", "clicked"}
    return True


if __name__ == "__main__":
    main()
