"""可复现的画像对照展示与公式控制；不是模型成绩，也不生成真人标签。"""

import copy

from .customer import customer_reference
from .dataset import fingerprint, validate_benchmark
from .scoring import evaluate_turn, scorer_fingerprint


def formula_reference(catalog, gold):
    if gold["customer_policy"]["action"] in {"clarify", "defer"}:
        return customer_reference(gold)
    diagnostic = evaluate_turn(
        catalog, gold, {"item_ids": [item["item_id"] for item in catalog], "outcome": "recommend"}
    )
    facts = {item["item_id"]: item for item in catalog}
    feasible = sorted(
        (item for item in diagnostic["items"] if item["hard_pass"]),
        key=lambda item: (-item["relevance"], facts[item["item_id"]]["price"], item["item_id"]),
    )
    outcome = diagnostic["expected_outcome"]
    return {
        "item_ids": [item["item_id"] for item in feasible[: diagnostic["required_count"]]],
        "outcome": outcome,
        "message": "公式参考：符合当前条件。"
        if outcome == "recommend"
        else "目前没有可确认符合全部条件的商品。",
        "limitations": ["unknown_attributes"]
        if outcome == "uncertain_match"
        else ["no_matches"]
        if outcome == "no_match"
        else [],
    }


def build_contrast_examples(benchmark, *, limit=3):
    validate_benchmark(benchmark)
    if type(limit) is not int or not 1 <= limit <= 30:
        raise ValueError("展示组数必须为 1..30")
    catalog = benchmark["catalog"]
    facts = {item["item_id"]: item for item in catalog}
    tasks = {task["task_id"]: task for task in benchmark["tasks"]}
    selected, fields = [], set()
    for group in benchmark.get("contrast_groups", []):
        key = (group["spec"]["category"], group["spec"]["field"])
        if group["split"] != "test" and group["kind"] == "authorized" and key not in fields:
            selected.append(group)
            fields.add(key)
        if len(selected) == limit:
            break
    examples = []
    for group in selected:
        members, references, golds = [], [], []
        for task_id in group["task_ids"]:
            task = tasks[task_id]
            gold = task["turns"][0]["gold"]
            answer = formula_reference(catalog, gold)
            references.append(answer)
            golds.append(gold)
            members.append(
                {
                    "task_id": task_id,
                    "family_id": task["family_id"],
                    "profile_user_id": task["profile_user_id"],
                    "customer_message": task["turns"][0]["user_message"],
                    "profile_evidence": copy.deepcopy(gold["customer_policy"]["profile_match"]),
                    "reference_products": [
                        copy.deepcopy(facts[item_id]) for item_id in answer["item_ids"]
                    ],
                }
            )
        matrix = [
            [evaluate_turn(catalog, gold, answer)["task_score"] for answer in references]
            for gold in golds
        ]
        related = []
        for other in benchmark["contrast_groups"]:
            if other["pair_id"] != group["pair_id"] or other["kind"] == "authorized":
                continue
            related.append(
                {
                    "kind": other["kind"],
                    "relation": other["relation"],
                    "members": [
                        {
                            "task_id": task_id,
                            "turns": [
                                {
                                    "customer_message": turn["user_message"],
                                    "reference": formula_reference(catalog, turn["gold"]),
                                    "grade": evaluate_turn(
                                        catalog,
                                        turn["gold"],
                                        formula_reference(catalog, turn["gold"]),
                                    ),
                                }
                                for turn in tasks[task_id]["turns"]
                            ],
                        }
                        for task_id in other["task_ids"]
                    ],
                }
            )
        examples.append(
            {
                "group_id": group["group_id"],
                "split": group["split"],
                "spec": group["spec"],
                "members": members,
                "score_matrix_rows_users_columns_products": matrix,
                "matched_pair_quality": min(matrix[0][0], matrix[1][1]),
                "swapped_pair_quality": min(matrix[0][1], matrix[1][0]),
                "same_product_a_pair_quality": min(row[0] for row in matrix),
                "same_product_b_pair_quality": min(row[1] for row in matrix),
                "related_scenarios": related,
            }
        )
    return {
        "schema_version": "rs-profile-contrast-examples/1",
        "benchmark_sha256": fingerprint(benchmark),
        "scorer_sha256": scorer_fingerprint(),
        "origin": "deterministic_formula_references_and_controls; not_actual_agent_or_human_satisfaction",
        "test_gold_not_exported": True,
        "examples": examples,
    }
