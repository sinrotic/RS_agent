"""自然购物的分层评价：历史证据不是本次需求或真实满意度。"""

import copy
import math
import re
import statistics


def validate_relevance_metadata(gold):
    labels = gold.get("relevance_judgments")
    if labels is None:
        return
    if (
        gold.get("customer_policy", {}).get("evaluation_policy") != "natural-shopping/1"
        or not isinstance(labels, dict)
        or labels.get("origin") != "human"
        or labels.get("status") != "approved"
        or not isinstance(labels.get("reviewer_id"), str)
        or not labels["reviewer_id"].strip()
        or not isinstance(labels.get("rubric"), str)
        or not labels["rubric"].strip()
        or not isinstance(labels.get("catalog_sha256"), str)
        or not isinstance(labels.get("grades"), dict)
        or not labels["grades"]
        or any(
            not isinstance(key, str) or type(grade) is not int or not 0 <= grade <= 3
            for key, grade in labels["grades"].items()
        )
    ):
        raise ValueError("独立相关性需要已批准的人工来源、评审依据和 0–3 分级；不接受模型自评")


def apply_relevance_judgments(catalog, gold, grades):
    from .dataset import fingerprint

    labels = gold.get("relevance_judgments")
    if labels is None:
        return
    if labels["catalog_sha256"] != fingerprint(catalog):
        raise ValueError("独立相关性标签不属于当前冻结目录")
    if set(labels["grades"]) - set(grades) or any(
        item_id not in labels["grades"] for item_id, grade in grades.items() if grade["hard_pass"]
    ):
        raise ValueError("独立相关性须覆盖全部硬条件可行商品；未标注不能默认当负例")
    for item_id, grade in grades.items():
        grade["relevance"] = labels["grades"].get(item_id, 0) if grade["hard_pass"] else 0.0


def evaluate_optional_question(gold, result):
    from .customer import evaluate_customer_interaction

    question_gold = copy.deepcopy(gold)
    question_gold["customer_policy"]["action"] = "clarify"
    grade = evaluate_customer_interaction(question_gold, result)
    grade.update(interaction_action="clarify", clarification_need="optional")
    return grade


def explanation_grade(catalog, gold, result):
    """有限的可审计断言检查，不声称覆盖所有语义或满意度。"""
    text = result.get("message", "")
    claims = []
    clauses = re.split(r"[。！？!?\n]", text)
    for clause in clauses:
        if re.search(
            r"不代表|不能说|无法证明|不能证明|并不|不保证|无法保证|不能保证|不能套用|不会套用|不按|不沿用|不参考",
            clause,
        ):
            continue
        if re.search(
            r"你(?:一直|一贯|总是|肯定|一定|最)(?:喜欢|偏爱|偏好|习惯)|你的(?:固定|稳定|唯一)偏好",
            clause,
        ):
            claims.append("overstated_history_preference")
        if gold["customer_policy"].get(
            "purchase_claim_source"
        ) != "current_customer_statement" and re.search(
            r"你(?:之前|以前|过去|曾经)(?:买过|购买|下单)|你的购买历史", clause
        ):
            claims.append("review_history_presented_as_purchase")
        if (
            gold["customer_policy"]["history_role"] == "disabled"
            and re.search(r"你的(?:历史|习惯|偏好)|你平时|你过去", clause)
            and re.search(r"给家人|给对方|送给|给他|给她", clause)
            and re.search(r"推荐|选择|选这|挑这|偏好", clause)
        ):
            claims.append("misapplied_profile_for_recipient")
        if "compatibility" in gold["customer_policy"].get("unverified_claims", []) and re.search(
            r"保证兼容|肯定兼容|一定兼容|完全兼容|一定适配|保证适配", clause
        ):
            claims.append("unsupported_compatibility_claim")
    facts = {item["item_id"]: item for item in catalog}
    selected = [facts[item_id] for item_id in result.get("item_ids", []) if item_id in facts]
    checked = len(claims)
    for raw in re.findall(r"(?:售价|标价|现价|价格)(?:是|为|约|[:：])?\s*(\d+(?:\.\d+)?)", text):
        if len(selected) == 1:
            checked += 1
            value = selected[0].get("price")
            if value is None or not math.isclose(float(raw), value, abs_tol=0.005):
                claims.append("unsupported_price_claim")
    if any(item.get("currency") == "SOURCE_UNIT" for item in selected) and re.search(
        r"\d+(?:\.\d+)?\s*(?:元|人民币|美元)|[¥$]\s*\d", text
    ):
        checked += 1
        claims.append("unsupported_currency_claim")
    return {
        "checked_claims": checked,
        "error_count": len(claims),
        "error_rate": len(claims) / checked if checked else None,
        "violations": sorted(set(claims)),
        "coverage": "limited_price_currency_history_and_flagged_compatibility_patterns; not_full_semantic_judging",
    }


def decorate_natural_grade(catalog, gold, result, grade):
    policy = gold.get("customer_policy", {})
    if policy.get("evaluation_policy") != "natural-shopping/1":
        return grade
    grade.setdefault("interaction_action", policy["action"])
    grade.setdefault("clarification_need", policy.get("clarification_need", "not_required"))
    grade.setdefault(
        "quality_basis",
        "independent_human_relevance"
        if gold.get("relevance_judgments")
        else "declared_constraints_only",
    )
    grade.setdefault("profile_evidence", profile_evidence_grade(gold, grade["items"]))
    grade["unscored_qualitative_needs"] = (
        policy.get("unscored_qualitative_needs", []) if not gold.get("relevance_judgments") else []
    )
    explanation = explanation_grade(catalog, gold, result)
    grade["explanation"] = explanation
    if explanation["violations"]:
        grade["violations"] = sorted(set(grade["violations"] + explanation["violations"]))
        grade["success"] = False
        grade["task_score"] = 0.0
        if "interaction_score" in grade:
            grade["interaction_score"] = 0.0
    return grade


def profile_evidence_grade(gold, returned):
    policy = gold["customer_policy"]
    match = policy.get("profile_match")
    if match is None or policy["history_role"] != "environment_reference":
        return None
    # returned 是评分投影；属性值从 profile_distribution 投影读取。
    if not returned:
        return None
    scores = [
        (item.get("profile_satisfaction", 0) or 0) if item["hard_pass"] else 0 for item in returned
    ]
    return {
        "score": 100 * match["confidence"] * statistics.mean(scores) if scores else 0.0,
        "known_items": match["known_items"],
        "coverage": match["coverage"],
        "evidence_discount": match["confidence"],
        "strength": "single_positive" if match["known_items"] == 1 else "repeated_positive",
        "used_for_primary_score": False,
        "interpretation": "discounted_history_alignment; not_personal_preference_probability",
    }


def natural_metrics(benchmark, trials, *, split, repeats):
    tasks = [task for task in benchmark["tasks"] if split is None or task["split"] == split]
    grades = [
        turn["grade"]
        for trial in trials
        for turn in trial["turns"]
        if turn["gold"].get("customer_policy", {}).get("evaluation_policy") == "natural-shopping/1"
    ]
    planned_required = repeats * sum(
        turn["gold"].get("customer_policy", {}).get("evaluation_policy") == "natural-shopping/1"
        and turn["gold"]["customer_policy"]["action"] == "clarify"
        for task in tasks
        for turn in task["turns"]
    )
    required = [grade for grade in grades if grade.get("clarification_need") == "required"]
    optional = [
        grade
        for grade in grades
        if grade.get("clarification_need") == "optional"
        and grade.get("interaction_action") == "clarify"
    ]
    violations = {
        "unnecessary_clarification",
        "reasks_known_information",
        "excessive_clarification",
        "irrelevant_personal_information_request",
    }
    evidence = [
        grade["profile_evidence"]["score"] for grade in grades if grade.get("profile_evidence")
    ]
    explanations = [grade["explanation"] for grade in grades if "explanation" in grade]
    checked = sum(item["checked_claims"] for item in explanations)
    labeled = [
        grade
        for grade in grades
        if grade["ranking_applicable"]
        and grade.get("quality_basis") == "independent_human_relevance"
    ]
    return {
        "required_clarification_turns": planned_required,
        "required_clarification_success_rate": sum(grade["success"] for grade in required)
        / planned_required
        if planned_required
        else None,
        "optional_clarification_turns": len(optional),
        "optional_clarification_success_rate": sum(grade["success"] for grade in optional)
        / len(optional)
        if optional
        else None,
        "unnecessary_question_turns": sum(
            bool(set(grade["violations"]) & violations) for grade in grades
        ),
        "unnecessary_question_rate": sum(
            bool(set(grade["violations"]) & violations) for grade in grades
        )
        / len(grades)
        if grades
        else None,
        "independent_quality_turns": len(labeled),
        "constraint_only_ranking_turns": sum(
            grade["ranking_applicable"]
            and grade.get("quality_basis") == "declared_constraints_only"
            for grade in grades
        ),
        "mean_history_evidence_score": statistics.mean(evidence) if evidence else None,
        "history_evidence_used_for_primary_or_promotion": False,
        "checked_explanation_claims": checked,
        "explanation_error_rate_on_checked_claims": sum(
            item["error_count"] for item in explanations
        )
        / checked
        if checked
        else None,
        "explanation_coverage": "limited_rule_projection; no_full_semantic_quality_claim",
        "personalization_quality_status": "independent_labels_available"
        if labeled
        else "pending_independent_relevance; history_alignment_is_not_quality_gain",
    }
