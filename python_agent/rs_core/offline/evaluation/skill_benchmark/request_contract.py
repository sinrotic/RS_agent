"""候选购物请求协议；只校验结构与引用，不产生人审 gold 或满意度。"""

import copy
import json
import math
import re

REQUEST_VERSION = "rs-shopping-request/2"
AUDIT_VERSION = "rs-shopping-audit/2"
INTENTS = {"recommendation", "comparison", "compatibility_consultation", "information_consultation", "mixed", "unknown"}
ACTIONS = {"recommend", "compare", "explain", "verify_compatibility", "guide_verification"}
DIMENSIONS = {"naturalness", "extraction_fidelity", "fact_boundary", "clarification_policy"}


def text(value, limit=2000):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError("协议文本必须为非空字符串且在长度限制内")
    return value


def keys(value, expected):
    if not isinstance(value, dict) or set(value) != set(expected):
        raise ValueError("协议对象字段缺失或包含未知字段")


def rows(value, limit=20):
    if not isinstance(value, list) or len(value) > limit:
        raise ValueError("协议列表无效或超过数量限制")
    return value


def choices(value, allowed):
    """枚举拒绝容器类型，模型坏输出统一走受控 ValueError。"""
    return isinstance(value, str) and value in allowed


def unique_strings(value):
    return all(isinstance(entry, str) for entry in value) and len(value) == len(set(value))


def quote(value, message):
    if text(value) not in message:
        raise ValueError("条件证据不在顾客原话中")


def _value(value):
    if isinstance(value, str):
        text(value)
    elif type(value) in {int, float}:
        if not math.isfinite(value):
            raise ValueError("协议数值必须有限")
    elif type(value) is bool:
        pass
    elif isinstance(value, list) and 1 <= len(value) <= 30:
        for entry in value:
            if isinstance(entry, list) or isinstance(entry, dict):
                raise ValueError("条件值不接受嵌套容器")
            _value(entry)
    else:
        raise ValueError("条件值必须是标量或非空标量列表")


def validate_request(value, message):
    if isinstance(value, dict) and value.get("schema_version") == "rs-shopping-request/3":
        from .request_contract_v3 import validate_request_v3
        return validate_request_v3(value, message, validate_request)
    keys(value, {"schema_version", "intent", "context_facts", "answer_requirements", "requirements", "unknowns", "clarification", "recipient"})
    if value["schema_version"] != REQUEST_VERSION:
        raise ValueError("不支持的候选需求协议版本")
    intent = value["intent"]
    keys(intent, {"primary", "actions", "evidence"})
    if not choices(intent["primary"], INTENTS):
        raise ValueError("无效购物意图")
    actions = rows(intent["actions"], 5)
    if (not unique_strings(actions) or any(not choices(action, ACTIONS) for action in actions)
            or (intent["primary"] != "unknown" and not actions)):
        raise ValueError("无效或重复的请求动作")
    evidence = rows(intent["evidence"], 5)
    if intent["primary"] != "unknown" and not evidence:
        raise ValueError("意图缺少原话依据")
    for entry in evidence:
        quote(entry, message)
    for fact in rows(value["context_facts"]):
        keys(fact, {"name", "value", "quote"})
        text(fact["name"], 64)
        _value(fact["value"])
        quote(fact["quote"], message)
    for need in rows(value["answer_requirements"]):
        keys(need, {"need", "quote"})
        text(need["need"])
        quote(need["quote"], message)
    identifiers = set()
    for requirement in rows(value["requirements"]):
        keys(requirement, {"id", "kind", "field", "relation", "value", "unit", "quote"})
        identifier = text(requirement["id"], 64)
        if identifier in identifiers:
            raise ValueError("需求id重复")
        identifiers.add(identifier)
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", text(requirement["field"], 64)):
            raise ValueError("无效约束字段")
        kind, relation, expected = requirement["kind"], requirement["relation"], requirement["value"]
        allowed = {"strict": {"eq", "lte", "gte", "in", "not_in"}, "approximate": {"about"},
                   "preference": {"prefer", "minimize", "maximize"}}
        if not choices(kind, allowed) or not choices(relation, allowed[kind]):
            raise ValueError("条件强度与运算不一致，近似要求不得伪装成严格边界")
        _value(expected)
        if requirement["field"] == "quantity":
            raise ValueError("数量须区分purchase_quantity与recommendation_count")
        if requirement["field"] in {"purchase_quantity", "recommendation_count"} and (
                type(expected) is not int or expected < 1):
            raise ValueError("数量必须是正整数")
        if relation in {"lte", "gte", "about"} and (type(expected) not in {int, float} or not math.isfinite(expected)):
            raise ValueError("数值关系必须使用有限数字")
        if relation in {"in", "not_in"} and not isinstance(expected, list):
            raise ValueError("集合关系必须使用列表")
        if requirement["unit"] is not None:
            text(requirement["unit"], 64)
        quote(requirement["quote"], message)
    unknowns = {}
    levels = {"required_for_requested_answer", "needed_for_specific_item", "optional_refinement"}
    for unknown in rows(value["unknowns"]):
        keys(unknown, {"slot", "reason", "needed_for", "blocking_level"})
        slot = text(unknown["slot"], 64)
        if slot in unknowns:
            raise ValueError("未知槽位重复")
        unknowns[slot] = unknown
        text(unknown["reason"])
        needed = rows(unknown["needed_for"], 5)
        if not needed or not unique_strings(needed) or any(not choices(action, ACTIONS) for action in needed):
            raise ValueError("未知信息必须注明适用动作")
        if not choices(unknown["blocking_level"], levels):
            raise ValueError("未知信息缺少适用的阻塞等级")
        if unknown["blocking_level"] == "required_for_requested_answer" and not set(needed).intersection(actions):
            raise ValueError("不能把未请求动作所需的信息当成本次必问条件")
    clarification = value["clarification"]
    keys(clarification, {"mode", "safe_answer_before_clarification", "unresolved_actions", "questions"})
    mode, safe = clarification["mode"], clarification["safe_answer_before_clarification"]
    if not choices(mode, {"required_before_answer", "answer_partially_then_clarify", "answer_then_optional_question", "not_needed"}) or type(safe) is not bool:
        raise ValueError("无效澄清模式")
    unresolved = rows(clarification["unresolved_actions"], 5)
    if not unique_strings(unresolved) or not set(unresolved) <= set(actions):
        raise ValueError("暂缓动作必须属于本次明确请求")
    questions = rows(clarification["questions"], 2)
    blocking_slots = {slot for slot, row in unknowns.items() if row["blocking_level"] == "required_for_requested_answer"}
    covered = set()
    action_covered = set()
    action_slots_covered = set()
    action_slots_needed = {slot for slot, row in unknowns.items()
                           if row["blocking_level"] != "optional_refinement"
                           and set(row["needed_for"]).intersection(unresolved)}
    for question in questions:
        keys(question, {"question", "slots", "necessity", "reason"})
        text(question["question"])
        text(question["reason"])
        slots = rows(question["slots"], 10)
        if not slots or not unique_strings(slots) or any(slot not in unknowns for slot in slots):
            raise ValueError("澄清问题必须引用已标出的未知槽位")
        if not choices(question["necessity"], {"blocking", "required_for_action", "optional"}):
            raise ValueError("澄清缺少必要性说明")
        if question["necessity"] == "blocking":
            if not set(slots) <= blocking_slots:
                raise ValueError("可选细节不能作为必问门槛")
            covered.update(slots)
        if question["necessity"] != "optional":
            action_slots_covered.update(slots)
            for slot in slots:
                if unknowns[slot]["blocking_level"] == "optional_refinement":
                    raise ValueError("可选细节不能作为动作结论的必问门槛")
                linked = set(unknowns[slot]["needed_for"]).intersection(unresolved)
                if not linked:
                    raise ValueError("必要追问必须对应暂缓动作")
                action_covered.update(linked)
    if mode == "required_before_answer":
        if (safe or not unresolved or not blocking_slots or not blocking_slots <= covered
                or not set(unresolved) <= action_covered or not action_slots_needed <= action_slots_covered):
            raise ValueError("必问模式需有相关阻塞信息及覆盖问题")
    elif mode == "answer_partially_then_clarify":
        if (not safe or not unresolved or not set(actions) - set(unresolved) or blocking_slots
                or not set(unresolved) <= action_covered or not action_slots_needed <= action_slots_covered
                or any(q["necessity"] == "blocking" for q in questions)):
            raise ValueError("部分回答必须保留可答动作，并为暂缓结论提供必要追问")
    else:
        if not safe or blocking_slots or unresolved or any(q["necessity"] != "optional" for q in questions):
            raise ValueError("可先回答的模式不能附带必问门槛")
        if (mode == "not_needed" and questions) or (mode == "answer_then_optional_question" and not questions):
            raise ValueError("澄清模式与问题数量不一致")
    recipient = value["recipient"]
    keys(recipient, {"target", "quote", "profile_policy"})
    if not choices(recipient["target"], {"self", "other", "unknown"}):
        raise ValueError("无效收礼人状态")
    if recipient["target"] == "unknown":
        if recipient["quote"] is not None:
            raise ValueError("未知对象不附加推测证据")
    else:
        quote(recipient["quote"], message)
    if not choices(recipient["profile_policy"], {"weak_reference_if_self", "do_not_transfer_to_recipient", "not_relevant"}):
        raise ValueError("无效画像参与策略")
    if recipient["target"] == "other" and recipient["profile_policy"] == "weak_reference_if_self":
        raise ValueError("赠送者历史不能作为收礼人偏好")
    return copy.deepcopy(value)


def validate_audit_contract(value, message, context):
    """v2 分维度理由；旧格式只读兼容，逐字证据规则不放宽。"""
    if isinstance(value, dict) and value.get("schema_version") == "rs-shopping-audit/3":
        projection = copy.deepcopy(value)
        projection["schema_version"] = AUDIT_VERSION
        validate_audit_contract(projection, message, context)
        return copy.deepcopy(value)
    if isinstance(value, dict) and "schema_version" in value:
        keys(value, {"schema_version", "checks", "reasons", "evidence", "issues"})
        if value["schema_version"] != AUDIT_VERSION:
            raise ValueError("不支持的预审协议版本")
        reasons = value["reasons"]
        keys(reasons, DIMENSIONS)
        for reason in reasons.values():
            text(reason)
    else:
        keys(value, {"checks", "reason", "evidence", "issues"})
        reason = value["reason"]
        if isinstance(reason, dict):
            keys(reason, DIMENSIONS)
            for entry in reason.values():
                text(entry)
        else:
            text(reason)
    keys(value["checks"], DIMENSIONS)
    if any(not choices(check, {"pass", "fail", "unknown"}) for check in value["checks"].values()):
        raise ValueError("预审维度缺失或值无效")
    for issue in rows(value["issues"]):
        text(issue)
    evidence = rows(value["evidence"])
    if not evidence:
        raise ValueError("预审缺少证据")
    sources = {"customer": message, **{key: json.dumps(context[key], ensure_ascii=False)
                                      for key in ("catalog", "profile")}}
    for row in evidence:
        keys(row, {"source", "quote"})
        if not choices(row["source"], sources) or text(row["quote"]) not in sources[row["source"]]:
            raise ValueError("预审引用不在可见事实中")
    return copy.deepcopy(value)


def strict_fact_inputs(value):
    """只投影严格条件供事实检查；近似与偏好完整保留，不构造容差或权重。"""
    return {"hard_constraints": [{"field": row["field"], "op": row["relation"], "value": copy.deepcopy(row["value"]),
                                   "quote": row["quote"]} for row in value["requirements"] if row["kind"] == "strict"]}


def schema_description():
    return {"request_schema_version": REQUEST_VERSION, "audit_schema_version": AUDIT_VERSION,
            "intent_kinds": sorted(INTENTS), "requested_actions": sorted(ACTIONS),
            "requirement_kinds": {"strict": ["eq", "lte", "gte", "in", "not_in"],
                                  "approximate": ["about"], "preference": ["prefer", "minimize", "maximize"]},
            "clarification_modes": ["required_before_answer", "answer_partially_then_clarify", "answer_then_optional_question", "not_needed"],
            "numeric_tolerance_policy": "近似值只保留中心值；未定义容差，不转成硬过滤条件",
            "quantity_policy": "purchase_quantity与recommendation_count分开；口语单数不自动成为严格数量",
            "validation_scope": "结构和逐字证据；不认证语义、隐含意图、事实真实性或人工批准",
            "is_gold": False, "auto_deploy": False}
