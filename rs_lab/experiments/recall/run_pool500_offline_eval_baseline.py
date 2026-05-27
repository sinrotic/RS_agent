from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any, Callable, Iterable

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rs_core.common.io import iter_jsonl, read_json, write_json, write_jsonl
from rs_core.common.runtime import enforce_project_venv
from rs_core.workflow.full_data_pool500_route_gate import canonical_user_set_hash
from rs_lab.experiments.recall.run_full_data_pool500_recall_only import (
    DEFAULT_CLEAN_MANIFEST,
    DEFAULT_LIGHTWEIGHT_VIEWS_MANIFEST,
    run_full_data_pool500_recall_only,
)

SCHEMA_VERSION = "pool500_offline_eval_baseline_current_v1"
DERIVED_TARGET_SCHEMA_VERSION = "pool500_aligned_eval_user_selection_v1"
DEFAULT_EVAL_MANIFEST = ROOT / "outputs" / "eval" / "pool500_offline_eval_users_10k" / "manifest.json"
DEFAULT_OUTPUT_DIR = ROOT / "outputs" / "eval" / "pool500_offline_eval_baseline_current"
POSITIVE_FIELDS = ("label_binary", "label", "holdout_hit", "is_hit", "clicked", "purchased")
SEGMENTS = ("hot", "warm", "cold-ish")
METRIC_KS = (20, 50, 100, 500)
CandidateRunner = Callable[..., dict[str, Any]]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the current pool500 recall route on a fixed offline eval user manifest and score Recall/HitRate.")
    parser.add_argument("--eval-manifest", default=str(DEFAULT_EVAL_MANIFEST))
    parser.add_argument("--eval-users", default="", help="Optional users.jsonl beside the fixed eval manifest; defaults to manifest_dir/users.jsonl.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--clean-manifest", default="", help="Override clean manifest; defaults to eval manifest source_manifest_paths.clean_manifest_path.")
    parser.add_argument("--lightweight-views-manifest", default=str(DEFAULT_LIGHTWEIGHT_VIEWS_MANIFEST))
    parser.add_argument("--limit-users", type=int, default=0, help="Use the first N fixed eval users for dry-runs; 0 means all fixed eval users.")
    parser.add_argument("--source-index-manifest", default="", help="Run raw two_tower eval with this source_index_manifest.json.")
    parser.add_argument("--with-two-tower-source-manifest", default="", help="Run ablation using this two_tower source_index_manifest.json for the with-two-tower arm.")
    parser.add_argument("--without-two-tower", action="store_true", help="Run the ablation arm with two_tower disabled.")
    parser.add_argument("--metric-ks", default=",".join(str(k) for k in METRIC_KS), help="Comma-separated metric cutoffs, e.g. 20,50,100,500.")
    parser.add_argument("--output-manifest", default="", help="Output path for raw two_tower eval manifest.")
    parser.add_argument("--output-ablation", default="", help="Output path for with/without two_tower ablation manifest.")
    parser.add_argument("--enable-semantic", action="store_true")
    parser.add_argument("--semantic-max-rows", type=int, default=200000)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--skip-venv-check", action="store_true")
    return parser.parse_args()


def run_pool500_offline_eval_baseline(
    *,
    eval_manifest_path: Path = DEFAULT_EVAL_MANIFEST,
    eval_users_path: Path | None = None,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    clean_manifest_path: Path | None = None,
    lightweight_views_manifest_path: Path = DEFAULT_LIGHTWEIGHT_VIEWS_MANIFEST,
    limit_users: int = 0,
    enable_semantic: bool = False,
    semantic_max_rows: int = 200000,
    overwrite: bool = False,
    enforce_venv: bool = True,
    metric_ks: Iterable[int] = METRIC_KS,
    source_manifest_paths: dict[str, Path] | None = None,
    candidate_runner: CandidateRunner = run_full_data_pool500_recall_only,
) -> dict[str, Any]:
    if enforce_venv:
        enforce_project_venv(ROOT)
    if limit_users < 0:
        raise ValueError("--limit-users must be non-negative")
    metric_ks = _parse_metric_ks(metric_ks)

    eval_manifest_path = eval_manifest_path.resolve()
    output_dir = output_dir.resolve()
    _precheck_output_dir(output_dir, overwrite)
    eval_manifest = _load_offline_eval_manifest(eval_manifest_path)
    users = _load_eval_users(eval_manifest, eval_manifest_path, eval_users_path)
    selected_users = users[:limit_users] if limit_users else users
    if not selected_users:
        raise ValueError("fixed eval manifest selected no users")
    eval_user_ids = [str(user["user_id"]) for user in selected_users]
    eval_user_set_hash = canonical_user_set_hash(eval_user_ids)
    if not limit_users and eval_user_set_hash != eval_manifest.get("user_set_hash"):
        raise ValueError("eval users hash does not match eval manifest user_set_hash")

    labels_by_user = _load_eval_labels(eval_manifest, eval_user_ids)
    user_segments = _user_segments(selected_users)
    output_dir.mkdir(parents=True, exist_ok=True)
    target_manifest_path = output_dir / "candidate_generation_target_users_manifest.json"
    write_json(target_manifest_path, _candidate_generation_target_manifest(eval_manifest, eval_manifest_path, eval_user_ids, eval_user_set_hash))

    base_clean_manifest_path = clean_manifest_path or _clean_manifest_from_eval(eval_manifest)
    runner_kwargs = {
        "clean_manifest_path": base_clean_manifest_path,
        "lightweight_views_manifest_path": lightweight_views_manifest_path,
        "output_dir": output_dir,
        "limit_users": len(eval_user_ids),
        "full_run": False,
        "enable_semantic": enable_semantic,
        "semantic_max_rows": semantic_max_rows,
        "overwrite": True,
        "enforce_venv": False,
        "source_manifest_paths": source_manifest_paths,
    }
    if candidate_runner is run_full_data_pool500_recall_only:
        runner_kwargs["clean_manifest_path"] = _write_eval_user_sequence_clean_manifest(base_clean_manifest_path, output_dir, eval_user_ids, target_manifest_path)
    else:
        runner_kwargs["target_user_manifest_path"] = target_manifest_path

    generation_started = perf_counter()
    generation_manifest = candidate_runner(**runner_kwargs)
    generation_elapsed_seconds = round(perf_counter() - generation_started, 6)
    candidate_path = output_dir / "pool500_candidates.jsonl"
    if not candidate_path.is_file():
        raise FileNotFoundError(f"candidate runner did not write {candidate_path}")

    metrics, segment_metrics, source_audit = _evaluate_candidates(candidate_path, eval_user_ids, labels_by_user, user_segments, metric_ks=metric_ks)
    metrics_path = output_dir / "metrics.json"
    segment_metrics_path = output_dir / "segment_metrics.json"
    source_audit_path = output_dir / "source_audit.json"
    write_json(metrics_path, metrics)
    write_json(segment_metrics_path, segment_metrics)
    write_json(source_audit_path, source_audit)

    baseline_manifest = {
        "schema_version": SCHEMA_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "eval_manifest_path": str(eval_manifest_path),
        "eval_users_path": str((eval_users_path or eval_manifest_path.parent / "users.jsonl").resolve()),
        "eval_manifest_schema_version": eval_manifest.get("schema_version"),
        "eval_manifest_user_set_hash": eval_manifest.get("user_set_hash"),
        "eval_user_set_hash": eval_user_set_hash,
        "total_user_count": len(eval_user_ids),
        "eval_manifest_total_user_count": eval_manifest.get("total_user_count"),
        "segment_counts": dict(sorted(Counter(user_segments.values()).items())),
        "eval_manifest_segment_counts": eval_manifest.get("segment_counts"),
        "split_contract": eval_manifest.get("split_contract"),
        "leakage_policy": eval_manifest.get("leakage_policy"),
        "candidate_artifact_path": str(candidate_path),
        "metrics_path": str(metrics_path),
        "segment_metrics_path": str(segment_metrics_path),
        "source_audit_path": str(source_audit_path),
        "metric_ks": metric_ks,
        "candidate_generation_elapsed_seconds": generation_elapsed_seconds,
        "candidate_generation_manifest_path": str(output_dir / "manifest.json"),
        "candidate_generation_target_manifest_path": str(target_manifest_path),
        "recall_route_profile": _recall_route_profile(generation_manifest, enable_semantic, semantic_max_rows),
        "no_oracle_label_injection": True,
    }
    baseline_manifest_path = output_dir / "baseline_manifest.json"
    write_json(baseline_manifest_path, baseline_manifest)
    return baseline_manifest


def run_raw_two_tower_eval(
    *,
    source_index_manifest_path: Path,
    output_manifest_path: Path,
    eval_manifest_path: Path = DEFAULT_EVAL_MANIFEST,
    eval_users_path: Path | None = None,
    output_dir: Path | None = None,
    clean_manifest_path: Path | None = None,
    lightweight_views_manifest_path: Path = DEFAULT_LIGHTWEIGHT_VIEWS_MANIFEST,
    limit_users: int = 0,
    enable_semantic: bool = False,
    semantic_max_rows: int = 200000,
    overwrite: bool = False,
    enforce_venv: bool = True,
    metric_ks: Iterable[int] = METRIC_KS,
    candidate_runner: CandidateRunner = run_full_data_pool500_recall_only,
) -> dict[str, Any]:
    metric_ks = _parse_metric_ks(metric_ks)
    source_index_manifest_path = source_index_manifest_path.resolve()
    _validate_source_index_manifest_path(source_index_manifest_path)
    output_manifest_path = output_manifest_path.resolve()
    generation_dir = (output_dir or output_manifest_path.parent / "raw_two_tower_generation").resolve()
    baseline_manifest = run_pool500_offline_eval_baseline(
        eval_manifest_path=eval_manifest_path,
        eval_users_path=eval_users_path,
        output_dir=generation_dir,
        clean_manifest_path=clean_manifest_path,
        lightweight_views_manifest_path=lightweight_views_manifest_path,
        limit_users=limit_users,
        enable_semantic=enable_semantic,
        semantic_max_rows=semantic_max_rows,
        overwrite=overwrite,
        enforce_venv=enforce_venv,
        metric_ks=metric_ks,
        source_manifest_paths={"two_tower": source_index_manifest_path},
        candidate_runner=candidate_runner,
    )
    eval_manifest = _load_offline_eval_manifest(eval_manifest_path.resolve())
    users = _load_eval_users(eval_manifest, eval_manifest_path.resolve(), eval_users_path)
    selected_users = users[:limit_users] if limit_users else users
    eval_user_ids = [str(user["user_id"]) for user in selected_users]
    labels_by_user = _load_eval_labels(eval_manifest, eval_user_ids)
    stats = _positive_hit_stats(Path(baseline_manifest["candidate_artifact_path"]), eval_user_ids, labels_by_user, metric_ks=metric_ks, source_filter="two_tower")
    candidate_count = int(read_json(Path(baseline_manifest["source_audit_path"])).get("candidate_row_count") or 0)
    elapsed = float(baseline_manifest.get("candidate_generation_elapsed_seconds") or 0.0)
    manifest = {
        "schema_version": "raw_two_tower_eval_v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_index_manifest": str(source_index_manifest_path),
        "eval_scope": "evaluation_only",
        "metric_ks": metric_ks,
        "metrics": {f"hit_at_{k}": stats["hit_rates"][k] for k in metric_ks},
        "raw_two_tower_unique_positive_hits": stats["unique_positive_hit_count"],
        "candidate_generation_qps": round(candidate_count / elapsed, 6) if elapsed > 0 else 0.0,
        "underfilled_user_rate": _underfilled_user_rate(Path(baseline_manifest["source_audit_path"])),
        "single_generation_elapsed_seconds": elapsed,
        "baseline_manifest_path": str(generation_dir / "baseline_manifest.json"),
        "no_oracle_label_injection": True,
    }
    output_manifest_path.parent.mkdir(parents=True, exist_ok=True)
    write_json(output_manifest_path, manifest)
    return manifest


def run_two_tower_ablation(
    *,
    with_two_tower_source_manifest_path: Path,
    output_ablation_path: Path,
    eval_manifest_path: Path = DEFAULT_EVAL_MANIFEST,
    eval_users_path: Path | None = None,
    output_dir: Path | None = None,
    clean_manifest_path: Path | None = None,
    lightweight_views_manifest_path: Path = DEFAULT_LIGHTWEIGHT_VIEWS_MANIFEST,
    limit_users: int = 0,
    enable_semantic: bool = False,
    semantic_max_rows: int = 200000,
    overwrite: bool = False,
    enforce_venv: bool = True,
    metric_ks: Iterable[int] = METRIC_KS,
    candidate_runner: CandidateRunner = run_full_data_pool500_recall_only,
) -> dict[str, Any]:
    metric_ks = _parse_metric_ks(metric_ks)
    with_two_tower_source_manifest_path = with_two_tower_source_manifest_path.resolve()
    _validate_source_index_manifest_path(with_two_tower_source_manifest_path)
    output_ablation_path = output_ablation_path.resolve()
    root_dir = (output_dir or output_ablation_path.parent / "two_tower_ablation_generation").resolve()
    with_manifest = run_pool500_offline_eval_baseline(
        eval_manifest_path=eval_manifest_path,
        eval_users_path=eval_users_path,
        output_dir=root_dir / "with_two_tower",
        clean_manifest_path=clean_manifest_path,
        lightweight_views_manifest_path=lightweight_views_manifest_path,
        limit_users=limit_users,
        enable_semantic=enable_semantic,
        semantic_max_rows=semantic_max_rows,
        overwrite=overwrite,
        enforce_venv=enforce_venv,
        metric_ks=metric_ks,
        source_manifest_paths={"two_tower": with_two_tower_source_manifest_path},
        candidate_runner=candidate_runner,
    )
    without_manifest = run_pool500_offline_eval_baseline(
        eval_manifest_path=eval_manifest_path,
        eval_users_path=eval_users_path,
        output_dir=root_dir / "without_two_tower",
        clean_manifest_path=clean_manifest_path,
        lightweight_views_manifest_path=lightweight_views_manifest_path,
        limit_users=limit_users,
        enable_semantic=enable_semantic,
        semantic_max_rows=semantic_max_rows,
        overwrite=overwrite,
        enforce_venv=False,
        metric_ks=metric_ks,
        source_manifest_paths={"two_tower": output_ablation_path.parent / "__disabled_two_tower_source_manifest.json"},
        candidate_runner=candidate_runner,
    )
    eval_manifest = _load_offline_eval_manifest(eval_manifest_path.resolve())
    users = _load_eval_users(eval_manifest, eval_manifest_path.resolve(), eval_users_path)
    selected_users = users[:limit_users] if limit_users else users
    eval_user_ids = [str(user["user_id"]) for user in selected_users]
    labels_by_user = _load_eval_labels(eval_manifest, eval_user_ids)
    with_candidates = Path(with_manifest["candidate_artifact_path"])
    without_candidates = Path(without_manifest["candidate_artifact_path"])
    with_positive_pairs = _positive_hit_pairs(with_candidates, labels_by_user, max(metric_ks))
    without_positive_pairs = _positive_hit_pairs(without_candidates, labels_by_user, max(metric_ks))
    raw_two_tower_stats = _positive_hit_stats(with_candidates, eval_user_ids, labels_by_user, metric_ks=metric_ks, source_filter="two_tower")
    with_metrics = _hit_at_payload(read_json(Path(with_manifest["metrics_path"])), metric_ks)
    without_metrics = _hit_at_payload(read_json(Path(without_manifest["metrics_path"])), metric_ks)
    marginal_unique_positive_hits = len(with_positive_pairs - without_positive_pairs)
    raw_two_tower_unique_positive_hits = raw_two_tower_stats["unique_positive_hit_count"]
    hit_at_500_ok = with_metrics.get("hit_at_500", 0.0) >= without_metrics.get("hit_at_500", 0.0)
    include = hit_at_500_ok and raw_two_tower_unique_positive_hits > 0 and marginal_unique_positive_hits > 0
    manifest = {
        "schema_version": "pool500_two_tower_ablation_v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "metric_ks": metric_ks,
        "without_two_tower": without_metrics,
        "with_two_tower": with_metrics,
        "raw_two_tower_unique_positive_hits": raw_two_tower_unique_positive_hits,
        "marginal_unique_positive_hits": marginal_unique_positive_hits,
        "overlap_positive_hits": len(with_positive_pairs & without_positive_pairs),
        "candidate_generation_qps": {
            "with_two_tower": _candidate_generation_qps(with_manifest),
            "without_two_tower": _candidate_generation_qps(without_manifest),
        },
        "underfilled_user_rate": {
            "with_two_tower": _underfilled_user_rate(Path(with_manifest["source_audit_path"])),
            "without_two_tower": _underfilled_user_rate(Path(without_manifest["source_audit_path"])),
        },
        "pool_budget_decision": "include" if include else "exclude",
        "decision_reason": "two_tower improves or matches Hit@500 with positive raw and marginal hits" if include else "two_tower failed Hit@500 or unique positive hit gate",
        "with_two_tower_baseline_manifest_path": str(root_dir / "with_two_tower" / "baseline_manifest.json"),
        "without_two_tower_baseline_manifest_path": str(root_dir / "without_two_tower" / "baseline_manifest.json"),
        "no_oracle_label_injection": True,
    }
    output_ablation_path.parent.mkdir(parents=True, exist_ok=True)
    write_json(output_ablation_path, manifest)
    return manifest


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


def _validate_source_index_manifest_path(path: Path) -> None:
    if not path.is_file():
        raise FileNotFoundError(f"two_tower source_index_manifest does not exist: {path}")
    manifest = read_json(path)
    if manifest.get("source") != "two_tower":
        raise ValueError(f"source_index_manifest must declare source=two_tower: {path}")


def _positive_hit_stats(
    candidate_path: Path,
    eval_user_ids: list[str],
    labels_by_user: dict[str, set[str]],
    *,
    metric_ks: Iterable[int],
    source_filter: str | None = None,
) -> dict[str, Any]:
    metric_ks = _parse_metric_ks(metric_ks)
    hit_users: dict[int, set[str]] = {k: set() for k in metric_ks}
    positive_pairs: set[tuple[str, str]] = set()
    for row in iter_jsonl(candidate_path):
        user_id = _string_value(row, "user_id")
        item_id = _string_value(row, "item_id", "parent_asin")
        if user_id not in labels_by_user or item_id not in labels_by_user[user_id]:
            continue
        primary_source = _primary_source(row)
        sources = _sources(row, primary_source)
        if source_filter and source_filter not in sources:
            continue
        rank = _int_value(row.get("rank"), max(metric_ks))
        if rank <= max(metric_ks):
            positive_pairs.add((user_id, item_id))
        for k in metric_ks:
            if rank <= k:
                hit_users[k].add(user_id)
    denominator = len(eval_user_ids)
    return {
        "hit_rates": {k: round(len(hit_users[k]) / denominator, 6) if denominator else 0.0 for k in metric_ks},
        "unique_positive_hit_count": len(positive_pairs),
        "positive_pairs": positive_pairs,
    }


def _positive_hit_pairs(candidate_path: Path, labels_by_user: dict[str, set[str]], max_k: int) -> set[tuple[str, str]]:
    pairs: set[tuple[str, str]] = set()
    for row in iter_jsonl(candidate_path):
        user_id = _string_value(row, "user_id")
        item_id = _string_value(row, "item_id", "parent_asin")
        if _int_value(row.get("rank"), max_k) <= max_k and user_id in labels_by_user and item_id in labels_by_user[user_id]:
            pairs.add((user_id, item_id))
    return pairs


def _hit_at_payload(metrics: dict[str, Any], metric_ks: Iterable[int]) -> dict[str, float]:
    return {f"hit_at_{k}": float(metrics.get(f"HitRate@{k}", 0.0)) for k in metric_ks}


def _candidate_generation_qps(manifest: dict[str, Any]) -> float:
    source_audit = read_json(Path(manifest["source_audit_path"]))
    elapsed = float(manifest.get("candidate_generation_elapsed_seconds") or 0.0)
    row_count = int(source_audit.get("candidate_row_count") or 0)
    return round(row_count / elapsed, 6) if elapsed > 0 else 0.0


def _underfilled_user_rate(source_audit_path: Path) -> float:
    source_audit = read_json(source_audit_path)
    user_count = int(source_audit.get("user_count") or 0)
    underfilled_count = int(source_audit.get("underfilled_user_count") or 0)
    return round(underfilled_count / user_count, 6) if user_count else 0.0


def _load_offline_eval_manifest(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"fixed eval manifest does not exist: {path}")
    manifest = read_json(path)
    if manifest.get("schema_version") != "pool500_offline_eval_users_v1":
        raise ValueError(f"expected pool500_offline_eval_users_v1 manifest: {path}")
    if manifest.get("status") != "PASS":
        raise ValueError(f"fixed eval manifest must have status=PASS: {path}")
    leakage_policy = manifest.get("leakage_policy") if isinstance(manifest.get("leakage_policy"), dict) else {}
    if leakage_policy.get("no_oracle_candidate_injection") is not True:
        raise ValueError("fixed eval manifest must declare no_oracle_candidate_injection=true")
    if leakage_policy.get("no_label_in_candidate_generation") is not True:
        raise ValueError("fixed eval manifest must declare no_label_in_candidate_generation=true")
    return manifest


def _load_eval_users(eval_manifest: dict[str, Any], eval_manifest_path: Path, eval_users_path: Path | None) -> list[dict[str, Any]]:
    users_path = (eval_users_path or eval_manifest_path.parent / "users.jsonl").resolve()
    if users_path.is_file():
        users = list(iter_jsonl(users_path))
    else:
        raw_users = eval_manifest.get("users")
        if not isinstance(raw_users, list):
            raise FileNotFoundError(f"fixed eval users jsonl does not exist and manifest.users is unavailable: {users_path}")
        users = [dict(user) for user in raw_users]
    if len(users) != int(eval_manifest.get("total_user_count") or 0):
        raise ValueError("users.jsonl count does not match eval manifest total_user_count")
    user_ids = [str(user.get("user_id") or "") for user in users]
    if any(not user_id for user_id in user_ids):
        raise ValueError("fixed eval users contain missing user_id")
    if len(set(user_ids)) != len(user_ids):
        raise ValueError("fixed eval users contain duplicate user_id")
    if canonical_user_set_hash(user_ids) != eval_manifest.get("user_set_hash"):
        raise ValueError("users.jsonl user_set_hash does not match eval manifest")
    return users


def _load_eval_labels(eval_manifest: dict[str, Any], eval_user_ids: list[str]) -> dict[str, set[str]]:
    source_data_paths = eval_manifest.get("source_data_paths") if isinstance(eval_manifest.get("source_data_paths"), dict) else {}
    label_paths = [Path(str(path)) for path in source_data_paths.get("label_paths") or []]
    if not label_paths:
        raise ValueError("fixed eval manifest source_data_paths.label_paths is required for full-label Recall/HitRate metrics")
    eval_user_set = set(eval_user_ids)
    labels_by_user: dict[str, set[str]] = {user_id: set() for user_id in eval_user_ids}
    for label_path in label_paths:
        if not label_path.is_file():
            raise FileNotFoundError(f"eval label path does not exist: {label_path}")
        for row in iter_jsonl(label_path):
            user_id = _string_value(row, "user_id", "user")
            if user_id not in eval_user_set or not _is_positive(row):
                continue
            item_id = _string_value(row, "parent_asin", "item_id", "item")
            if item_id:
                labels_by_user[user_id].add(item_id)
    missing = [user_id for user_id in eval_user_ids if not labels_by_user[user_id]]
    if missing:
        raise ValueError(f"fixed eval users missing labels: {missing[:10]} (count={len(missing)})")
    return labels_by_user


def _evaluate_candidates(
    candidate_path: Path,
    eval_user_ids: list[str],
    labels_by_user: dict[str, set[str]],
    user_segments: dict[str, str],
    *,
    metric_ks: Iterable[int] = METRIC_KS,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    metric_ks = _parse_metric_ks(metric_ks)
    eval_user_set = set(eval_user_ids)
    seen_users: set[str] = set()
    completed_users: set[str] = set()
    per_user_counts: Counter[str] = Counter()
    primary_source_counts: Counter[str] = Counter()
    all_source_counts: Counter[str] = Counter()
    pairwise_source_overlap: dict[str, Counter[str]] = defaultdict(Counter)
    user_scores: dict[str, dict[str, float]] = {}
    current_user: str | None = None
    current_seen_items: set[str] = set()
    current_hit_items = {k: set() for k in metric_ks}

    def finalize_user(user_id: str | None) -> None:
        if user_id is None:
            return
        labels = labels_by_user[user_id]
        user_scores[user_id] = {}
        for k in metric_ks:
            hit_count = len(current_hit_items[k])
            user_scores[user_id][f"Recall@{k}"] = hit_count / len(labels)
            user_scores[user_id][f"HitRate@{k}"] = 1.0 if hit_count else 0.0
        completed_users.add(user_id)

    duplicate_count = 0
    row_count = 0
    for row in iter_jsonl(candidate_path):
        user_id = _string_value(row, "user_id")
        item_id = _string_value(row, "item_id", "parent_asin")
        if user_id not in eval_user_set:
            raise ValueError(f"candidate row contains user outside fixed eval users: {user_id}")
        if not item_id:
            raise ValueError(f"candidate row missing item_id for user={user_id}")
        if current_user != user_id:
            if user_id in completed_users:
                raise ValueError(f"candidate rows for user are not contiguous: {user_id}")
            finalize_user(current_user)
            current_user = user_id
            current_seen_items = set()
            current_hit_items = {k: set() for k in metric_ks}
            seen_users.add(user_id)
        if item_id in current_seen_items:
            duplicate_count += 1
        current_seen_items.add(item_id)
        row_count += 1
        per_user_counts[user_id] += 1
        rank = _int_value(row.get("rank"), per_user_counts[user_id])
        labels = labels_by_user[user_id]
        if item_id in labels:
            for k in metric_ks:
                if rank <= k:
                    current_hit_items[k].add(item_id)
        primary_source = _primary_source(row)
        primary_source_counts[primary_source] += 1
        sources = _sources(row, primary_source)
        all_source_counts.update(sources)
        for left_index, left in enumerate(sources):
            for right in sources[left_index + 1 :]:
                pairwise_source_overlap[left][right] += 1
                pairwise_source_overlap[right][left] += 1
    finalize_user(current_user)

    missing_candidate_users = [user_id for user_id in eval_user_ids if user_id not in seen_users]
    if missing_candidate_users:
        raise ValueError(f"candidate artifact missing eval users: {missing_candidate_users[:10]} (count={len(missing_candidate_users)})")
    if duplicate_count:
        raise ValueError(f"candidate artifact contains duplicate user_id+item_id rows: {duplicate_count}")

    metrics = _aggregate_metrics(eval_user_ids, user_scores, metric_ks=metric_ks)
    segment_metrics = {
        segment: _aggregate_metrics([user_id for user_id in eval_user_ids if user_segments[user_id] == segment], user_scores, include_user_count=True, metric_ks=metric_ks)
        for segment in SEGMENTS
    }
    underfilled_user_count = sum(1 for user_id in eval_user_ids if per_user_counts[user_id] < 500)
    source_audit = {
        "schema_version": f"{SCHEMA_VERSION}.source_audit",
        "user_count": len(eval_user_ids),
        "candidate_row_count": row_count,
        "average_candidates_per_user": round(row_count / len(eval_user_ids), 6),
        "underfilled_user_count": underfilled_user_count,
        "source_contribution_counts": dict(sorted(primary_source_counts.items())),
        "source_contribution_ratio": _ratios(primary_source_counts, row_count),
        "all_source_contribution_counts": dict(sorted(all_source_counts.items())),
        "all_source_contribution_ratio": _ratios(all_source_counts, sum(all_source_counts.values())),
        "popular_category_contribution_ratio": round((primary_source_counts.get("popular", 0) + primary_source_counts.get("category", 0)) / row_count, 6) if row_count else 0.0,
        "source_overlap": {source: dict(sorted(overlaps.items())) for source, overlaps in sorted(pairwise_source_overlap.items())},
        "duplicate_user_item_count": duplicate_count,
        "no_oracle_label_injection": True,
    }
    return metrics, segment_metrics, source_audit


def _aggregate_metrics(user_ids: list[str], user_scores: dict[str, dict[str, float]], *, include_user_count: bool = False, metric_ks: Iterable[int] = METRIC_KS) -> dict[str, Any]:
    payload: dict[str, Any] = {"user_count": len(user_ids)} if include_user_count else {}
    for k in metric_ks:
        for metric_name in (f"Recall@{k}", f"HitRate@{k}"):
            payload[metric_name] = round(sum(user_scores[user_id][metric_name] for user_id in user_ids) / len(user_ids), 6) if user_ids else 0.0
    return payload


def _write_eval_user_sequence_clean_manifest(base_clean_manifest_path: Path, output_dir: Path, eval_user_ids: list[str], target_manifest_path: Path) -> Path:
    clean_manifest = read_json(base_clean_manifest_path)
    sequence_path = _resolve_repo_path(clean_manifest["train_user_sequences_path"])
    target_user_set = set(eval_user_ids)
    selected_sequences: dict[str, dict[str, Any]] = {}
    for sequence in iter_jsonl(sequence_path):
        user_id = str(sequence.get("user_id") or "")
        if user_id in target_user_set:
            selected_sequences[user_id] = sequence
            if len(selected_sequences) == len(target_user_set):
                break
    missing_user_ids = [user_id for user_id in eval_user_ids if user_id not in selected_sequences]
    if missing_user_ids:
        raise ValueError(f"fixed eval users missing train-only sequences: {missing_user_ids[:5]}")

    sequence_view_path = output_dir / "candidate_generation_train_user_sequences.jsonl"
    write_jsonl(sequence_view_path, [selected_sequences[user_id] for user_id in eval_user_ids])
    clean_manifest_view = dict(clean_manifest)
    clean_manifest_view["train_user_sequences_path"] = str(sequence_view_path)
    clean_manifest_view["eval_user_sequence_view"] = {
        "schema_version": "pool500_offline_eval_train_sequence_view_v1",
        "source_train_user_sequences_path": str(sequence_path),
        "source_eval_target_manifest_path": str(target_manifest_path),
        "user_count": len(eval_user_ids),
        "user_set_hash": canonical_user_set_hash(eval_user_ids),
        "label_inputs_role": "evaluation_only_not_recall_generation_inputs",
        "candidate_generation_allowed": False,
    }
    clean_manifest_view_path = output_dir / "candidate_generation_clean_manifest.json"
    write_json(clean_manifest_view_path, clean_manifest_view)
    return clean_manifest_view_path


def _resolve_repo_path(value: Any) -> Path:
    path = Path(str(value))
    return path if path.is_absolute() else ROOT / path


def _candidate_generation_target_manifest(eval_manifest: dict[str, Any], eval_manifest_path: Path, user_ids: list[str], user_set_hash: str) -> dict[str, Any]:
    return {
        "schema_version": DERIVED_TARGET_SCHEMA_VERSION,
        "status": "PASS",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scope": "diagnostic_only_valid_test_eval_user_selection",
        "policy_role": "eval_target_user_manifest_not_recall_source",
        "diagnostic_only": True,
        "eval_label_inputs_role": "evaluation_only_valid_test_labels_not_recall_generation_inputs",
        "source_eval_manifest_path": str(eval_manifest_path),
        "source_eval_manifest_schema_version": eval_manifest.get("schema_version"),
        "source_eval_user_set_hash": eval_manifest.get("user_set_hash"),
        "selected_user_set_hash": user_set_hash,
        "candidate_generation_allowed": False,
        "ranking_input_replacement_allowed": False,
        "ranking_replacement_allowed": False,
        "promotion_allowed": False,
        "pool1000_allowed": False,
        "final_pool500_ready_claimed": False,
        "full_pool500_ready_declared": False,
        "target_user_ids": user_ids,
        "eligible_user_ids": user_ids,
        "summary": {"selected_user_count": len(user_ids), "target_user_hash": user_set_hash},
    }


def _clean_manifest_from_eval(eval_manifest: dict[str, Any]) -> Path:
    source_manifest_paths = eval_manifest.get("source_manifest_paths") if isinstance(eval_manifest.get("source_manifest_paths"), dict) else {}
    value = source_manifest_paths.get("clean_manifest_path")
    return Path(str(value)) if value else DEFAULT_CLEAN_MANIFEST


def _recall_route_profile(generation_manifest: dict[str, Any], enable_semantic: bool, semantic_max_rows: int) -> dict[str, Any]:
    return {
        "candidate_generation_schema_version": generation_manifest.get("schema_version"),
        "mode": generation_manifest.get("mode"),
        "status": generation_manifest.get("status"),
        "decision": generation_manifest.get("decision"),
        "enable_semantic": enable_semantic,
        "semantic_max_rows": semantic_max_rows,
        "recall_profile_config": generation_manifest.get("recall_profile_config"),
    }


def _user_segments(users: list[dict[str, Any]]) -> dict[str, str]:
    segments = {str(user["user_id"]): str(user.get("segment") or "") for user in users}
    invalid = sorted({segment for segment in segments.values() if segment not in SEGMENTS})
    if invalid:
        raise ValueError(f"fixed eval users contain unsupported segments: {invalid}")
    return segments


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
        text = str(value).strip().lower()
        return text in {"1", "true", "yes", "positive", "purchased", "clicked"}
    return True


def _primary_source(row: dict[str, Any]) -> str:
    source = row.get("source") or row.get("primary_source")
    return str(source) if source else "unknown"


def _sources(row: dict[str, Any], primary_source: str) -> list[str]:
    raw_sources = row.get("sources")
    if isinstance(raw_sources, list):
        sources = [str(source) for source in raw_sources if source]
    else:
        sources = [primary_source]
    deduped = []
    seen = set()
    for source in sources:
        if source not in seen:
            deduped.append(source)
            seen.add(source)
    return deduped or [primary_source]


def _ratios(counts: Counter[str], denominator: int) -> dict[str, float]:
    return {source: round(count / denominator, 6) if denominator else 0.0 for source, count in sorted(counts.items())}


def main() -> None:
    args = parse_args()
    metric_ks = _parse_metric_ks(args.metric_ks)
    if args.source_index_manifest:
        if not args.output_manifest:
            raise ValueError("--output-manifest is required with --source-index-manifest")
        manifest = run_raw_two_tower_eval(
            source_index_manifest_path=Path(args.source_index_manifest),
            output_manifest_path=Path(args.output_manifest),
            eval_manifest_path=Path(args.eval_manifest),
            eval_users_path=Path(args.eval_users) if args.eval_users else None,
            output_dir=None if args.output_dir == str(DEFAULT_OUTPUT_DIR) else Path(args.output_dir),
            clean_manifest_path=Path(args.clean_manifest) if args.clean_manifest else None,
            lightweight_views_manifest_path=Path(args.lightweight_views_manifest),
            limit_users=args.limit_users,
            enable_semantic=args.enable_semantic,
            semantic_max_rows=args.semantic_max_rows,
            overwrite=args.overwrite,
            enforce_venv=not args.skip_venv_check,
            metric_ks=metric_ks,
        )
        print(json.dumps({"status": "PASS", "raw_two_tower_eval_manifest_path": str(Path(args.output_manifest)), "metrics": manifest["metrics"]}, ensure_ascii=False, indent=2))
        return
    if args.output_ablation or args.with_two_tower_source_manifest or args.without_two_tower:
        if not args.with_two_tower_source_manifest:
            raise ValueError("--with-two-tower-source-manifest is required for ablation")
        if not args.without_two_tower:
            raise ValueError("--without-two-tower is required for ablation")
        if not args.output_ablation:
            raise ValueError("--output-ablation is required for ablation")
        manifest = run_two_tower_ablation(
            with_two_tower_source_manifest_path=Path(args.with_two_tower_source_manifest),
            output_ablation_path=Path(args.output_ablation),
            eval_manifest_path=Path(args.eval_manifest),
            eval_users_path=Path(args.eval_users) if args.eval_users else None,
            output_dir=None if args.output_dir == str(DEFAULT_OUTPUT_DIR) else Path(args.output_dir),
            clean_manifest_path=Path(args.clean_manifest) if args.clean_manifest else None,
            lightweight_views_manifest_path=Path(args.lightweight_views_manifest),
            limit_users=args.limit_users,
            enable_semantic=args.enable_semantic,
            semantic_max_rows=args.semantic_max_rows,
            overwrite=args.overwrite,
            enforce_venv=not args.skip_venv_check,
            metric_ks=metric_ks,
        )
        print(json.dumps({"status": "PASS", "ablation_manifest_path": str(Path(args.output_ablation)), "pool_budget_decision": manifest["pool_budget_decision"]}, ensure_ascii=False, indent=2))
        return
    manifest = run_pool500_offline_eval_baseline(
        eval_manifest_path=Path(args.eval_manifest),
        eval_users_path=Path(args.eval_users) if args.eval_users else None,
        output_dir=Path(args.output_dir),
        clean_manifest_path=Path(args.clean_manifest) if args.clean_manifest else None,
        lightweight_views_manifest_path=Path(args.lightweight_views_manifest),
        limit_users=args.limit_users,
        enable_semantic=args.enable_semantic,
        semantic_max_rows=args.semantic_max_rows,
        overwrite=args.overwrite,
        enforce_venv=not args.skip_venv_check,
        metric_ks=metric_ks,
    )
    print(json.dumps({"status": "PASS", "baseline_manifest_path": str(Path(args.output_dir) / "baseline_manifest.json"), "metrics_path": manifest["metrics_path"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
