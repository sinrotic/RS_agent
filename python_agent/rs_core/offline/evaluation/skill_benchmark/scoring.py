"""独立公式评分：三值硬约束、加权效用、完整列表门控及冻结目录 NDCG。"""

import math
import hashlib
from pathlib import Path

from .dataset import validate_gold


def scorer_fingerprint():
    """包含推荐评分、会话评价和 gold 校验，防止只冻结外层评分入口。"""
    digest = hashlib.sha256()
    for name in (
        "scoring.py",
        "customer.py",
        "dataset.py",
        "profile_matching.py",
        "catalog_curation.py",
        "natural.py",
        "environment.py",
        "quality_dataset.py",
        "quality_scoring.py",
        "quality_review.py",
        "quality_evidence.py",
    ):
        digest.update(name.encode("utf-8"))
        digest.update(Path(__file__).with_name(name).read_bytes())
    return digest.hexdigest()


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _check(item, criterion):
    value = item.get(criterion["field"])
    if value is None:
        return None
    op, expected = criterion["op"], criterion.get("value")
    if op == "eq":
        if isinstance(expected, bool) and not isinstance(value, bool):
            return None
        return value == expected
    if op == "not_in":
        return value not in expected
    if op == "in":
        return value in expected
    if op in {"lte", "gte"}:
        if not _number(value):
            return None
        return value <= expected if op == "lte" else value >= expected
    raise ValueError(f"不支持的硬约束: {op}")


def _item_grade(item, gold):
    checks = [_check(item, criterion) for criterion in gold["hard"]]
    soft = gold.get("soft", [])
    total_weight = sum(criterion["weight"] for criterion in soft)
    utility, observed_weight = 0.0, 0.0
    for criterion in soft:
        value = item.get(criterion["field"])
        if value is None:
            continue
        if criterion["op"] == "eq":
            satisfaction = float(value == criterion["value"])
        elif criterion["op"] == "lookup":
            if not isinstance(value, str):
                continue
            satisfaction = criterion["scores"].get(value, 0.0)
        else:
            if not _number(value):
                continue
            satisfaction = (value - criterion["worst"]) / (criterion["best"] - criterion["worst"])
            satisfaction = min(1.0, max(0.0, satisfaction))
        observed_weight += criterion["weight"]
        utility += criterion["weight"] * satisfaction
    utility = utility / total_weight if soft else 1.0
    if "customer_policy" in gold and soft:
        # 明确软偏好只是排序奖励；其他已满足硬要求的商品仍有基础相关性。
        utility = (1.0 + utility) / 2.0
    match = gold.get("customer_policy", {}).get("profile_match")
    profile_match_score = None
    if match is not None:
        from .profile_matching import profile_satisfaction

        profile_match_score = profile_satisfaction(item, match)
    if match is not None and gold["customer_policy"]["history_role"] == "authorized_reference":
        # 基础合格性始终保留；历史样本少、属性缺失多时，个性化奖励自动减弱。
        utility = 1.0 + match["confidence"] * profile_match_score
    hard_pass = all(check is True for check in checks)
    return {
        "item_id": item["item_id"],
        "hard_checks": checks,
        "hard_pass": hard_pass,
        "potentially_feasible": False not in checks,
        "utility": utility,
        "relevance": utility if hard_pass else 0.0,
        "soft_coverage": observed_weight / total_weight if soft else 1.0,
        "profile_satisfaction": profile_match_score,
    }


def _dcg(relevances):
    return sum(value / math.log2(index + 2) for index, value in enumerate(relevances))


def evaluate_turn(catalog, gold, result):
    """输入可信 Catalog Item、当前 Turn gold 与 Agent 结果；返回分数和失败证据。"""
    validate_gold(gold)
    from .natural import decorate_natural_grade

    ids = result.get("item_ids", [])
    if not isinstance(ids, list) or any(
        not isinstance(item_id, str) or not item_id for item_id in ids
    ):
        raise ValueError("item_ids 必须为非空字符串组成的列表")
    if not isinstance(result.get("message", ""), str) or not isinstance(
        result.get("limitations", []), list
    ):
        raise ValueError("无效结果 message/limitations")
    if len({item["item_id"] for item in catalog}) != len(catalog):
        raise ValueError("目录包含重复 item_id")
    if gold.get("customer_policy", {}).get("action") in {"clarify", "defer"}:
        from .customer import evaluate_customer_interaction

        return decorate_natural_grade(
            catalog, gold, result, evaluate_customer_interaction(gold, result)
        )
    if gold.get("customer_policy", {}).get("action") == "recommend_or_clarify" and not ids:
        from .natural import evaluate_optional_question

        return decorate_natural_grade(
            catalog, gold, result, evaluate_optional_question(gold, result)
        )
    grades = {item["item_id"]: _item_grade(item, gold) for item in catalog}
    from .natural import apply_relevance_judgments

    apply_relevance_judgments(catalog, gold, grades)
    quality_labels = gold.get("quality_judgments", {}).get("use_fit")
    feasible = [grade for grade in grades.values() if grade["hard_pass"]
                and (not quality_labels or quality_labels.get(grade["item_id"], {}).get("grade", 0) > 0)]
    potential = [grade for grade in grades.values() if grade["potentially_feasible"]
                 and (not quality_labels or not grade["hard_pass"])]
    expected = "recommend" if feasible else "uncertain_match" if potential else "no_match"
    count = min(gold["k"], len(feasible))
    violations, returned, gains, seen = [], [], [], set()
    if result.get("status", "ok") != "ok":
        violations.append("execution_failed")
    if result.get("outcome") != expected:
        violations.append("wrong_outcome")
    if len(ids) != count:
        violations.append("wrong_count")
    required_limitation = (
        "no_matches"
        if expected == "no_match"
        else "unknown_attributes"
        if expected == "uncertain_match"
        else "insufficient_matches"
        if count < gold["k"]
        else None
    )
    if required_limitation and (
        required_limitation not in result.get("limitations", [])
        or not result.get("message", "").strip()
    ):
        violations.append("missing_limitation_explanation")
    for item_id in ids:
        grade = grades.get(item_id)
        unique = item_id not in seen
        seen.add(item_id)
        if "observed_item_ids" in result and item_id not in result["observed_item_ids"]:
            violations.append("unobserved_item")
        if not unique:
            violations.append("duplicate_item")
        if grade is None:
            violations.append("unknown_item")
            gains.append(0.0)
            returned.append({"item_id": item_id, "hard_pass": False})
        else:
            if not grade["hard_pass"]:
                violations.append("hard_constraint_failed")
            if quality_labels and quality_labels.get(item_id, {}).get("grade") == 0:
                violations.append("independently_labelled_unsuitable_item")
            gains.append(grade["relevance"] if unique else 0.0)
            returned.append(grade)
    idcg = _dcg(sorted((grade["relevance"] for grade in feasible), reverse=True)[: gold["k"]])
    ndcg = _dcg(gains[: gold["k"]]) / idcg if idcg > 0 else None
    success = not violations
    output = {
        "success": success,
        "task_score": 100.0 * ndcg if success and ndcg is not None else 0.0,
        "ndcg": ndcg,
        "idcg": idcg,
        "ranking_applicable": idcg > 0,
        "expected_outcome": expected,
        "required_count": count,
        "feasible_count": len(feasible),
        "potentially_feasible_count": len(potential),
        "violations": sorted(set(violations)),
        "items": returned,
    }
    if "customer_policy" in gold:
        from .customer import history_alignment, recommendation_interaction_violations

        output["history_alignment"] = history_alignment(catalog, gold, result)
        output["violations"].extend(recommendation_interaction_violations(gold, result))
        output["success"] = not output["violations"]
        if not output["success"]:
            output["task_score"] = 0.0
        if gold["customer_policy"].get("evaluation_policy") == "natural-shopping/1":
            from .natural import profile_evidence_grade

            output["quality_basis"] = (
                "independent_human_relevance"
                if gold.get("relevance_judgments")
                else "declared_constraints_only"
            )
            output["profile_evidence"] = profile_evidence_grade(gold, returned)
            output["interaction_action"] = "recommend"
            output["clarification_need"] = gold["customer_policy"].get(
                "clarification_need", "not_required"
            )
    return decorate_natural_grade(catalog, gold, result, output)
