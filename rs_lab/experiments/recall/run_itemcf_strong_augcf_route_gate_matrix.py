from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rs_core.common.io import iter_jsonl, read_json, write_json
from rs_core.common.runtime import enforce_project_venv
from rs_lab.experiments.recall.run_full_data_pool500_recall_only import DEFAULT_LIGHTWEIGHT_VIEWS_MANIFEST
from rs_lab.experiments.recall.run_pool500_offline_eval_baseline import (
    DEFAULT_EVAL_MANIFEST,
    METRIC_KS,
    CandidateRunner,
    _load_eval_labels,
    _load_eval_users,
    _load_offline_eval_manifest,
    _parse_metric_ks,
    _primary_source,
    _sources,
    _string_value,
    run_full_data_pool500_recall_only,
    run_pool500_offline_eval_baseline,
)

SCHEMA_VERSION = "itemcf_strong_augcf_route_gate_evidence_matrix_v1"
DEFAULT_OUTPUT_DIR = ROOT / "outputs" / "eval" / "itemcf_strong_augcf_route_gate_matrix"
DEFAULT_OUTPUT_MANIFEST = "route_gate_evidence_manifest.json"
DIAGNOSTIC_DECISIONS = {
    "continue_diagnostic_route_gate",
    "stop_augcf_lite_due_to_overlap_or_hotness",
    "needs_more_ablation",
}
NO_OVERRIDE_VALUES = {"", "default", "relaxed"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run itemcf_strong AugCF route-gate variants on fixed pool500 offline eval users and aggregate evidence.")
    parser.add_argument("--eval-manifest", default=str(DEFAULT_EVAL_MANIFEST))
    parser.add_argument("--eval-users", default="", help="Optional users.jsonl beside the fixed eval manifest; defaults to manifest_dir/users.jsonl.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--output-manifest", default=DEFAULT_OUTPUT_MANIFEST)
    parser.add_argument("--clean-manifest", default="", help="Override clean manifest; defaults to eval manifest source_manifest_paths.clean_manifest_path.")
    parser.add_argument("--lightweight-views-manifest", default=str(DEFAULT_LIGHTWEIGHT_VIEWS_MANIFEST))
    parser.add_argument("--limit-users", type=int, default=0)
    parser.add_argument("--metric-ks", default=",".join(str(k) for k in METRIC_KS))
    parser.add_argument("--variant", action="append", default=[], help="Variant as name=path. path default/relaxed/empty means no source override; otherwise itemcf_strong source override.")
    parser.add_argument(
        "--source-manifest",
        action="append",
        default=[],
        help="Base source override applied to every variant as source=/path, e.g. swing_recall=/tmp/disabled.json.",
    )
    parser.add_argument("--enable-semantic", action="store_true")
    parser.add_argument("--semantic-max-rows", type=int, default=200000)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--skip-venv-check", action="store_true")
    return parser.parse_args()


def run_itemcf_strong_augcf_route_gate_matrix(
    *,
    variants: dict[str, str | Path],
    base_source_manifest_paths: dict[str, str | Path] | None = None,
    eval_manifest_path: Path = DEFAULT_EVAL_MANIFEST,
    eval_users_path: Path | None = None,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    output_manifest_path: Path | None = None,
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
    if enforce_venv:
        enforce_project_venv(ROOT)
    metric_ks = _parse_metric_ks(metric_ks)
    max_k = max(metric_ks)
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    output_manifest_path = (output_manifest_path or output_dir / DEFAULT_OUTPUT_MANIFEST).resolve()

    ordered_variants = _normalized_variants(variants)
    base_source_overrides = _base_source_overrides(base_source_manifest_paths)
    eval_manifest = _load_offline_eval_manifest(eval_manifest_path.resolve())
    users = _load_eval_users(eval_manifest, eval_manifest_path.resolve(), eval_users_path)
    selected_users = users[:limit_users] if limit_users else users
    eval_user_ids = [str(user["user_id"]) for user in selected_users]
    labels_by_user = _load_eval_labels(eval_manifest, eval_user_ids)

    variant_payloads: dict[str, dict[str, Any]] = {}
    candidate_pairs_by_variant: dict[str, set[tuple[str, str]]] = {}
    positive_pairs_by_variant: dict[str, set[tuple[str, str]]] = {}
    baseline_name = "baseline"

    for name, raw_path in ordered_variants.items():
        source_overrides = _source_overrides(raw_path, base_source_overrides)
        variant_output_dir = output_dir / name
        baseline_manifest = run_pool500_offline_eval_baseline(
            eval_manifest_path=eval_manifest_path,
            eval_users_path=eval_users_path,
            output_dir=variant_output_dir,
            clean_manifest_path=clean_manifest_path,
            lightweight_views_manifest_path=lightweight_views_manifest_path,
            limit_users=limit_users,
            enable_semantic=enable_semantic,
            semantic_max_rows=semantic_max_rows,
            overwrite=overwrite,
            enforce_venv=False,
            metric_ks=metric_ks,
            source_manifest_paths=source_overrides,
            candidate_runner=candidate_runner,
        )
        metrics = read_json(Path(baseline_manifest["metrics_path"]))
        source_audit = read_json(Path(baseline_manifest["source_audit_path"]))
        candidate_path = Path(baseline_manifest["candidate_artifact_path"])
        candidate_pairs = _candidate_pairs(candidate_path, max_k=max_k)
        positive_pairs = _positive_pairs(candidate_path, labels_by_user, max_k=max_k)
        candidate_pairs_by_variant[name] = candidate_pairs
        positive_pairs_by_variant[name] = positive_pairs
        variant_payloads[name] = {
            "variant": name,
            "requested_source_path": str(raw_path),
            "source_manifest_overrides": baseline_manifest.get("source_manifest_overrides", {}),
            "baseline_manifest_path": str(variant_output_dir / "baseline_manifest.json"),
            "baseline_manifest": _baseline_manifest_summary(baseline_manifest),
            "metrics": _metric_summary(metrics, metric_ks),
            "source_audit": _source_audit_summary(source_audit),
            "candidate_artifact": _candidate_artifact_summary(candidate_path, candidate_pairs),
            "diagnostic_hot_budget_audit": _diagnostic_hot_budget_audit_summary(baseline_manifest, source_audit),
            "source_hit_attribution": _source_hit_attribution(candidate_path, labels_by_user, max_k=max_k),
            "no_oracle": True,
            "eval_only": True,
            "diagnostic_only": True,
            "label_inputs_role": "evaluation_only_not_recall_generation_inputs",
            "label_backflow_allowed": False,
        }

    baseline_metrics = variant_payloads[baseline_name]["metrics"]
    baseline_candidates = candidate_pairs_by_variant[baseline_name]
    baseline_positive_pairs = positive_pairs_by_variant[baseline_name]
    for name, payload in variant_payloads.items():
        positive_pairs = positive_pairs_by_variant[name]
        candidate_pairs = candidate_pairs_by_variant[name]
        payload["delta_vs_baseline"] = _metric_delta(payload["metrics"], baseline_metrics)
        payload["positive_hit_pairs"] = {
            "count": len(positive_pairs),
            "exclusive_vs_baseline_count": len(positive_pairs - baseline_positive_pairs),
            "baseline_exclusive_count": len(baseline_positive_pairs - positive_pairs),
            "overlap_vs_baseline_count": len(positive_pairs & baseline_positive_pairs),
            "exclusive_vs_baseline": _serialized_pairs(positive_pairs - baseline_positive_pairs),
            "overlap_vs_baseline": _serialized_pairs(positive_pairs & baseline_positive_pairs),
        }
        payload["user_item_candidate_overlap"] = _overlap_payload(candidate_pairs, baseline_candidates)
        payload["diagnostic_decision"] = _diagnostic_decision(payload)

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "eval_manifest_path": str(eval_manifest_path.resolve()),
        "eval_users_path": str((eval_users_path or eval_manifest_path.parent / "users.jsonl").resolve()),
        "output_dir": str(output_dir),
        "metric_ks": metric_ks,
        "baseline_variant": baseline_name,
        "variants": variant_payloads,
        "diagnostic_decisions_allowed": sorted(DIAGNOSTIC_DECISIONS),
        "no_oracle": True,
        "no_oracle_label_injection": True,
        "eval_only": True,
        "diagnostic_only": True,
        "label_inputs_role": "evaluation_only_not_recall_generation_inputs",
        "label_backflow_allowed": False,
        "promotion_allowed": False,
        "ready_or_promote_decision_allowed": False,
    }
    write_json(output_manifest_path, manifest)
    return manifest


def _normalized_variants(variants: dict[str, str | Path]) -> dict[str, str | Path]:
    ordered: dict[str, str | Path] = {}
    if "baseline" not in variants:
        ordered["baseline"] = "default"
    for name, value in variants.items():
        clean_name = str(name).strip()
        if not clean_name:
            raise ValueError("variant name must be non-empty")
        if clean_name in ordered:
            raise ValueError(f"duplicate variant name: {clean_name}")
        ordered[clean_name] = value
    return ordered


def _base_source_overrides(base_source_manifest_paths: dict[str, str | Path] | None) -> dict[str, Path]:
    return {str(source): Path(path) for source, path in (base_source_manifest_paths or {}).items()}


def _source_overrides(raw_path: str | Path, base_source_overrides: dict[str, Path] | None = None) -> dict[str, Path] | None:
    overrides = dict(base_source_overrides or {})
    text = str(raw_path).strip()
    if text not in NO_OVERRIDE_VALUES:
        overrides["itemcf_strong"] = Path(text)
    return overrides or None


def _candidate_pairs(candidate_path: Path, *, max_k: int) -> set[tuple[str, str]]:
    pairs: set[tuple[str, str]] = set()
    for row in iter_jsonl(candidate_path):
        if int(row.get("rank") or max_k) <= max_k:
            pairs.add((_string_value(row, "user_id"), _string_value(row, "item_id", "parent_asin")))
    return pairs


def _positive_pairs(candidate_path: Path, labels_by_user: dict[str, set[str]], *, max_k: int) -> set[tuple[str, str]]:
    pairs: set[tuple[str, str]] = set()
    for row in iter_jsonl(candidate_path):
        user_id = _string_value(row, "user_id")
        item_id = _string_value(row, "item_id", "parent_asin")
        if int(row.get("rank") or max_k) <= max_k and item_id in labels_by_user.get(user_id, set()):
            pairs.add((user_id, item_id))
    return pairs


def _source_hit_attribution(candidate_path: Path, labels_by_user: dict[str, set[str]], *, max_k: int) -> dict[str, Any]:
    primary_counts: Counter[str] = Counter()
    all_source_counts: Counter[str] = Counter()
    for row in iter_jsonl(candidate_path):
        user_id = _string_value(row, "user_id")
        item_id = _string_value(row, "item_id", "parent_asin")
        if int(row.get("rank") or max_k) > max_k or item_id not in labels_by_user.get(user_id, set()):
            continue
        primary_source = _primary_source(row)
        primary_counts[primary_source] += 1
        all_source_counts.update(_sources(row, primary_source))
    total = sum(primary_counts.values())
    return {
        "positive_hit_count": total,
        "primary_source_counts": dict(sorted(primary_counts.items())),
        "all_source_counts": dict(sorted(all_source_counts.items())),
        "primary_source_ratio": {source: round(count / total, 6) if total else 0.0 for source, count in sorted(primary_counts.items())},
    }


def _metric_summary(metrics: dict[str, Any], metric_ks: Iterable[int]) -> dict[str, float]:
    summary: dict[str, float] = {}
    for k in metric_ks:
        for metric_name in (f"Recall@{k}", f"HitRate@{k}"):
            summary[metric_name] = float(metrics.get(metric_name, 0.0))
    return summary


def _metric_delta(metrics: dict[str, float], baseline_metrics: dict[str, float]) -> dict[str, float]:
    return {
        "Recall@500": round(metrics.get("Recall@500", 0.0) - baseline_metrics.get("Recall@500", 0.0), 6),
        "HitRate@500": round(metrics.get("HitRate@500", 0.0) - baseline_metrics.get("HitRate@500", 0.0), 6),
    }


def _baseline_manifest_summary(manifest: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": manifest.get("schema_version"),
        "eval_user_set_hash": manifest.get("eval_user_set_hash"),
        "total_user_count": manifest.get("total_user_count"),
        "segment_counts": manifest.get("segment_counts"),
        "candidate_artifact_path": manifest.get("candidate_artifact_path"),
        "metrics_path": manifest.get("metrics_path"),
        "source_audit_path": manifest.get("source_audit_path"),
        "recall_route_profile": manifest.get("recall_route_profile"),
        "no_oracle": manifest.get("no_oracle"),
        "no_oracle_label_injection": manifest.get("no_oracle_label_injection"),
        "no_oracle_semantics": manifest.get("no_oracle_semantics"),
    }


def _source_audit_summary(source_audit: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "schema_version",
        "user_count",
        "candidate_row_count",
        "average_candidates_per_user",
        "underfilled_user_count",
        "source_contribution_counts",
        "source_contribution_ratio",
        "all_source_contribution_counts",
        "all_source_contribution_ratio",
        "popular_category_contribution_ratio",
        "source_overlap",
        "duplicate_user_item_count",
        "no_oracle_label_injection",
    )
    return {key: source_audit.get(key) for key in keys if key in source_audit}


def _candidate_artifact_summary(candidate_path: Path, candidate_pairs: set[tuple[str, str]]) -> dict[str, Any]:
    return {
        "path": str(candidate_path),
        "exists": candidate_path.is_file(),
        "user_item_pair_count_at_gate_k": len(candidate_pairs),
    }


def _diagnostic_hot_budget_audit_summary(baseline_manifest: dict[str, Any], source_audit: dict[str, Any]) -> dict[str, Any]:
    generation_manifest_path = Path(str(baseline_manifest.get("candidate_generation_manifest_path") or ""))
    generation_manifest = read_json(generation_manifest_path) if generation_manifest_path.is_file() else {}
    audit = generation_manifest.get("diagnostic_hot_budget_audit") if isinstance(generation_manifest.get("diagnostic_hot_budget_audit"), dict) else {}
    return {
        "source": "candidate_generation_manifest" if audit else "source_audit_fallback",
        "audit": audit,
        "popular_category_contribution_ratio": source_audit.get("popular_category_contribution_ratio", 0.0),
        "underfilled_user_count": source_audit.get("underfilled_user_count", 0),
    }


def _overlap_payload(candidate_pairs: set[tuple[str, str]], baseline_pairs: set[tuple[str, str]]) -> dict[str, Any]:
    union = candidate_pairs | baseline_pairs
    overlap = candidate_pairs & baseline_pairs
    return {
        "candidate_pair_count": len(candidate_pairs),
        "baseline_pair_count": len(baseline_pairs),
        "overlap_count": len(overlap),
        "exclusive_vs_baseline_count": len(candidate_pairs - baseline_pairs),
        "baseline_exclusive_count": len(baseline_pairs - candidate_pairs),
        "jaccard_vs_baseline": round(len(overlap) / len(union), 6) if union else 1.0,
    }


def _diagnostic_decision(payload: dict[str, Any]) -> str:
    delta = payload["delta_vs_baseline"]
    overlap = payload["user_item_candidate_overlap"]
    hot_ratio = float(payload["diagnostic_hot_budget_audit"].get("popular_category_contribution_ratio") or 0.0)
    exclusive_hits = int(payload["positive_hit_pairs"].get("exclusive_vs_baseline_count") or 0)
    if hot_ratio >= 0.8 or (exclusive_hits == 0 and overlap.get("jaccard_vs_baseline", 0.0) >= 0.95):
        return "stop_augcf_lite_due_to_overlap_or_hotness"
    if delta.get("Recall@500", 0.0) > 0 or delta.get("HitRate@500", 0.0) > 0 or exclusive_hits > 0:
        return "continue_diagnostic_route_gate"
    return "needs_more_ablation"


def _serialized_pairs(pairs: set[tuple[str, str]], limit: int = 50) -> list[dict[str, str]]:
    return [{"user_id": user_id, "item_id": item_id} for user_id, item_id in sorted(pairs)[:limit]]


def _parse_variants(values: list[str]) -> dict[str, str]:
    variants: dict[str, str] = {}
    for value in values:
        if "=" not in value:
            raise ValueError(f"variant must be name=path: {value}")
        name, path = value.split("=", 1)
        name = name.strip()
        if not name:
            raise ValueError(f"variant name must be non-empty: {value}")
        if name in variants:
            raise ValueError(f"duplicate variant name: {name}")
        variants[name] = path.strip()
    return variants


def _parse_source_manifest_overrides(values: list[str]) -> dict[str, Path]:
    overrides: dict[str, Path] = {}
    for value in values:
        if "=" not in value:
            raise ValueError(f"source manifest override must be source=path: {value}")
        source, path = value.split("=", 1)
        source = source.strip()
        if not source:
            raise ValueError(f"source name must be non-empty: {value}")
        if source in overrides:
            raise ValueError(f"duplicate source manifest override: {source}")
        overrides[source] = Path(path.strip())
    return overrides


def main() -> None:
    args = parse_args()
    variants = _parse_variants(args.variant) or {"relaxed": "relaxed", "q20": "default", "q30": "default", "no_hot": "default"}
    output_manifest_path = Path(args.output_manifest)
    if not output_manifest_path.is_absolute():
        output_manifest_path = Path(args.output_dir) / output_manifest_path
    manifest = run_itemcf_strong_augcf_route_gate_matrix(
        variants=variants,
        base_source_manifest_paths=_parse_source_manifest_overrides(args.source_manifest),
        eval_manifest_path=Path(args.eval_manifest),
        eval_users_path=Path(args.eval_users) if args.eval_users else None,
        output_dir=Path(args.output_dir),
        output_manifest_path=output_manifest_path,
        clean_manifest_path=Path(args.clean_manifest) if args.clean_manifest else None,
        lightweight_views_manifest_path=Path(args.lightweight_views_manifest),
        limit_users=args.limit_users,
        enable_semantic=args.enable_semantic,
        semantic_max_rows=args.semantic_max_rows,
        overwrite=args.overwrite,
        enforce_venv=not args.skip_venv_check,
        metric_ks=_parse_metric_ks(args.metric_ks),
    )
    print(json.dumps({"status": "PASS", "route_gate_evidence_manifest_path": str(output_manifest_path), "variant_count": len(manifest["variants"])}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
