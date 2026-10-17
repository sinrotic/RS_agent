"""独立相关性标注入口：空白人审模板与显式导入，不自动制造个人喜好真值。"""

import copy

from .dataset import fingerprint, validate_benchmark
from .scoring import evaluate_turn


def build_relevance_review(benchmark, *, task_limit=40):
    validate_benchmark(benchmark)
    if type(task_limit) is not int or task_limit < 1:
        raise ValueError("标注任务数必须为正整数")
    candidates = sorted(
        (
            task
            for task in benchmark["tasks"]
            if task["split"] != "test"
            and task["turns"][0]["gold"].get("customer_policy", {}).get("evaluation_policy")
            == "natural-shopping/1"
            and task["turns"][0]["gold"]["customer_policy"]["action"]
            in {"recommend", "recommend_or_clarify"}
        ),
        key=lambda task: (
            task["kind"] != "profile_contrast_implicit_profile",
            task["split"] != "dev",
            task["family_id"],
            task["task_id"],
        ),
    )
    selected, seen = [], set()
    for task in candidates:
        if task["family_id"] not in seen:
            selected.append(task)
            seen.add(task["family_id"])
    selected_ids = {task["task_id"] for task in selected}
    selected = (selected + [task for task in candidates if task["task_id"] not in selected_ids])[
        :task_limit
    ]
    catalog = benchmark["catalog"]
    entries = []
    for task in selected:
        diagnostic = evaluate_turn(
            catalog,
            task["turns"][0]["gold"],
            {
                "item_ids": [item["item_id"] for item in catalog],
                "outcome": "recommend",
            },
        )
        feasible = {grade["item_id"] for grade in diagnostic["items"] if grade["hard_pass"]}
        if not feasible:
            continue
        entries.append(
            {
                "task_id": task["task_id"],
                "turn_index": 0,
                "split": task["split"],
                "family_id": task["family_id"],
                "customer_messages": [task["turns"][0]["user_message"]],
                "profile": copy.deepcopy(benchmark["profiles"][task["profile_user_id"]]),
                "candidate_facts": [
                    copy.deepcopy(item) for item in catalog if item["item_id"] in feasible
                ],
                "grades": {item_id: None for item_id in sorted(feasible)},
                "reasons": {item_id: None for item_id in sorted(feasible)},
                "approved": False,
                "reviewer_id": None,
                "rubric": None,
            }
        )
    return {
        "schema_version": "rs-independent-relevance-review/1",
        "origin": "human",
        "benchmark_sha256": fingerprint(benchmark),
        "catalog_sha256": fingerprint(catalog),
        "test_gold_not_exported": True,
        "instructions": (
            "从当前顾客需求、可核实商品事实与相关的弱历史证据，独立给每款合格商品标 0–3 级并说明理由。"
            "0=不适合，1=勉强可接受，2=合理，3=相对更适合；允许并列。分级锚点须在 rubric 中解释。"
            "未交互不等于不喜欢；单次正向评价不能变成本次隐藏硬需求；评审合理性不是实际顾客满意度。"
            "信息不足、事实或场景不合理时不要批准；保持空白并另行修正，不把未标注商品默认当0。"
            "逐项完成后填写 reviewer_id、rubric、reasons，再显式批准；不得让被测Agent自己填入并批准。"
        ),
        "entries": entries,
    }


def apply_relevance_review(benchmark, review):
    validate_benchmark(benchmark)
    if (
        review.get("schema_version") != "rs-independent-relevance-review/1"
        or review.get("origin") != "human"
        or review.get("benchmark_sha256") != fingerprint(benchmark)
        or review.get("catalog_sha256") != fingerprint(benchmark["catalog"])
    ):
        raise ValueError("独立人审不属于当前冻结题集或目录")
    result = copy.deepcopy(benchmark)
    tasks = {task["task_id"]: task for task in result["tasks"]}
    used, approved = set(), 0
    for entry in review.get("entries", []):
        if entry.get("approved") is not True:
            continue
        key = entry.get("task_id"), entry.get("turn_index")
        task = tasks.get(key[0])
        if (
            key in used
            or task is None
            or type(key[1]) is not int
            or not 0 <= key[1] < len(task["turns"])
        ):
            raise ValueError("独立标注的任务缺失、轮次无效或重复")
        used.add(key)
        judgments = entry.get("grades", {})
        reasons = entry.get("reasons", {})
        if (
            not isinstance(judgments, dict)
            or not isinstance(reasons, dict)
            or any(
                not isinstance(reasons.get(item_id), str) or not reasons[item_id].strip()
                for item_id in judgments
            )
        ):
            raise ValueError("每项批准的相关性分级都需要独立评审理由")
        turn = task["turns"][key[1]]
        turn["gold"]["relevance_judgments"] = {
            "origin": "human",
            "status": "approved",
            "reviewer_id": entry.get("reviewer_id"),
            "rubric": entry.get("rubric"),
            "catalog_sha256": review["catalog_sha256"],
            "grades": copy.deepcopy(judgments),
            "reasons": copy.deepcopy(reasons),
        }
        evaluate_turn(
            result["catalog"], turn["gold"], {"item_ids": [], "outcome": "invalid_output"}
        )
        approved += 1
    if not approved:
        raise ValueError("没有已批准的独立人工相关性标签，拒绝输出伪校准版本")
    ranked = [
        turn
        for task in result["tasks"]
        for turn in task["turns"]
        if turn["gold"]["customer_policy"]["action"] in {"recommend", "recommend_or_clarify"}
    ]
    result["manifest"].update(
        parent_benchmark_sha256=fingerprint(benchmark),
        relevance_review_sha256=fingerprint(review),
        independent_relevance_status="complete_human_labels"
        if all(turn["gold"].get("relevance_judgments") for turn in ranked)
        else "partial_human_labels",
        human_reviewed=False,
        scoring_calibration={"status": "pending_recalibration_after_label_import", "passed": False},
    )
    validate_benchmark(result)
    return result
