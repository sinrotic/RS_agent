from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[4]
DATA_ROOT = ROOT / "data" / "processed" / "amazon_2023_recall_recent_2y_1m_3m"
DEFAULT_SOURCE_MANIFEST = (
    ROOT
    / "outputs"
    / "recall"
    / "pool500_method_sources_newdata"
    / "itemcf_strong_relaxed_supplemental_v1"
    / "itemcf_strong"
    / "formal_relaxed_from_recent2y"
    / "source_index_manifest.json"
)
DEFAULT_OUTPUT = (
    ROOT
    / "outputs"
    / "recall"
    / "pool500_method_sources_newdata"
    / "itemcf_strong_relaxed_supplemental_v1"
    / "itemcf_strong"
    / "formal_relaxed_from_recent2y_eval"
    / "purchase_label_eval.json"
)

K_VALUES = (20, 50, 100, 500)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Evaluate itemcf_strong relaxed source against purchase/strong-positive labels only."
    )
    parser.add_argument("--source-index-manifest", type=Path, default=DEFAULT_SOURCE_MANIFEST)
    parser.add_argument("--data-root", type=Path, default=DATA_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--target-limit", type=int, default=0, help="0 means all labeled train users")
    parser.add_argument("--seed-window", type=int, default=20)
    parser.add_argument("--candidate-limit", type=int, default=500)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    data_root = _resolve_path(args.data_root)
    source_manifest_path = _resolve_path(args.source_index_manifest)
    output_path = _resolve_path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    source_manifest, edges, edge_stats = _load_manifest_edges(source_manifest_path)
    dst_universe = edge_stats.pop("dst_universe")
    labels, label_stats = _load_eval_labels(data_root, dst_universe)
    all_label_users = set().union(*(set(view) for view in labels.values()))
    item_hotness = _load_item_hotness(data_root)

    targets_seen = 0
    reports = _empty_reports(labels)
    examples: list[dict[str, Any]] = []
    all_labeled_train_users_scanned = 0
    all_labeled_train_users_with_strong_seed_hit = 0

    for seq in _iter_jsonl(data_root / "user_sequences.train.jsonl"):
        user_id = str(seq.get("user_id") or "")
        if user_id not in all_label_users:
            continue
        all_labeled_train_users_scanned += 1
        strong_seeds = _recent_unique(seq.get("recent_strong_positive_item_sequence"), args.seed_window)
        if any(seed in edges for seed in strong_seeds):
            all_labeled_train_users_with_strong_seed_hit += 1
        if args.target_limit and targets_seen >= args.target_limit:
            continue
        targets_seen += 1
        seen = set(_recent_unique(seq.get("recent_positive_item_sequence"), 10000)) | set(strong_seeds)
        candidates, seed_hit = _gen_candidates(edges, strong_seeds, seen, args.candidate_limit)
        candidate_items = [item_id for item_id, _score in candidates]
        hot_counter = Counter(item_hotness.get(item_id, "unknown") or "unknown" for item_id in candidate_items)

        if candidate_items and len(examples) < 5:
            examples.append(
                {
                    "user_id": user_id,
                    "strong_seed_count": len(strong_seeds),
                    "candidate_count": len(candidate_items),
                    "top_candidates": candidate_items[:10],
                    "label_views": {
                        view: sorted(view_labels[user_id])[:10]
                        for view, view_labels in labels.items()
                        if user_id in view_labels
                    },
                }
            )

        for view, labels_by_user in labels.items():
            user_labels = labels_by_user.get(user_id)
            if not user_labels:
                continue
            in_universe_labels = user_labels & dst_universe
            report = reports[view]
            report["target_user_count"] += 1
            report["label_count_total"] += len(user_labels)
            report["label_count_in_dst_universe"] += len(in_universe_labels)
            report["seed_hit_user_count"] += int(seed_hit)
            report["user_coverage_count"] += int(bool(candidate_items))
            report["candidate_row_count"] += len(candidate_items)
            report["candidate_count_hist_capped_at_10"][min(len(candidate_items), 10)] += 1
            report["candidate_hotness_counts"].update(hot_counter)
            for k in K_VALUES:
                top = set(candidate_items[:k])
                hits = len(top & user_labels)
                in_universe_hits = len(top & in_universe_labels)
                report["metrics"][k]["hits"] += hits
                report["metrics"][k]["hit_users"] += int(hits > 0)
                report["metrics"][k]["recall_numer"] += hits
                report["metrics"][k]["recall_denom"] += len(user_labels)
                report["metrics"][k]["in_universe_hits"] += in_universe_hits
                report["metrics"][k]["in_universe_hit_users"] += int(in_universe_hits > 0)
                report["metrics"][k]["in_universe_recall_numer"] += in_universe_hits
                report["metrics"][k]["in_universe_recall_denom"] += len(in_universe_labels)

    final_reports = {view: _finalize_report(view_report) for view, view_report in reports.items()}
    source_metadata = _source_manifest_metadata(source_manifest)
    output = {
        "schema_version": "itemcf_strong_purchase_label_eval_v1",
        "source": source_metadata["source"],
        "variant": source_metadata["variant"],
        "source_variant": source_metadata["source_variant"],
        "source_run_id": source_metadata["run_id"],
        "run_id": source_metadata["run_id"],
        "index_scope": source_metadata["index_scope"],
        "hot_budget_policy": source_metadata["hot_budget_policy"],
        "controlled_hot_budget": source_metadata["controlled_hot_budget"],
        "max_final_hot_share_per_user": source_metadata["max_final_hot_share_per_user"],
        "diagnostic_only": source_metadata["diagnostic_only"],
        "source_status": source_metadata["source_status"],
        "source_index_manifest_path": str(source_manifest_path),
        "source_manifest_status": source_metadata["source_status"],
        "candidate_generation_inputs": [str(data_root / "user_sequences.train.jsonl"), str(source_manifest_path)],
        "evaluation_label_inputs": [
            str(data_root / "canonical_interactions.valid.jsonl"),
            str(data_root / "canonical_interactions.test.jsonl"),
        ],
        "labels_role": "evaluation_only_not_candidate_generation_or_training",
        "label_views": {
            "purchase_positive": "verified_purchase == true and label_binary > 0",
            "strong_positive": "label_strong > 0",
            "verified_purchase_any_rating": "verified_purchase == true regardless of rating/label_binary",
            "all_positive": "label_binary > 0",
        },
        "target_limit": args.target_limit,
        "actual_target_user_count_union": targets_seen,
        "all_labeled_train_users_scanned": all_labeled_train_users_scanned,
        "all_labeled_train_users_with_strong_seed_hit": all_labeled_train_users_with_strong_seed_hit,
        "all_labeled_train_seed_hit_rate": round(
            all_labeled_train_users_with_strong_seed_hit / max(all_labeled_train_users_scanned, 1), 6
        ),
        "seed_window": f"recent_strong_positive_item_sequence:last{args.seed_window}_unique",
        "candidate_limit": args.candidate_limit,
        "source_edge_stats": edge_stats,
        "source_metadata": source_metadata,
        "label_stats": label_stats,
        "reports": final_reports,
        "examples": examples,
        "decision_hint": "Purchase/strong-positive labels are eval-only; use purchase_positive and strong_positive views for itemcf_strong route-gate judgement.",
    }
    output_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(output_path), "reports": _compact_reports(final_reports)}, ensure_ascii=False))


def _empty_reports(labels: dict[str, dict[str, set[str]]]) -> dict[str, dict[str, Any]]:
    return {
        view: {
            "target_user_count": 0,
            "label_count_total": 0,
            "label_count_in_dst_universe": 0,
            "seed_hit_user_count": 0,
            "user_coverage_count": 0,
            "candidate_row_count": 0,
            "candidate_count_hist_capped_at_10": Counter(),
            "candidate_hotness_counts": Counter(),
            "metrics": {
                k: {
                    "hits": 0,
                    "hit_users": 0,
                    "recall_numer": 0,
                    "recall_denom": 0,
                    "in_universe_hits": 0,
                    "in_universe_hit_users": 0,
                    "in_universe_recall_numer": 0,
                    "in_universe_recall_denom": 0,
                }
                for k in K_VALUES
            },
        }
        for view in labels
    }


def _finalize_report(report: dict[str, Any]) -> dict[str, Any]:
    target_users = report["target_user_count"]
    candidate_rows = report["candidate_row_count"]
    out = {
        "target_user_count": target_users,
        "label_count_total": report["label_count_total"],
        "label_count_in_dst_universe": report["label_count_in_dst_universe"],
        "label_in_dst_universe_ratio": round(
            report["label_count_in_dst_universe"] / max(report["label_count_total"], 1), 6
        ),
        "seed_hit_user_count": report["seed_hit_user_count"],
        "seed_hit_rate": round(report["seed_hit_user_count"] / max(target_users, 1), 6),
        "user_coverage_count": report["user_coverage_count"],
        "user_coverage_rate": round(report["user_coverage_count"] / max(target_users, 1), 6),
        "candidate_row_count": candidate_rows,
        "avg_candidates_per_user": round(candidate_rows / max(target_users, 1), 6),
        "candidate_count_hist_capped_at_10": dict(sorted(report["candidate_count_hist_capped_at_10"].items())),
        "hotness_audit": {
            "candidate_hotness_counts": dict(sorted(report["candidate_hotness_counts"].items())),
            "candidate_hot_share": round(report["candidate_hotness_counts"].get("hot", 0) / max(candidate_rows, 1), 6),
        },
        "metrics": {},
    }
    for k, values in report["metrics"].items():
        out["metrics"][f"hit_rate_at_{k}"] = round(values["hit_users"] / max(target_users, 1), 6)
        out["metrics"][f"recall_at_{k}"] = round(values["recall_numer"] / max(values["recall_denom"], 1), 6)
        out["metrics"][f"unique_hit_users_at_{k}"] = values["hit_users"]
        out["metrics"][f"total_hits_at_{k}"] = values["hits"]
        out["metrics"][f"in_universe_hit_rate_at_{k}"] = round(
            values["in_universe_hit_users"] / max(target_users, 1), 6
        )
        out["metrics"][f"in_universe_recall_at_{k}"] = round(
            values["in_universe_recall_numer"] / max(values["in_universe_recall_denom"], 1), 6
        )
        out["metrics"][f"in_universe_unique_hit_users_at_{k}"] = values["in_universe_hit_users"]
        out["metrics"][f"in_universe_total_hits_at_{k}"] = values["in_universe_hits"]
    return out


def _compact_reports(reports: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        view: {
            "target_user_count": report["target_user_count"],
            "label_in_dst_universe_ratio": report["label_in_dst_universe_ratio"],
            "user_coverage_rate": report["user_coverage_rate"],
            "recall_at_500": report["metrics"]["recall_at_500"],
            "in_universe_recall_at_500": report["metrics"]["in_universe_recall_at_500"],
            "hit_rate_at_500": report["metrics"]["hit_rate_at_500"],
            "total_hits_at_500": report["metrics"]["total_hits_at_500"],
        }
        for view, report in reports.items()
    }


def _source_manifest_metadata(manifest: dict[str, Any]) -> dict[str, Any]:
    diagnostic_policy = manifest.get("diagnostic_policy") if isinstance(manifest.get("diagnostic_policy"), dict) else {}

    def first_present(*keys: str, default: Any = None) -> Any:
        for key in keys:
            if key in manifest and manifest[key] is not None:
                return manifest[key]
            if key in diagnostic_policy and diagnostic_policy[key] is not None:
                return diagnostic_policy[key]
        return default

    variant = first_present("variant", "source_variant", default="relaxed_strong_supplemental_recent2y_v1")
    source_variant = first_present("source_variant", "variant", default=variant)
    return {
        "source": first_present("source", "canonical_source", default="itemcf_strong"),
        "variant": variant,
        "source_variant": source_variant,
        "run_id": first_present("run_id"),
        "index_scope": first_present("index_scope"),
        "hot_budget_policy": first_present("hot_budget_policy"),
        "controlled_hot_budget": first_present("controlled_hot_budget"),
        "max_final_hot_share_per_user": first_present("max_final_hot_share_per_user"),
        "diagnostic_only": first_present("diagnostic_only"),
        "source_status": first_present("source_status"),
    }


def _load_manifest_edges(manifest_path: Path) -> tuple[dict[str, Any], dict[str, list[tuple[str, float]]], dict[str, Any]]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    paths = []
    if manifest.get("edges_path"):
        paths.append(_resolve_path(manifest["edges_path"]))
    paths.extend(_resolve_path(path) for path in manifest.get("edges_shards") or [])
    outputs = manifest.get("outputs") if isinstance(manifest.get("outputs"), dict) else {}
    if not paths and outputs.get("edges_path"):
        paths.append(_resolve_path(outputs["edges_path"]))
    if not paths and outputs.get("edges_shards"):
        paths.extend(_resolve_path(path) for path in outputs["edges_shards"])
    by_src: dict[str, list[tuple[str, float]]] = defaultdict(list)
    src_items: set[str] = set()
    dst_items: set[str] = set()
    score_values: list[float] = []
    support_hist: Counter[int] = Counter()
    edge_type_counts: Counter[str] = Counter()
    rows = 0
    for path in paths:
        for row in _iter_jsonl(path):
            src = str(row.get("src_item") or "")
            dst = str(row.get("dst_item") or "")
            if not src or not dst:
                continue
            score = float(row.get("score") or 0.0)
            meta = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
            by_src[src].append((dst, score))
            src_items.add(src)
            dst_items.add(dst)
            score_values.append(score)
            support_hist[min(int(meta.get("pair_support") or meta.get("cooc_cnt") or 0), 5)] += 1
            edge_type = str(meta.get("edge_type") or meta.get("edge_mode") or "unknown")
            edge_type_counts[edge_type] += 1
            rows += 1
    for src in by_src:
        by_src[src].sort(key=lambda item: (-item[1], item[0]))
    return manifest, by_src, {
        "row_count": rows,
        "src_item_count": len(src_items),
        "dst_item_count": len(dst_items),
        "support_hist_capped5": dict(sorted(support_hist.items())),
        "edge_type_counts": dict(sorted(edge_type_counts.items())),
        "score_min": min(score_values) if score_values else 0.0,
        "score_max": max(score_values) if score_values else 0.0,
        "score_avg": round(mean(score_values), 6) if score_values else 0.0,
        "dst_universe": dst_items,
    }


def _load_eval_labels(data_root: Path, dst_universe: set[str]) -> tuple[dict[str, dict[str, set[str]]], dict[str, Any]]:
    labels: dict[str, dict[str, set[str]]] = {
        "purchase_positive": defaultdict(set),
        "strong_positive": defaultdict(set),
        "verified_purchase_any_rating": defaultdict(set),
        "all_positive": defaultdict(set),
    }
    stats: dict[str, Any] = {view: {"row_count": 0, "user_count": 0, "in_dst_universe_count": 0} for view in labels}
    for name in ("canonical_interactions.valid.jsonl", "canonical_interactions.test.jsonl"):
        for row in _iter_jsonl(data_root / name):
            user_id = str(row.get("user_id") or "")
            item_id = str(row.get("parent_asin") or row.get("item_id") or "")
            if not user_id or not item_id:
                continue
            views = []
            label_binary = _as_float(row.get("label_binary")) > 0
            verified_purchase = row.get("verified_purchase") is True
            label_strong = _as_float(row.get("label_strong")) > 0
            if verified_purchase and label_binary:
                views.append("purchase_positive")
            if label_strong:
                views.append("strong_positive")
            if verified_purchase:
                views.append("verified_purchase_any_rating")
            if label_binary:
                views.append("all_positive")
            for view in views:
                labels[view][user_id].add(item_id)
                stats[view]["row_count"] += 1
                stats[view]["in_dst_universe_count"] += int(item_id in dst_universe)
    out_labels = {view: dict(value) for view, value in labels.items()}
    for view, view_labels in out_labels.items():
        stats[view]["user_count"] = len(view_labels)
        stats[view]["in_dst_universe_ratio"] = round(
            stats[view]["in_dst_universe_count"] / max(stats[view]["row_count"], 1), 6
        )
    return out_labels, stats


def _load_item_hotness(data_root: Path) -> dict[str, str]:
    path = data_root / "train_only_governance" / "item_quality_profile.jsonl"
    hotness = {}
    for row in _iter_jsonl(path):
        item_id = str(row.get("parent_asin") or "")
        if item_id:
            hotness[item_id] = str(row.get("hotness_bucket") or "")
    return hotness


def _gen_candidates(
    edges: dict[str, list[tuple[str, float]]], seeds: list[str], seen: set[str], limit: int
) -> tuple[list[tuple[str, float]], bool]:
    best: dict[str, float] = {}
    seed_hit = False
    for seed in seeds:
        rows = edges.get(seed)
        if not rows:
            continue
        seed_hit = True
        for dst, score in rows:
            if dst in seen:
                continue
            if score > best.get(dst, -1.0):
                best[dst] = score
    return sorted(best.items(), key=lambda item: (-item[1], item[0]))[:limit], seed_hit


def _recent_unique(values: Any, window: int) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    raw_values = [str(value) for value in (values or []) if value]
    for value in reversed(raw_values):
        if value in seen:
            continue
        out.append(value)
        seen.add(value)
        if len(out) >= window:
            break
    return list(reversed(out))


def _iter_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                yield json.loads(line)


def _resolve_path(value: Any) -> Path:
    raw = str(value).replace("\\", "/")
    for marker in ("/RS_agent/", "/RS_agent_remote/"):
        if marker in raw:
            raw = raw.split(marker, 1)[1]
            break
    if raw.startswith("D:/"):
        parts = raw.split("/RS_agent/", 1)
        raw = parts[1] if len(parts) == 2 else raw
    path = Path(raw)
    return path if path.is_absolute() else ROOT / path


def _as_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


if __name__ == "__main__":
    main()
