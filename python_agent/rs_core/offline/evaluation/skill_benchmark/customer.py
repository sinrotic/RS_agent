"""顾客任务与可审计会话评价；历史匹配只提供诊断，不代理真人满意度。"""

import re
import statistics


SLOT_ALIASES = {
    "budget": ("预算", "多少钱", "价格上限", "花多少", "价位"),
    "recipient_need": (
        "送给谁",
        "给谁",
        "送谁",
        "用途",
        "需要什么",
        "想要什么",
        "喜欢什么",
        "什么类型",
        "哪类",
        "年龄",
        "送什么",
    ),
    "device": ("型号", "接口", "尺寸", "主板", "设备"),
    "category": ("什么商品", "买什么", "类别", "类目"),
    "quantity": ("几个", "多少件", "数量", "几件"),
    "profile_preference": ("习惯", "偏好", "还是", "有线", "无线", "笔尖", "哪家", "哪一家"),
}


def validate_customer_policy(gold):
    policy = gold.get("customer_policy")
    if policy is None:
        return
    if not isinstance(policy, dict) or policy.get("action") not in {
        "recommend",
        "clarify",
        "defer",
        "recommend_or_clarify",
    }:
        raise ValueError("无效顾客会话策略")
    if policy.get("history_role") not in {
        "weak_reference",
        "disabled",
        "authorized_reference",
        "environment_reference",
    }:
        raise ValueError("历史偏好只能作弱参考、顾客授权的类目内参考或禁用")
    match = policy.get("profile_match")
    if policy.get("history_role") == "authorized_reference":
        from .profile_matching import validate_profile_match

        validate_profile_match(match)
        if (
            policy.get("history_authorization") != "current_customer_request"
            or policy["action"] != "recommend"
            or gold.get("soft")
            or not any(
                c == {"field": "category", "op": "eq", "value": match["category"]}
                for c in gold.get("hard", [])
            )
            or not any(
                c == {"field": "category_path", "op": "eq", "value": match["category_path"]}
                for c in gold.get("hard", [])
            )
        ):
            raise ValueError("画像主分必须有当前顾客授权、当前类目范围，不能混入其他软权重")
    elif policy.get("history_role") == "environment_reference":
        from .profile_matching import validate_profile_match

        validate_profile_match(match)
        if (
            policy.get("history_authorization") != "bound_profile_permission"
            or policy.get("evaluation_policy") != "natural-shopping/1"
            or not any(
                c == {"field": "category", "op": "eq", "value": match["category"]}
                for c in gold.get("hard", [])
            )
            or not any(
                c == {"field": "category_path", "op": "eq", "value": match["category_path"]}
                for c in gold.get("hard", [])
            )
        ):
            raise ValueError("自然画像参考必须来自环境权限且局限当前类目；不是隐藏硬需求")
    elif match is not None:
        raise ValueError("没有当前顾客授权时，画像不能参与主分")
    if any(criterion.get("op") == "lookup" for criterion in gold.get("soft", [])):
        raise ValueError("顾客主分不能混入历史偏好映射")
    if policy["action"] == "recommend_or_clarify" and (
        policy.get("evaluation_policy") != "natural-shopping/1"
        or policy.get("clarification_need") != "optional"
    ):
        raise ValueError("可选澄清必须明确是自然购物低风险问题，不能绕过必要信息")
    if policy["action"] in {"clarify", "recommend_or_clarify"}:
        required, known = policy.get("required_slots"), policy.get("known_slots", [])
        if (
            not isinstance(required, list)
            or not required
            or not isinstance(known, list)
            or any(slot not in SLOT_ALIASES for slot in required + known)
            or set(required) & set(known)
            or type(policy.get("max_questions")) is not int
            or not 1 <= policy["max_questions"] <= 3
        ):
            raise ValueError("澄清必须针对尚未提供的关键字段")
        if "profile_preference" in required and policy.get("clarification_field") not in {
            "tip_mm",
            "connection_type",
            "store",
        }:
            raise ValueError("画像澄清必须指定需要核实的商品属性")


def evaluate_customer_interaction(gold, result):
    """只检查可见问题/指导，拒绝 Agent 自报的 asked_slots 作为证据。"""
    policy = gold["customer_policy"]
    message = result.get("message", "")
    questions = result.get("questions", [])
    if not isinstance(questions, list) or any(
        not isinstance(question, str) for question in questions
    ):
        raise ValueError("问题投影必须为字符串列表")
    clauses = [
        text.strip()
        for text in re.split(r"[，,；;？?。\n]", "\n".join(questions) if questions else message)
        if text.strip()
        and (
            questions or re.search(r"多少|什么|哪|是否|吗|呢|还是|要多|请提供|告诉|方便|能否", text)
        )
    ]
    asked = {
        slot
        for slot, aliases in SLOT_ALIASES.items()
        if any(any(alias in clause for alias in aliases) for clause in clauses)
    }
    if policy.get("evaluation_policy") == "natural-shopping/1" and "recipient_need" in policy.get(
        "required_slots", []
    ):
        field_words = {
            "tip_mm": ("笔尖", "粗细", "细字", "粗字", "毫米", "mm"),
            "connection_type": ("有线", "无线", "连接方式"),
            "store": ("品牌", "店铺", "哪家"),
        }.get(policy.get("clarification_field"), ())
        if any(word in clause for word in field_words for clause in clauses):
            asked.add("recipient_need")
            asked.discard("profile_preference")
    violations = []
    if result.get("status", "ok") != "ok":
        violations.append("execution_failed")
    if result.get("item_ids"):
        violations.append("premature_recommendation")
    if result.get("outcome") not in {"uncertain_match", "clarify"}:
        violations.append("wrong_outcome")
    if policy["action"] == "clarify":
        if set(policy["required_slots"]) - asked:
            violations.append("missing_required_clarification")
        if "profile_preference" in policy["required_slots"]:
            aliases = {
                "tip_mm": ("笔尖", "粗细", "毫米", "mm"),
                "connection_type": ("有线", "无线", "连接方式"),
                "store": ("哪家", "哪一家", "店铺", "品牌"),
            }[policy["clarification_field"]]
            if not any(alias in clause for clause in clauses for alias in aliases):
                violations.append("missing_specific_preference_question")
        if asked & set(policy.get("known_slots", [])):
            violations.append("reasks_known_information")
        if len(clauses) > policy["max_questions"] or len(asked) > policy["max_questions"]:
            violations.append("excessive_clarification")
        if any(
            token in "\n".join(clauses)
            for token in ("手机号", "电话", "身份证", "地址", "姓名", "邮箱")
        ):
            violations.append("irrelevant_personal_information_request")
    else:
        if not any(
            token in message
            for token in ("无法确认", "不能确认", "不能确定", "暂不确定", "还不能", "没法确认")
        ):
            violations.append("missing_uncertainty_acknowledgement")
        if not any(
            token in message
            for token in ("查看", "查找", "检查", "设置", "说明书", "拍", "确认型号")
        ):
            violations.append("missing_actionable_information_guidance")
    success = not violations
    return {
        "success": success,
        "task_score": 0.0,
        "interaction_score": 100.0 if success else 0.0,
        "ndcg": None,
        "idcg": 0.0,
        "ranking_applicable": False,
        "expected_outcome": policy["action"],
        "required_count": 0,
        "feasible_count": None,
        "potentially_feasible_count": None,
        "violations": sorted(set(violations)),
        "items": [],
        "asked_slots": sorted(asked),
        "question_count": len(clauses),
    }


def history_alignment(catalog, gold, result):
    policy = gold["customer_policy"]
    if policy["history_role"] == "disabled":
        return None
    facts = {item["item_id"]: item for item in catalog}
    items = [facts[item_id] for item_id in result.get("item_ids", []) if item_id in facts]
    reference = policy.get("history_reference", {})
    output = {"role": "weak_reference", "used_for_primary_score": False}
    for field in ("category", "store"):
        scores = reference.get(f"{field}_scores", {})
        values = [scores.get(item.get(field), 0) for item in items if item.get(field) is not None]
        output[f"{field}_mean"] = statistics.mean(values) if values and scores else None
    return output


def recommendation_interaction_violations(gold, result):
    question_text = "\n".join(result.get("questions", []))
    if not question_text:
        question_text = "\n".join(
            clause
            for clause in re.split(r"[。\n]", result.get("message", ""))
            if "？" in clause or "?" in clause
        )
    if any(
        alias in question_text
        for slot in gold["customer_policy"].get("known_slots", [])
        for alias in SLOT_ALIASES[slot]
    ):
        return ["unnecessary_clarification"]
    return []


def customer_reference(gold):
    policy = gold["customer_policy"]
    questions = {
        "budget": "预算大概是多少？",
        "recipient_need": "送给谁，对方想要什么类型的东西？",
        "device": "现有设备的型号或接口是什么？",
        "profile_preference": "这次有什么偏好，还是沿用之前的习惯吗？",
    }
    if policy["action"] in {"clarify", "recommend_or_clarify"}:
        if "profile_preference" in policy["required_slots"]:
            questions["profile_preference"] = {
                "tip_mm": "这次想用什么粗细的笔尖？",
                "connection_type": "这次想要有线还是无线款呢？",
                "store": "这次想从哪家店铺选？",
            }[policy["clarification_field"]]
        elif policy.get("evaluation_policy") == "natural-shopping/1" and policy.get(
            "clarification_field"
        ):
            questions["recipient_need"] = {
                "tip_mm": "家人平时用笔喜欢细字还是粗字？",
                "connection_type": "对方想要有线还是无线耳机？",
                "store": "对方有没有特别偏好的店铺？",
            }[policy["clarification_field"]]
        asked = [questions[slot] for slot in policy["required_slots"]]
        return {
            "item_ids": [],
            "outcome": "uncertain_match",
            "message": "\n".join(asked),
            "questions": asked,
            "limitations": ["unknown_attributes"],
        }
    return {
        "item_ids": [],
        "outcome": "uncertain_match",
        "message": "现在无法确认兼容性，请在设备设置、铭牌或说明书中查看型号与接口，再核对商品规格。",
        "limitations": ["unknown_attributes"],
    }
