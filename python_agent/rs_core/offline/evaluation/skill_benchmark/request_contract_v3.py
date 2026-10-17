"""预览需求协议 v3：受控规范化、逐字证据定位和跨字段安全边界。

原始输出不得覆盖；规范化不补造需求、币种、容差或人工 gold。
"""

import copy
from decimal import Decimal

REQUEST_VERSION = "rs-shopping-request/3"
AUDIT_VERSION = "rs-shopping-audit/3"
VALIDATOR_REVISION = "v3-action-local-clarification-2"
ANSWER_KINDS = {"recommendation", "comparison", "explanation", "verification_steps",
                "decision_support", "compatibility_verdict"}
FIELD_ALIASES = {"budget": "price", "cable_length": "length",
                 "installation_complexity": "installation_difficulty",
                 "wireless_band_support": "dual_band", "wearing_pressure": "wearing_comfort",
                 "noise_cancellation": "noise_control"}
FIELDS = {"product_type", "price", "length", "operating_system", "purchase_quantity",
          "recommendation_count", "use_case", "music_and_calls", "thermal_coverage", "cooling_goal",
          "noise_control", "wearing_comfort", "wireless", "dual_band", "installation_difficulty",
          "reliability", "priority", "category", "category_path", "brand", "store", "connection_type",
          "tip_mm", "warranty_years", "battery_hours", "microphone", "writing"}
LENGTH_UNITS = {"m": "1", "米": "1", "cm": "0.01", "厘米": "0.01", "mm": "0.001",
                "毫米": "0.001", "ft": "0.3048", "feet": "0.3048", "英尺": "0.3048"}
CURRENCIES = {"CNY", "USD", "EUR", "JPY", "GBP", "HKD", "CAD", "AUD", "KRW", "SGD"}


def evidence_report(value, message):
    """收集所有 quote 和 intent.evidence；偏移由程序计算，不让模型猜位置。"""
    records = []

    def append(path, quote):
        valid = isinstance(quote, str) and bool(quote.strip()) and len(quote) <= 2000 and quote in message
        start = message.find(quote) if valid else None
        records.append({"path": path, "quote": quote, "valid": valid, "start": start,
                        "end": start + len(quote) if valid else None})

    def walk(node, path=""):
        if isinstance(node, dict):
            for key, child in node.items():
                child_path = path + "/" + key
                if key == "quote":
                    if child is not None or path != "/recipient" or node.get("target") != "unknown":
                        append(child_path, child)
                elif child_path == "/intent/evidence" and isinstance(child, list):
                    for index, entry in enumerate(child):
                        append(child_path + "/" + str(index), entry)
                else:
                    walk(child, child_path)
        elif isinstance(node, list):
            for index, child in enumerate(node):
                walk(child, path + "/" + str(index))

    walk(value)
    return {"offset_unit": "unicode_codepoint", "range": "zero_based_half_open_first_occurrence",
            "records": records, "errors": [entry for entry in records if not entry["valid"]],
            "all_quotes_valid": all(entry["valid"] for entry in records)}


def normalize_request(value):
    """仅接受注册别名及精确单位换算；未知维度拒绝，不静默降级。"""
    result, changes = copy.deepcopy(value), []
    requirements = result.get("requirements", []) if isinstance(result, dict) else []
    if not isinstance(requirements, list):
        raise ValueError("requirements必须为列表")
    for index, row in enumerate(requirements):
        if not isinstance(row, dict) or not isinstance(row.get("field"), str):
            raise ValueError("条件字段无效")
        before = {key: copy.deepcopy(row.get(key)) for key in ("field", "value", "unit")}
        field = FIELD_ALIASES.get(row["field"], row["field"])
        if field not in FIELDS:
            raise ValueError("未注册的条件字段：" + field)
        row["field"] = field
        unit, amount = row.get("unit"), row.get("value")
        if field == "length":
            if not isinstance(unit, str) or unit not in LENGTH_UNITS or type(amount) not in {int, float}:
                raise ValueError("长度必须有已知单位与数值，不能推定未知单位")
            numeric = Decimal(str(amount)) * Decimal(LENGTH_UNITS[unit])
            if not numeric.is_finite():
                raise ValueError("长度必须有限")
            row.update(value=float(numeric), unit="m")
        elif field == "price":
            if unit is not None and (not isinstance(unit, str) or unit not in CURRENCIES):
                raise ValueError("价格单位只能是明确币种代码或null")
        elif field in {"purchase_quantity", "recommendation_count"}:
            allowed = {"purchase_quantity": {"item", "件", "副", "个"},
                       "recommendation_count": {"option", "款"}}[field]
            if unit is not None and (not isinstance(unit, str) or unit not in allowed):
                raise ValueError("数量单位与数量角色不一致")
            if unit is not None:
                row["unit"] = "item" if field == "purchase_quantity" else "option"
        elif field in {"tip_mm", "warranty_years", "battery_hours"}:
            units = {"tip_mm": {"mm", "毫米"}, "warranty_years": {"year", "年"},
                     "battery_hours": {"h", "小时"}}
            if unit is not None:
                if not isinstance(unit, str) or unit not in units[field]:
                    raise ValueError("数值字段的单位不一致")
                row["unit"] = {"tip_mm": "mm", "warranty_years": "year", "battery_hours": "h"}[field]
        elif unit is not None:
            raise ValueError("非量纲字段不得附加单位")
        after = {key: copy.deepcopy(row.get(key)) for key in before}
        if before != after:
            changes.append({"path": "/requirements/" + str(index), "before": before, "after": after,
                            "policy": "registered_alias_or_exact_unit_conversion"})
    return result, changes


def validate_request_v3(value, message, legacy_validator):
    from .request_contract import keys, choices, rows, text

    if not isinstance(value, dict) or value.get("schema_version") != REQUEST_VERSION:
        raise ValueError("本次必须使用v3需求协议")
    evidence = evidence_report(value, message)
    if evidence["errors"]:
        raise ValueError("非逐字引用：" + ", ".join(row["path"] for row in evidence["errors"]))
    result, _ = normalize_request(value)
    kinds = set()
    for need in rows(result.get("answer_requirements")):
        keys(need, {"kind", "need", "quote"})
        if not choices(need["kind"], ANSWER_KINDS):
            raise ValueError("未注册的回答目标种类")
        kinds.add(need["kind"])
    recipient = result.get("recipient")
    keys(recipient, {"target", "quote", "profile_policy", "profile_reason"})
    text(recipient["profile_reason"])
    # v2负责通用结构；投影是校验用副本，不影响原始和规范化输出。
    projection = copy.deepcopy(result)
    projection["schema_version"] = "rs-shopping-request/2"
    projection["recipient"].pop("profile_reason")
    for need in projection["answer_requirements"]:
        need.pop("kind")
    # v2把required_for_requested_answer视为整条回答的门槛。
    # v3的needed_for已绑定动作：部分回答时，必要信息可以只阻塞该动作。
    # 仅在校验副本中适配旧内核；原始标签及最终输出不改写。
    if isinstance(projection.get("clarification"), dict) and projection["clarification"].get("mode") == "answer_partially_then_clarify":
        for unknown in rows(projection.get("unknowns")):
            if isinstance(unknown, dict) and unknown.get("blocking_level") == "required_for_requested_answer":
                unknown["blocking_level"] = "needed_for_specific_item"
    legacy_validator(projection, message)
    actions = set(result["intent"]["actions"])
    required_kinds = {"recommend": "recommendation", "compare": "comparison",
                      "guide_verification": "verification_steps", "verify_compatibility": "compatibility_verdict"}
    for action, kind in required_kinds.items():
        if action in actions and kind not in kinds:
            raise ValueError("请求动作缺少对应回答目标：" + action)
    unresolved = set(result["clarification"]["unresolved_actions"])
    for unknown in result["unknowns"]:
        if unknown["blocking_level"] == "required_for_requested_answer" and not actions.intersection(unknown["needed_for"]):
            raise ValueError("未来动作缺口不能标成当前答案必需")
        if unknown["blocking_level"] != "optional_refinement":
            needed = actions.intersection(unknown["needed_for"])
            if not needed <= unresolved:
                raise ValueError("当前动作缺少必要信息却未暂缓：" + unknown["slot"])
    if recipient["target"] == "other" and recipient["profile_policy"] != "do_not_transfer_to_recipient":
        raise ValueError("收礼人需求不得迁移赠送者画像")
    # 本预览保守限定：仅recommend动作可条件式参考购物历史；技术方法不计必用分。
    if "recommend" not in actions and recipient["target"] != "other" and recipient["profile_policy"] != "not_relevant":
        raise ValueError("纯比较或技术核查不因自用就适用购物画像")
    fields = {row["field"] for row in result["requirements"]}
    for fact in result["context_facts"]:
        name = FIELD_ALIASES.get(fact["name"], fact["name"])
        if name in {"operating_system", "price", "length", "use_case", "music_and_calls", "thermal_coverage"} and name not in fields:
            raise ValueError("评分条件仅放入背景：" + name)
    return result


def contract_description():
    return {"request_schema_version": REQUEST_VERSION, "audit_schema_version": AUDIT_VERSION,
            "validator_revision": VALIDATOR_REVISION,
            "canonical_fields": sorted(FIELDS), "field_aliases": FIELD_ALIASES,
            "length_unit": "m", "length_conversions": LENGTH_UNITS,
            "price_policy": "币种未知保持null；不从画像、目录或中文表达猜币种",
            "answer_kinds": sorted(ANSWER_KINDS), "quote_offsets": "zero_based_unicode_codepoint_half_open",
            "profile_scope": "仅推荐允许条件式弱参考；纯技术咨询不要求使用历史；送礼不迁移本人画像",
            "validation_scope": "结构、受控规范化、逐字证据及跨字段一致性；不是语义认证或人工gold",
            "is_gold": False, "auto_deploy": False}
