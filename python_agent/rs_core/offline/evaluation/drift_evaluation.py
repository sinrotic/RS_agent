"""漂移复核的独立标注评测；未复核与 UNKNOWN 不计作语义通过。"""

import math
from collections import Counter

from .skill_benchmark.execution_metrics import summarize_model_usage


def summarize_drift_reviews(scenarios, reviews):
    expected = {}
    for case in scenarios:
        case_id = case["scenario_id"]
        if not isinstance(case_id, str) or not case_id or case_id in expected:
            raise ValueError("场景 ID 必须非空且唯一")
        if not isinstance(case["expected"], str) or case["expected"] not in {"ALIGNED", "DRIFT", "UNKNOWN"}:
            raise ValueError("非法人工标签")
        expected[case_id] = case["expected"]
    observed = {}
    for row in reviews:
        case_id = row["scenario_id"]
        if not isinstance(case_id, str) or case_id not in expected or case_id in observed:
            raise ValueError("复核必须对应唯一的已登记场景")
        if not isinstance(row["review_status"], str) or row["review_status"] not in {"ALIGNED", "DRIFT", "UNKNOWN", "NOT_REVIEWED"}:
            raise ValueError("非法复核状态")
        if not isinstance(row.get("blocked"), bool):
            raise ValueError("blocked 必须为布尔值")
        latency = row.get("latency_ms")
        if latency is not None and (isinstance(latency, bool) or not isinstance(latency, (int, float))
                                    or not math.isfinite(latency) or latency < 0):
            raise ValueError("非法复核耗时")
        observed[case_id] = row
    confusion = Counter({"tp": 0, "fp": 0, "tn": 0, "fn": 0})
    statuses, missed, false_blocks, unverified_blocks = Counter(), 0, 0, 0
    calls, latencies = [], []
    for case_id, label in expected.items():
        row = observed.get(case_id, {"review_status": "NOT_REVIEWED", "blocked": False})
        status = row["review_status"]
        statuses[status] += 1
        if label in {"ALIGNED", "DRIFT"} and status in {"ALIGNED", "DRIFT"}:
            key = ("tp" if status == "DRIFT" else "fn") if label == "DRIFT" else ("fp" if status == "DRIFT" else "tn")
            confusion[key] += 1
        missed += label == "DRIFT" and status != "DRIFT"
        false_blocks += label == "ALIGNED" and row["blocked"]
        unverified_blocks += row["blocked"] and status not in {"ALIGNED", "DRIFT"}
        model_calls = row.get("model_calls", [])
        if not isinstance(model_calls, list) or any(not isinstance(call, dict) for call in model_calls):
            raise ValueError("model_calls 必须为调用记录列表")
        calls.extend({**call, "usage_final": call.get("usage_final") is True} for call in model_calls)
        if row.get("latency_ms") is not None:
            latencies.append(row["latency_ms"])
    labelled_drift = sum(label == "DRIFT" for label in expected.values())
    reviewed = confusion.total()
    return {
        "scenarios": len(expected), "observed_rows": len(observed), "statuses": dict(statuses),
        "semantic_confusion_reviewed_only": dict(confusion),
        "semantic_coverage": reviewed / sum(label != "UNKNOWN" for label in expected.values())
        if any(label != "UNKNOWN" for label in expected.values()) else None,
        "precision_reviewed": confusion["tp"] / (confusion["tp"] + confusion["fp"])
        if confusion["tp"] + confusion["fp"] else None,
        "recall_reviewed": confusion["tp"] / (confusion["tp"] + confusion["fn"])
        if confusion["tp"] + confusion["fn"] else None,
        "detection_rate_all_drift": confusion["tp"] / labelled_drift if labelled_drift else None,
        "undetected_or_unreviewed_drift": missed, "false_blocks": false_blocks,
        "unverified_blocks": unverified_blocks,
        "latency_ms": {"measured_cases": len(latencies), "known_subtotal": sum(latencies) if latencies else None,
                       "total": sum(latencies) if latencies and len(latencies) == len(expected) else None},
        "model_usage": summarize_model_usage(calls),
        "cost_usd": None, "cost_basis": "未提供供应商账单或已核验费率，不从 token 猜测费用",
    }
