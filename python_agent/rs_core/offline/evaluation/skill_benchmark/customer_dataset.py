"""从已验证真实绑定构建顾客情境；不伪造设备规格、用途效果或真人需求。"""

import copy
import math

from .dataset import fingerprint, validate_benchmark


# 仅翻译类目名称，不从类目或标题推断兼容性、性能和保修。
CATEGORY_NAMES = {
    "Computer Cases": "电脑机箱",
    "Earbud Headphones": "入耳式耳机",
    "Inkjet Ink Cartridges": "打印机墨盒",
    "Water Cooling Systems": "电脑水冷散热器",
    "Clipboards": "写字夹板",
    "Camera Mounts & Clamps": "相机固定夹",
    "Monitor Arms": "显示器支臂",
    "Computer Workstations": "电脑桌",
    "VGA Cables": "VGA连接线",
    "Fixed-mount CB Radios": "车载电台",
    "Gel Ink Rollerball Pens": "中性笔",
    "Label Printers": "标签打印机",
    "Case Fans": "机箱风扇",
    "Internal Power Supplies": "电脑电源",
    "Supply Organizers": "办公用品收纳盒",
    "External Solid State Drives": "移动固态硬盘",
    "Power Converters": "电源转换器",
    "Single Board Computers": "单板电脑",
    "Vehicle Backup Cameras": "倒车摄像头",
    "CPU Processors": "电脑处理器",
    "Ballpoint Pens": "圆珠笔",
    "Backpacks": "背包",
    "Stabilizers": "相机稳定器",
    "Smartwatches": "智能手表",
    "Extension Cords": "电源延长线",
    "Camera": "相机电池充电器",
    "In-Mirror Video": "后视镜显示设备",
    "Compressed Air Dusters": "清洁气吹",
    "Self-Stick Notes": "便利贴",
    "Switches": "网络交换机",
    "Keyboard & Mouse Combos": "键鼠套装",
    "Pencil Holders": "笔筒",
    "Amplifiers": "音频功放",
    "Tablets": "平板电脑",
    "Backgrounds": "摄影背景布",
    "Ink Tank Printers": "墨仓式打印机",
    "Minis": "迷你电脑",
    "Drawer Organizers": "抽屉收纳盒",
    "USB Lamps": "USB灯",
    "TV Wall & Ceiling Mounts": "电视支架",
    "Mouse Pads": "鼠标垫",
    "Chargers & Adapters": "充电器",
    "Back & Seat Cushions": "坐垫",
    "Earpads": "耳机耳罩",
    "Cable Raceways": "理线槽",
    "Planning Boards": "计划看板",
    "In-Dash Navigation": "车载导航设备",
    "USB Network Adapters": "USB网卡",
    "Power Cords": "电源线",
    "Car Stereo Receivers": "车载音响主机",
    "Laminators": "塑封机",
    "Towers": "台式电脑",
    "USB Cables": "USB连接线",
    "Hardcover Executive Notebooks": "硬皮笔记本",
    "Keyboards": "键盘",
    "Bluetooth Transmitters": "蓝牙发射器",
    "Remote Controls": "遥控器",
    "Portable Bluetooth Speakers": "便携蓝牙音箱",
    "Docking Stations": "扩展坞",
    "Key Cabinets": "钥匙收纳柜",
    "Stands": "支架",
    "Sleeves": "电脑内胆包",
    "Vehicle Mounts": "车载支架",
    "Dome Cameras": "半球摄像头",
    "Network Adapters": "网卡",
    "CD-R": "可刻录光盘",
    "Filter Sets": "相机滤镜套装",
    "Complete Tripods": "三脚架",
    "Internal Solid State Drives": "内置固态硬盘",
    "Lap Desks": "膝上电脑桌",
    "Power Strips": "插线板",
    "Heatsinks": "散热片",
    "DVI": "DVI连接线",
    "In-Dash DVD & Video Receivers": "车载影音主机",
    "Cat 6 Cables": "六类网线",
    "Greeting Cards": "贺卡",
    "Porous-Point Pens": "签字笔",
    "Mechanical Pencils": "自动铅笔",
    "USB Hubs": "USB集线器",
    "Item Finders": "物品防丢器",
    "Monitors": "显示器",
    "Dry Erase & Wet Erase Markers": "白板笔",
    "Over-Ear Headphones": "头戴式耳机",
    "Mounting Tape": "固定胶带",
    "Connectors & Adapters": "转接头",
    "Memory Card Readers": "读卡器",
    "Mice": "鼠标",
    "HDMI Cables": "HDMI连接线",
    "Covers": "电子阅读器保护套",
    "Racks & Displays": "陈列架",
    "Magnetic Tape": "磁性胶带",
    "Speaker": "音箱连接线",
    "Serial Cables": "串口连接线",
    "Monitor Stands": "显示器增高架",
    "USB-to-VGA Adapters": "USB转VGA转接器",
    "Batteries": "电池",
    "Power & Ground Cable": "供电连接线",
    "Graphics Tablets": "数位板",
    "CompactFlash Cards": "CF存储卡",
    "Thermal Pads": "导热垫",
    "Memory": "内存条",
    "pens": "笔",
    "Heart Rate Monitors": "心率计",
    "Wi-Fi Range Extenders": "Wi-Fi信号扩展器",
    "Open-Ear Headphones": "开放式耳机",
    "Pen Refills": "替换笔芯",
    "Micro SD Memory Cards": "micro SD存储卡",
    "CB Radio Microphones": "车载电台麦克风",
    "SWR Meters": "驻波比测量表",
    "Sticky Note Dispensers": "便利贴分配器",
}

COMPATIBILITY_CATEGORIES = {
    "Camera",
    "Speaker",
    "Stands",
    "Computer Cases",
    "Inkjet Ink Cartridges",
    "Water Cooling Systems",
    "Camera Mounts & Clamps",
    "Monitor Arms",
    "VGA Cables",
    "Case Fans",
    "Internal Power Supplies",
    "CPU Processors",
    "Power Converters",
    "Vehicle Backup Cameras",
    "TV Wall & Ceiling Mounts",
    "Chargers & Adapters",
    "Earpads",
    "In-Dash Navigation",
    "Power Cords",
    "Car Stereo Receivers",
    "USB Cables",
    "Remote Controls",
    "Docking Stations",
    "Vehicle Mounts",
    "Filter Sets",
    "Internal Solid State Drives",
    "Heatsinks",
    "DVI",
    "In-Dash DVD & Video Receivers",
    "Connectors & Adapters",
    "Memory Card Readers",
    "HDMI Cables",
    "Covers",
    "Serial Cables",
    "USB-to-VGA Adapters",
    "Batteries",
    "Power & Ground Cable",
    "CompactFlash Cards",
    "Thermal Pads",
    "Memory",
}


def build_customer_benchmark(source):
    """保持商品、画像、真实绑定和用户划分，替换整个任务设计与历史评分口径。"""
    validate_benchmark(source)
    bases = [task for task in source["tasks"] if task["kind"] == "personalized"]
    if not bases or not source.get("profiles"):
        raise ValueError("需要含真实画像绑定的 personalized 来源")
    result = copy.deepcopy(source)
    result["tasks"] = []
    facts = {item["item_id"]: item for item in result["catalog"]}
    for base in bases:
        anchor = facts[base["anchor_item_id"]]
        category, currency = anchor["category"], anchor["currency"]
        if category not in CATEGORY_NAMES:
            raise ValueError(f"缺少待审核的顾客类目表达：{category}")
        noun = CATEGORY_NAMES[category]
        path = anchor.get("category_path", [])
        if category == "Stands":
            noun = (
                "音箱支架"
                if "Speaker Accessories" in path
                else "笔记本支架"
                if "Laptop Accessories" in path
                else "平板支架"
            )
        elif category == "Remote Controls":
            noun = "相机遥控器" if "Camera & Photo" in path else "电视遥控器"
        elif category == "Batteries":
            noun = "笔记本电池" if "Laptop Accessories" in path else "电话电池"
        elif category == "Chargers & Adapters":
            noun = "笔记本充电器" if "Laptop Accessories" in path else "平板充电器"
        budget = max(10, math.ceil(anchor["price"] * 1.2 / 10) * 10)
        profile = result["profiles"][base["profile_user_id"]]
        reference = profile["profile_preferences"]

        def gold(
            action="recommend",
            *,
            limit=budget,
            target_category=category,
            target_path=None,
            role="weak_reference",
            soft=None,
            required=None,
            known=None,
        ):
            hard = [{"field": "currency", "op": "eq", "value": currency}]
            if target_category is not None:
                hard.append({"field": "category", "op": "eq", "value": target_category})
                hard.append(
                    {
                        "field": "category_path",
                        "op": "eq",
                        "value": target_path if target_path is not None else path,
                    }
                )
            if limit is not None:
                hard.append({"field": "price", "op": "lte", "value": limit})
            policy = {
                "action": action,
                "history_role": role,
                "history_reference": {
                    key: copy.deepcopy(reference.get(key, {}))
                    for key in ("category_scores", "store_scores")
                }
                if role != "disabled"
                else {},
                "known_slots": known if known is not None else ["budget", "category", "quantity"],
                "primary_quality": "current_request_only; no_implicit_price_or_profile_preference",
                "currency_source": "public_store_context_not_customer_utterance",
            }
            if action == "clarify":
                policy.update(required_slots=required, max_questions=2)
            return {"k": 1, "hard": hard, "soft": soft or [], "customer_policy": policy}

        def turn(message, rule, **extra):
            return {"user_message": message, "limit": 1, "gold": rule, **extra}

        def add(kind, turns, *, purpose="self", environment=None):
            result["tasks"].append(
                {
                    "task_id": f"{base['family_id']}-customer-{kind}",
                    "family_id": base["family_id"],
                    "profile_user_id": base["profile_user_id"],
                    "split": base["split"],
                    "kind": kind,
                    "anchor_item_id": base["anchor_item_id"],
                    "anchor_evidence": copy.deepcopy(base["anchor_evidence"]),
                    "review_status": "pending",
                    "dialogue_policy": "conditional_customer/1",
                    "customer_context": {
                        "purchase_for": purpose,
                        "scenario_origin": "synthetic_customer_situation; not_recovered_real_intent",
                        "history_transfer": "disabled_for_others"
                        if purpose != "self"
                        else "weak_reference_only",
                    },
                    "environment": environment or {},
                    "turns": turns,
                }
            )

        initial = f"想买{noun}，预算{budget:g}以内，先帮我选1款参考。"
        add("clear_purchase", [turn(initial, gold())])
        add(
            "missing_budget",
            [
                turn(
                    f"想买{noun}，先帮我选1款，别太贵。",
                    gold(
                        "clarify", limit=None, required=["budget"], known=["category", "quantity"]
                    ),
                ),
                turn(f"预算{budget:g}以内就好。", gold()),
            ],
        )
        add(
            "gift_needs",
            [
                turn(
                    f"想给家人买份礼物，预算{budget:g}以内，帮我挑1款。",
                    gold(
                        "clarify",
                        target_category=None,
                        role="disabled",
                        required=["recipient_need"],
                        known=["budget", "quantity"],
                    ),
                ),
                turn(
                    f"是送给家人的，对方刚好想要{noun}。就按这个方向选1款，预算不变。",
                    gold(role="disabled"),
                ),
            ],
            purpose="gift",
            environment={"history_retrieval_role": "disabled"},
        )
        add(
            "explicit_new_need",
            [
                turn(
                    f"这次是替家人买{noun}，不是我自己用，别照我平时买的来选。预算{budget:g}以内，给我选1款。",
                    gold(role="disabled"),
                )
            ],
            purpose="household",
            environment={"history_retrieval_role": "disabled"},
        )
        add(
            "price_priority",
            [
                turn(
                    initial + "符合这个要求就行，越便宜越好。",
                    gold(
                        soft=[
                            {
                                "field": "price",
                                "op": "minimize",
                                "best": 0,
                                "worst": budget * 1.1,
                                "weight": 1,
                            }
                        ]
                    ),
                )
            ],
        )
        if anchor.get("store"):
            add(
                "explicit_store_preference",
                [
                    turn(
                        initial + f"符合预算的情况下，优先看看“{anchor['store']}”家的商品。",
                        gold(
                            soft=[
                                {
                                    "field": "store",
                                    "op": "eq",
                                    "value": anchor["store"],
                                    "weight": 1,
                                }
                            ]
                        ),
                    )
                ],
            )
        if reference.get("preferred_store"):
            confirmed_store = reference["preferred_store"]
            confirmed = gold(
                soft=[{"field": "store", "op": "eq", "value": confirmed_store, "weight": 1}]
            )
            confirmed["customer_policy"]["explicit_preference_source"] = (
                "current_customer_confirms_past_store; not_latent_history_weight"
            )
            add(
                "confirmed_history_preference",
                [
                    turn(
                        f"以前“{confirmed_store}”家的东西用着还行。这次想买{noun}，预算{budget:g}以内，优先从他家帮我挑1款；没有合适的也可以看别家。",
                        confirmed,
                    )
                ],
            )
        reduced = max(5, math.floor(budget * 0.6 / 5) * 5)
        add(
            "budget_change",
            [
                turn(initial, gold()),
                turn(f"刚算了一下，最多只能花{reduced:g}，其他要求不变。", gold(limit=reduced)),
            ],
        )
        add(
            "reject_previous",
            [
                turn(initial, gold()),
                turn(
                    "刚才推荐的我不考虑了，换1款，预算和其他要求不变。",
                    gold(),
                    exclude_previous=True,
                ),
            ],
        )
        warranty = gold()
        warranty["hard"].append({"field": "warranty_years", "op": "gte", "value": 5})
        add("unknown_warranty", [turn(initial + "但必须有至少5年保修，能帮我确认吗？", warranty)])
        add(
            "tool_unavailable",
            [turn(initial, gold())],
            environment={"unavailable_tools": ["recommend_semantic_recall"]},
        )
        minimum = min(item["price"] for item in facts.values() if item.get("category_path") == path)
        too_low = math.floor(minimum / 2 / 5) * 5 if minimum >= 10 else round(minimum / 2, 2)
        if too_low > 0:
            add(
                "budget_unaffordable",
                [
                    turn(
                        f"想买{noun}，但最多只能花{too_low:g}，能帮我选1款吗？", gold(limit=too_low)
                    )
                ],
            )
        if category in COMPATIBILITY_CATEGORIES:
            add(
                "compatibility_unknown",
                [
                    turn(
                        f"想买{noun}，预算{budget:g}以内。需要能用在我现在的设备上，帮我选1款。",
                        gold("clarify", required=["device"]),
                    ),
                    turn(
                        "设备型号我暂时不清楚。先告诉我要去哪里找哪些信息，没确认之前先别替我定商品。",
                        gold("defer"),
                    ),
                ],
            )
        repeat = next(
            (
                facts[event["parent_asin"]]
                for event in profile["history"]
                if event["parent_asin"] in facts
                and facts[event["parent_asin"]].get("price") is not None
            ),
            None,
        )
        if repeat is not None:
            repeat_gold = gold(
                limit=max(budget, math.ceil(repeat["price"] / 10) * 10),
                target_category=repeat["category"],
                target_path=repeat.get("category_path", []),
            )
            repeat_gold["hard"].append({"field": "item_id", "op": "eq", "value": repeat["item_id"]})
            repeat_budget = next(c["value"] for c in repeat_gold["hard"] if c["field"] == "price")
            add(
                "repeat_purchase",
                [
                    turn(
                        f"之前买的“{repeat['title']}”用着还行，我想再买1件同款，预算{repeat_budget:g}以内。",
                        repeat_gold,
                    )
                ],
            )
    result["environment"].update(
        exclude_seen_items=False,
        history_retrieval_role="weak_reference",
        retrieval="lexical_price_weak_history/1",
        shopping_context={
            "price_unit": "SOURCE_UNIT",
            "price_display": "所有预算数字按商店目录的标价单位理解；原始币种未确认，不换算，不称为人民币或美元。",
            "catalog_scope": "frozen_fixture_only",
            "customer_information": "未知设备规格、保修、性能必须核实，不从购买历史推断。",
        },
    )
    result["manifest"].update(
        builder_version="customer-shopping-scenarios/1",
        parent_benchmark_sha256=fingerprint(source),
        human_reviewed=False,
        scoring_calibration_required=True,
        scoring_calibration={"status": "pending_customer_scenario_human_review", "passed": False},
        task_design="customer_intent_then_observable_information_then_conditional_clarification",
        history_scoring_policy="implicit_history_separate_diagnostic_only; customer_confirmed_preference_becomes_explicit_request; disabled_for_gifts_and_others",
        gold_policy="hidden; current_public_request_only; future_customer_replies_conditionally_released",
        primary_scoring_policy="hard_gated_current_request; explicit_soft_priority_only; no_latent_profile_weights",
        clarification_policy="visible_question_rule_projection; max_2_question_clauses; known_information_not_reasked; human_calibration_required",
        scenario_origin="curated_synthetic_customer_templates; not_real_customer_dialogue",
        evaluation_scope="recommendation_and_clarification; not_purchase_payment_shipping_or_live_inventory",
    )
    for stale in (
        "stress_suite_version",
        "profile_scoring_policy",
        "price_scale_policy",
        "readiness_policy",
    ):
        result["manifest"].pop(stale, None)
    validate_benchmark(result)
    return result
