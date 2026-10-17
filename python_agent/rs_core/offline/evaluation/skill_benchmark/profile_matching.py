"""按当前类目隔离的行为画像匹配；置信度折扣，不把单次交互当稳定喜好。"""

from collections import Counter
import statistics


MATCH_VERSION = "category-scoped-positive-history/1"
MATCH_FIELDS = {"connection_type", "tip_mm", "store"}


def build_profile_match(profile, category, path, field):
    if field not in MATCH_FIELDS:
        raise ValueError("不支持的画像匹配属性")
    events = {
        event["parent_asin"]: event
        for event in profile["history"]
        if event.get("item", {}).get("category") == category
        and event["item"].get("category_path") == path
    }
    known = [event for event in events.values() if event["item"].get(field) is not None]
    counts = Counter(str(event["item"][field]) for event in known)
    if not counts:
        return None
    n, total = len(known), len(events)
    return {
        "version": MATCH_VERSION,
        "category": category,
        "category_path": path,
        "field": field,
        "counts": dict(sorted(counts.items())),
        "distribution": {key: count / n for key, count in sorted(counts.items())},
        "known_items": n,
        "relevant_items": total,
        "coverage": n / total,
        "confidence": n / (n + 2) * n / total,
        "evidence": [
            {
                "item_id": event["parent_asin"],
                "timestamp": event["timestamp"],
                "value": str(event["item"][field]),
            }
            for event in sorted(known, key=lambda event: event["parent_asin"])
        ],
        "interpretation": "positive_interaction_proxy; not_observed_customer_satisfaction",
    }


def validate_profile_match(match):
    if (
        not isinstance(match, dict)
        or match.get("version") != MATCH_VERSION
        or match.get("field") not in MATCH_FIELDS
        or not isinstance(match.get("category"), str)
        or not isinstance(match.get("category_path"), list)
    ):
        raise ValueError("无效类目内画像匹配规则")
    counts = match.get("counts")
    n, total = match.get("known_items"), match.get("relevant_items")
    if (
        not isinstance(counts, dict)
        or not counts
        or type(n) is not int
        or type(total) is not int
        or not 0 < n <= total
        or any(
            not isinstance(key, str) or type(value) is not int or value <= 0
            for key, value in counts.items()
        )
        or sum(counts.values()) != n
        or match.get("distribution") != {key: value / n for key, value in counts.items()}
        or match.get("coverage") != n / total
        or match.get("confidence") != n / (n + 2) * n / total
        or not isinstance(match.get("evidence"), list)
        or len(match["evidence"]) != n
    ):
        raise ValueError("画像匹配计数、分布或置信度不一致")


def profile_satisfaction(item, match):
    value = item.get(match["field"])
    return match["distribution"].get(str(value), 0.0) if value is not None else 0.0


def needs_preference_confirmation(match):
    return (
        match is None
        or match["known_items"] < 2
        or match["coverage"] < 2 / 3
        or max(match["distribution"].values()) < 2 / 3
    )


def contrast_metrics(benchmark, trials, *, split, repeats):
    """计划对照组作分母；缺一侧、任一侧失败均记零，不能用随机不同 ID 得分。"""
    indexed = {(trial["task_id"], trial["repeat"]): trial for trial in trials}
    tasks = {task["task_id"]: task for task in benchmark["tasks"]}
    groups = [
        group
        for group in benchmark.get("contrast_groups", [])
        if split is None or group["split"] == split
    ]
    rows = []
    for group in groups:
        for repeat in range(repeats):
            members = [indexed.get((task_id, repeat)) for task_id in group["task_ids"]]
            ranking_applicable = any(
                turn["gold"].get("customer_policy", {}).get("action") not in {"clarify", "defer"}
                for task_id in group["task_ids"]
                for turn in tasks[task_id]["turns"]
            )
            values = [
                trial["ranking_score"]
                if trial is not None and trial["success"] and trial["ranking_score"] is not None
                else 0.0
                for trial in members
            ]
            rows.append(
                {
                    "group_id": group["group_id"],
                    "kind": group["kind"],
                    "repeat": repeat,
                    "complete": all(
                        trial is not None and trial.get("dialogue_complete", True)
                        for trial in members
                    ),
                    "paired_quality": min(values) if ranking_applicable else None,
                    "ranking_applicable": ranking_applicable,
                    "paired_success": all(
                        trial is not None
                        and trial["success"]
                        and trial.get("dialogue_complete", True)
                        for trial in members
                    ),
                    "member_scores": values,
                    "member_history_evidence_scores": [
                        trial.get("profile_evidence_score") if trial is not None else None
                        for trial in members
                    ],
                    "both_full_match": all(value >= 99.999 for value in values)
                    if ranking_applicable
                    else None,
                }
            )
    return {
        "planned_group_trials": len(rows),
        "mean_paired_quality": statistics.mean(
            row["paired_quality"] for row in rows if row["ranking_applicable"]
        )
        if any(row["ranking_applicable"] for row in rows)
        else None,
        "both_full_match_rate": statistics.mean(
            row["both_full_match"] for row in rows if row["ranking_applicable"]
        )
        if any(row["ranking_applicable"] for row in rows)
        else None,
        "paired_success_rate": statistics.mean(row["paired_success"] for row in rows)
        if rows
        else None,
        "incomplete_group_trials": sum(not row["complete"] for row in rows),
        "by_kind": {
            kind: {
                "group_trials": len(selected),
                "mean_paired_quality": statistics.mean(
                    row["paired_quality"] for row in selected if row["ranking_applicable"]
                )
                if any(row["ranking_applicable"] for row in selected)
                else None,
                "both_full_match_rate": statistics.mean(
                    row["both_full_match"] for row in selected if row["ranking_applicable"]
                )
                if any(row["ranking_applicable"] for row in selected)
                else None,
                "paired_success_rate": statistics.mean(row["paired_success"] for row in selected),
            }
            for kind in sorted({row["kind"] for row in rows})
            if (selected := [row for row in rows if row["kind"] == kind])
        },
        "groups": rows,
        "different_item_ids_alone_receive_no_reward": True,
    }
