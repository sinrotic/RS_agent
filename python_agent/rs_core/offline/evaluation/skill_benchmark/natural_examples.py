"""自然画像对照的实际商品与受控路径展示；不宣称真实模型输出或满意度。"""

import copy

from .contrast_examples import formula_reference
from .customer import customer_reference
from .dataset import fingerprint, validate_benchmark
from .scoring import evaluate_turn, scorer_fingerprint


def evidence_reference(catalog, gold):
    """为展示选取历史属性较匹配的合格款；历史排序不充当质量裁判。"""
    if gold["customer_policy"]["action"] in {"clarify", "defer"}:
        return customer_reference(gold)
    diagnostic = evaluate_turn(
        catalog,
        gold,
        {
            "item_ids": [item["item_id"] for item in catalog],
            "outcome": "recommend",
        },
    )
    facts = {item["item_id"]: item for item in catalog}
    feasible = sorted(
        (grade for grade in diagnostic["items"] if grade["hard_pass"]),
        key=lambda grade: (
            -(grade.get("profile_satisfaction") or 0),
            -grade["relevance"],
            facts[grade["item_id"]]["price"],
            grade["item_id"],
        ),
    )
    if not feasible:
        return formula_reference(catalog, gold)
    return {
        "item_ids": [grade["item_id"] for grade in feasible[: diagnostic["required_count"]]],
        "outcome": "recommend",
        "message": "先给一款符合当前条件的参考；尚未确认的信息不能保证。"
        if gold["customer_policy"]["history_role"] == "disabled"
        else "先给一款符合当前条件的参考；历史记录只作弱参考。",
        "limitations": [],
    }


def _paths(catalog, task):
    first = task["turns"][0]
    paths = []
    optional = first["gold"]["customer_policy"]["action"] == "recommend_or_clarify"
    if optional:
        answer = evidence_reference(catalog, first["gold"])
        paths.append(
            {
                "path": "direct_reference",
                "turns": [
                    {
                        "customer_message": first["user_message"],
                        "reference": answer,
                        "grade": evaluate_turn(catalog, first["gold"], answer),
                    }
                ],
                "future_reply_released": False,
            }
        )
    answers = []
    for index, turn in enumerate(task["turns"]):
        gold = turn["gold"]
        answer = (
            customer_reference(gold)
            if optional and index == 0
            else evidence_reference(catalog, gold)
        )
        answers.append(
            {
                "customer_message": turn["user_message"],
                "reference": answer,
                "grade": evaluate_turn(catalog, gold, answer),
            }
        )
    paths.append(
        {
            "path": "question_then_reply" if optional else "required_path",
            "turns": answers,
            "future_reply_released": len(answers) > 1,
        }
    )
    return paths


def build_natural_examples(benchmark, *, limit=3):
    validate_benchmark(benchmark)
    if type(limit) is not int or not 1 <= limit <= 30:
        raise ValueError("展示组数必须为 1..30")
    catalog = benchmark["catalog"]
    facts = {item["item_id"]: item for item in catalog}
    tasks = {task["task_id"]: task for task in benchmark["tasks"]}
    chosen, fields = [], set()
    for group in benchmark.get("contrast_groups", []):
        key = group["spec"]["category"], group["spec"]["field"]
        if group["kind"] == "implicit_profile" and group["split"] != "test" and key not in fields:
            chosen.append(group)
            fields.add(key)
        if len(chosen) == limit:
            break
    examples = []
    for group in chosen:
        members, golds, references = [], [], []
        for task_id in group["task_ids"]:
            task = tasks[task_id]
            gold = task["turns"][0]["gold"]
            reference = evidence_reference(catalog, gold)
            golds.append(gold)
            references.append(reference)
            members.append(
                {
                    "task_id": task_id,
                    "family_id": task["family_id"],
                    "profile_user_id": task["profile_user_id"],
                    "customer_message": task["turns"][0]["user_message"],
                    "profile_evidence": copy.deepcopy(gold["customer_policy"].get("profile_match")),
                    "reference_products": [
                        copy.deepcopy(facts[item_id]) for item_id in reference["item_ids"]
                    ],
                    "allowed_paths": _paths(catalog, task),
                }
            )
        grades = [
            [evaluate_turn(catalog, gold, reference) for reference in references] for gold in golds
        ]
        related = [
            {
                "kind": other["kind"],
                "relation": other["relation"],
                "members": [
                    {"task_id": task_id, "allowed_paths": _paths(catalog, tasks[task_id])}
                    for task_id in other["task_ids"]
                ],
            }
            for other in benchmark["contrast_groups"]
            if other["pair_id"] == group["pair_id"] and other["kind"] != "implicit_profile"
        ]
        examples.append(
            {
                "group_id": group["group_id"],
                "split": group["split"],
                "spec": group["spec"],
                "members": members,
                "current_request_score_matrix": [
                    [grade["task_score"] for grade in row] for row in grades
                ],
                "history_evidence_score_matrix": [
                    [
                        grade["profile_evidence"]["score"]
                        if grade.get("profile_evidence")
                        else None
                        for grade in row
                    ]
                    for row in grades
                ],
                "independent_quality_status": "pending_human_labels"
                if not any(gold.get("relevance_judgments") for gold in golds)
                else "independent_labels_available",
                "related_scenarios": related,
            }
        )
    return {
        "schema_version": "rs-natural-profile-examples/1",
        "benchmark_sha256": fingerprint(benchmark),
        "scorer_sha256": scorer_fingerprint(),
        "test_gold_not_exported": True,
        "origin": "real_catalog_and_past_profiles; synthetic_customer_scenes; controlled_references_not_model_outputs",
        "history_evidence_not_primary_quality": True,
        "examples": examples,
    }
