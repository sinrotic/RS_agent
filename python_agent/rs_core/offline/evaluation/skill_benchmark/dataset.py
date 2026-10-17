"""有证据的种子任务生成与严格加载；流式读取，不加载评论或训练模型。"""

import copy
import hashlib
import json
import math
from collections import Counter, defaultdict
from pathlib import Path


def fingerprint(value):
    encoded = json.dumps(
        value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":")
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def validate_gold(gold):
    from .customer import validate_customer_policy

    validate_customer_policy(gold)
    from .natural import validate_relevance_metadata

    validate_relevance_metadata(gold)
    contract = gold.get("quality_contract")
    if contract is not None:
        from .quality_dataset import VERSION, SEMANTIC_DIMENSIONS, SCENARIOS

        if (contract.get("version") != VERSION
                or any(type(contract.get(key)) is not bool for key in ("use_fit_required", "profile_fit_required"))
                or not isinstance(contract.get("semantic_dimensions"), list)
                or not contract["semantic_dimensions"]
                or len(contract["semantic_dimensions"]) != len(set(contract["semantic_dimensions"]))
                or set(contract["semantic_dimensions"]) - set(SEMANTIC_DIMENSIONS)
                or contract.get("scenario") not in ("ordinary", *SCENARIOS)):
            raise ValueError("无效购物质量契约")
    if type(gold.get("k")) is not int or not 1 <= gold["k"] <= 50:
        raise ValueError("k 必须是 1..50 的整数")
    if not isinstance(gold.get("hard"), list) or not gold["hard"]:
        raise ValueError("任务必须有显式硬约束")
    for criterion in gold["hard"]:
        if not isinstance(criterion.get("field"), str) or criterion.get("op") not in {
            "eq",
            "lte",
            "gte",
            "in",
            "not_in",
        }:
            raise ValueError("无效硬约束")
        value = criterion.get("value")
        if criterion["op"] in {"lte", "gte"} and (
            type(value) not in {int, float} or not math.isfinite(value)
        ):
            raise ValueError("数字硬约束必须有限")
        if criterion["op"] in {"in", "not_in"} and not isinstance(value, list):
            raise ValueError("集合硬约束必须是列表")
    for criterion in gold.get("soft", []):
        weight = criterion.get("weight")
        if type(weight) not in {int, float} or not math.isfinite(weight) or weight <= 0:
            raise ValueError("软约束权重必须是有限正数")
        if criterion.get("op") not in {"eq", "minimize", "maximize", "lookup"}:
            raise ValueError("无效软约束")
        if criterion["op"] == "lookup":
            scores = criterion.get("scores")
            if (
                not isinstance(scores, dict)
                or not scores
                or any(
                    not isinstance(key, str)
                    or type(value) not in {int, float}
                    or not math.isfinite(value)
                    or not 0 <= value <= 1
                    for key, value in scores.items()
                )
            ):
                raise ValueError("画像偏好映射必须为非空的字符串到 [0,1] 有限分数")
        elif criterion["op"] != "eq":
            best, worst = criterion.get("best"), criterion.get("worst")
            if any(
                type(value) not in {int, float} or not math.isfinite(value)
                for value in (best, worst)
            ):
                raise ValueError("软约束标尺必须有限")
            if (
                criterion["op"] == "minimize"
                and best >= worst
                or criterion["op"] == "maximize"
                and best <= worst
            ):
                raise ValueError("软约束标尺方向错误")


def validate_benchmark(benchmark):
    if benchmark.get("schema_version") != "rs-skill-benchmark/1":
        raise ValueError("不支持的评测集版本")
    catalog, tasks = benchmark["catalog"], benchmark["tasks"]
    ids = [item["item_id"] for item in catalog]
    if (
        not catalog
        or any(not isinstance(i, str) or not i for i in ids)
        or len(ids) != len(set(ids))
    ):
        raise ValueError("商品目录为空或 item_id 重复/无效")
    if benchmark["manifest"]["catalog_sha256"] != fingerprint(catalog):
        raise ValueError("商品快照哈希不匹配")
    profiles = benchmark.get("profiles", {})
    if not isinstance(profiles, dict):
        raise ValueError("profiles 必须是画像用户映射")
    if profiles and benchmark["manifest"].get("profiles_sha256") != fingerprint(profiles):
        raise ValueError("画像快照哈希不匹配")
    if benchmark["manifest"].get("catalog_curation_version"):
        from .catalog_curation import CURATION_VERSION, corrected_category, title_traits

        if benchmark["manifest"]["catalog_curation_version"] != CURATION_VERSION:
            raise ValueError("不支持的类目修正版")
        all_items = catalog + [
            event["item"]
            for profile in profiles.values()
            for event in profile.get("history", [])
            if event.get("item")
        ]
        for item in all_items:
            if corrected_category(item) is not None:
                raise ValueError("已知商品类型错标没有被修正")
            traits = title_traits(item)
            if any(item.get(field) != traits.get(field) for field in ("connection_type", "tip_mm")):
                raise ValueError("商品属性必须有明确标题证据，不能补造未知属性")
    for user, profile in profiles.items():
        cutoff = profile.get("history_cutoff_exclusive")
        seen = profile.get("seen_item_ids")
        if (
            not isinstance(user, str)
            or profile.get("profile_user_id") != user
            or type(cutoff) is not int
            or cutoff < 0
            or not isinstance(seen, list)
            or any(not isinstance(item, str) for item in seen)
            or not isinstance(profile.get("history"), list)
            or not isinstance(profile.get("profile_preferences"), dict)
        ):
            raise ValueError("无效画像绑定/截止时间/历史结构")
        for event in profile["history"]:
            timestamp = event.get("timestamp")
            rating = event.get("rating")
            if (
                event.get("user_id") != user
                or type(timestamp) is not int
                or not 0 <= timestamp < cutoff
                or event.get("parent_asin") not in seen
                or type(rating) not in {int, float}
                or not math.isfinite(rating)
                or rating < 4
            ):
                raise ValueError("画像历史跨用户、跨时间或不是过去正向交互")
            if event.get("item") and event["item"].get("item_id") not in {
                None,
                event["parent_asin"],
            }:
                raise ValueError("画像历史商品事实绑定错误")
    task_ids, families, profile_families, anchor_families = set(), {}, {}, {}
    profile_clusters, cluster_splits = {}, {}
    for task in tasks:
        from .quality_dataset import task_catalog

        environment = dict(benchmark.get("environment", {}), **task.get("environment", {}))
        if (set(environment.get("masked_catalog_fields", [])) - {"price", "connection_type", "tip_mm", "warranty_years"}
                or environment.get("available_item_ids") is not None
                and (not isinstance(environment["available_item_ids"], list)
                     or set(environment["available_item_ids"]) - set(ids))
                or type(environment.get("transient_failure_budget", 0)) is not int
                or not 0 <= environment.get("transient_failure_budget", 0) <= 5):
            raise ValueError("无效受控商品环境或瞬时故障配置")
        evaluation_catalog = task_catalog(catalog, environment)
        if task["task_id"] in task_ids or task["split"] not in {"train", "dev", "test"}:
            raise ValueError("task_id 重复或 split 无效")
        task_ids.add(task["task_id"])
        previous_split = families.setdefault(task["family_id"], task["split"])
        if previous_split != task["split"]:
            raise ValueError("同一任务 family 跨 split 泄漏")
        user = task.get("profile_user_id")
        if profiles or user is not None:
            if user not in profiles:
                raise ValueError("任务未绑定到真实画像快照")
            if profile_families.setdefault(user, task["family_id"]) != task["family_id"]:
                raise ValueError("同一画像用户必须属于同一 family，禁止跨 split/统计簇泄漏")
            cluster = task.get("statistical_cluster_id", task["family_id"])
            if (
                profile_clusters.setdefault(user, cluster) != cluster
                or cluster_splits.setdefault(cluster, task["split"]) != task["split"]
            ):
                raise ValueError("同一用户或画像对照统计簇不能跨集合或拆分")
            if task.get("anchor_item_id") is not None:
                anchor = task["anchor_item_id"]
                evidence = task.get("anchor_evidence", {})
                timestamp, rating = evidence.get("timestamp"), evidence.get("rating")
                if (
                    anchor not in ids
                    or anchor in profiles[user]["seen_item_ids"]
                    or evidence.get("user_id") != user
                    or evidence.get("parent_asin") != anchor
                    or type(timestamp) is not int
                    or timestamp < profiles[user]["history_cutoff_exclusive"]
                    or type(rating) not in {int, float}
                    or not math.isfinite(rating)
                    or rating < 4
                ):
                    raise ValueError("目标不是该用户在画像截止后、目录可验证的未见正向交互")
                if anchor_families.setdefault(anchor, task["family_id"]) != task["family_id"]:
                    raise ValueError("目标商品在不同 family 重复")
        if not task["turns"]:
            raise ValueError("任务没有 Turn")
        for turn_index, turn in enumerate(task["turns"]):
            if turn.get("continuation") is not None and (
                turn["continuation"] != "only_after_clarification"
                or turn_index == 0
                or task.get("dialogue_policy") != "conditional_customer/1"
                or task["turns"][turn_index - 1]["gold"].get("customer_policy", {}).get("action")
                != "recommend_or_clarify"
            ):
                raise ValueError("顾客偏好答复只能在可选澄清通过后释放")
            if not turn.get("user_message") or turn.get("limit") != turn["gold"]["k"]:
                raise ValueError("缺少用户表达或显式数量不一致")
            validate_gold(turn["gold"])
            if benchmark["manifest"].get("quality_contract_version"):
                from .quality_dataset import quality_contract

                if turn["gold"].get("quality_contract") != quality_contract(task, turn):
                    raise ValueError("质量契约必须覆盖当前任务的全部适用维度")
            if turn["gold"].get("relevance_judgments") is not None:
                from .scoring import evaluate_turn

                evaluate_turn(evaluation_catalog, turn["gold"], {"item_ids": [], "outcome": "invalid_output"})
            if turn["gold"].get("quality_judgments") is not None:
                from .quality_scoring import validate_quality_labels

                validate_quality_labels(turn["gold"], evaluation_catalog)
            match = turn["gold"].get("customer_policy", {}).get("profile_match")
            if match is not None:
                from .profile_matching import build_profile_match

                if user not in profiles or match != build_profile_match(
                    profiles[user], match["category"], match["category_path"], match["field"]
                ):
                    raise ValueError("画像匹配金标准不等于该真实用户的过去类目内证据")
                policy = turn["gold"]["customer_policy"]
                if policy["history_role"] == "environment_reference":
                    access = task.get("environment", {}).get("profile_access", {})
                    if (
                        access.get("allowed") is not True
                        or access.get("bound_profile_user_id") != user
                        or task.get("customer_context", {}).get("purchase_for", "self") != "self"
                    ):
                        raise ValueError("画像参考缺少当前绑定的环境权限，或错误迁移给他人")
                elif not any(
                    text in turn["user_message"] for text in ("照我以前的习惯", "按我以前的习惯")
                ) or any(text in turn["user_message"] for text in ("别照", "不要照", "不要按")):
                    raise ValueError("画像主分缺少当前顾客公开授权，或与当前拒绝冲突")
    groups = benchmark.get("contrast_groups", [])
    if (
        groups
        or benchmark["manifest"].get("contrast_groups_sha256")
        or any(task.get("contrast_group_id") for task in tasks)
    ):
        if not isinstance(groups, list) or not groups:
            raise ValueError("画像对照清单不能缺失或清空")
        if benchmark["manifest"].get("contrast_groups_sha256") != fingerprint(groups):
            raise ValueError("画像对照清单哈希不匹配")
        tasks_by_id = {task["task_id"]: task for task in tasks}
        group_ids, grouped_tasks = set(), set()
        for group in groups:
            if (
                group["group_id"] in group_ids
                or len(group["task_ids"]) != 2
                or len(set(group["task_ids"])) != 2
            ):
                raise ValueError("画像对照必须有唯一组号及两个不同成员")
            group_ids.add(group["group_id"])
            members = [tasks_by_id.get(task_id) for task_id in group["task_ids"]]
            if any(member is None for member in members):
                raise ValueError("画像对照成员缺失")
            if (
                len({member["profile_user_id"] for member in members}) != 2
                or any(
                    member["split"] != group["split"]
                    or member.get("contrast_group_id") != group["group_id"]
                    for member in members
                )
                or len({member["turns"][0]["user_message"] for member in members}) != 1
                or members[0]["turns"][0]["gold"]["hard"] != members[1]["turns"][0]["gold"]["hard"]
                or any(
                    member.get("statistical_cluster_id") != group["statistical_cluster_id"]
                    for member in members
                )
                or grouped_tasks.intersection(group["task_ids"])
            ):
                raise ValueError("画像对照必须同需求、同集合、不同真实用户且共享统计簇")
            grouped_tasks.update(group["task_ids"])
        if grouped_tasks != {task["task_id"] for task in tasks if task.get("contrast_group_id")}:
            raise ValueError("画像对照任务与组清单不一致")
    if not tasks:
        raise ValueError("任务集为空")
    if benchmark["manifest"].get("quality_label_status") == "complete_human_labels" and any(
        not turn["gold"].get("quality_judgments") for task in tasks for turn in task["turns"]
    ):
        raise ValueError("不能仅修改状态宣称独立质量标注已全部完成")
    if benchmark["manifest"].get("human_reviewed") and any(
        task.get("review_status") != "approved" for task in tasks
    ):
        raise ValueError("不能把待审核种子声明成人工验证集")
    return {
        "catalog_count": len(catalog),
        "task_count": len(tasks),
        "family_count": len(families),
        "turn_count": sum(len(task["turns"]) for task in tasks),
        "split_counts": dict(Counter(task["split"] for task in tasks)),
        "kind_counts": dict(Counter(task["kind"] for task in tasks)),
        "human_reviewed": bool(benchmark["manifest"].get("human_reviewed")),
        "profile_count": len(profiles),
    }


def load_benchmark(path):
    benchmark = json.loads(Path(path).read_text(encoding="utf-8"))
    validate_benchmark(benchmark)
    return benchmark


def build_benchmark(
    sources, *, catalog_limit=200, max_scan_rows=10000, currency="SOURCE_UNIT", family_limit=10
):
    """默认生成 10 个 family × 4 个任务，可扩大任务族。原始单位不擅自解释成货币。"""
    if catalog_limit < 40 or max_scan_rows < catalog_limit:
        raise ValueError("种子生成至少需要 40 商品，扫描上限不能低于目录上限")
    if type(family_limit) is not int or family_limit < 10:
        raise ValueError("family_limit 必须是至少 10 的整数")
    catalog, seen, evidence = [], set(), []
    for source in sources:
        prefix_hash, scanned = hashlib.sha256(), 0
        with Path(source).open("rb") as stream:
            for raw in stream:
                scanned += 1
                prefix_hash.update(raw)
                row = json.loads(raw)
                item_id = row.get("parent_asin")
                price = row.get("price")
                try:
                    price = float(price) if not isinstance(price, bool) else float("nan")
                except (ValueError, TypeError):
                    price = float("nan")
                categories = row.get("categories") or []
                if (
                    item_id
                    and item_id not in seen
                    and row.get("title")
                    and categories
                    and row.get("main_category") != "Books"
                    and math.isfinite(price)
                    and price > 0
                ):
                    item = {
                        "item_id": str(item_id),
                        "title": row["title"],
                        "category": categories[-1],
                        "category_path": categories,
                        "price": price,
                        "currency": currency,
                        "store": row.get("store"),
                        "source": {
                            "dataset": row.get("dataset", "provided_metadata"),
                            "file": Path(source).name,
                            "row": scanned,
                            "parent_asin": str(item_id),
                        },
                    }
                    details = row.get("details") or {}
                    if isinstance(details.get("Color"), str):
                        item["color"] = details["Color"].strip()
                    catalog.append(item)
                    seen.add(item_id)
                if len(catalog) >= catalog_limit or scanned >= max_scan_rows:
                    break
        evidence.append(
            {
                "path": str(Path(source).resolve()),
                "scanned_rows": scanned,
                "scanned_prefix_sha256": prefix_hash.hexdigest(),
            }
        )
        if len(catalog) >= catalog_limit:
            break
    groups = defaultdict(list)
    for item in catalog:
        groups[item["category"]].append(item)
    selected = sorted(
        (items for items in groups.values() if len(items) >= 2),
        key=lambda items: (-len(items), items[0]["category"]),
    )[:family_limit]
    if len(selected) < family_limit:
        raise ValueError(f"仅 {len(selected)} 个具有至少两个商品的类目；请提高目录/扫描上限")
    tasks = []
    for index, items in enumerate(selected):
        items.sort(key=lambda item: (item["price"], item["item_id"]))
        anchor = items[len(items) // 2]
        category = anchor["category"]
        budget = max(item["price"] for item in items)
        cheaper = items[max(0, len(items) // 2 - 1)]["price"]
        family = f"family-{index:02d}"
        split = (
            "train"
            if index < int(family_limit * 0.6)
            else "dev"
            if index < int(family_limit * 0.8)
            else "test"
        )
        hard = [
            {"field": "category", "op": "eq", "value": category},
            {"field": "currency", "op": "eq", "value": currency},
            {"field": "price", "op": "lte", "value": budget},
        ]
        soft = [{"field": "price", "op": "minimize", "best": 0, "worst": budget, "weight": 1}]
        base_gold = {"k": 2, "hard": hard, "soft": soft}
        message = f"请从目录的“{category}”类目推荐2件不同商品，原始价格不超过{budget:g} {currency}，不换算货币。在满足条件的商品中尽量便宜，最合适的排前面。若不足2件，说明不足，不要凑数。"

        def add(kind, turns, config=None):
            tasks.append(
                {
                    "task_id": f"{family}-{kind}",
                    "family_id": family,
                    "split": split,
                    "kind": kind,
                    "review_status": "pending",
                    "anchor_item_id": anchor["item_id"],
                    "environment": config or {},
                    "turns": turns,
                }
            )

        def turn(text, gold):
            return {"user_message": text, "limit": gold["k"], "gold": copy.deepcopy(gold)}

        add("clear", [turn(message, base_gold)])
        preference = copy.deepcopy(base_gold)
        preference["soft"] = [
            dict(soft[0], weight=0.7),
            {"field": "store", "op": "eq", "value": anchor.get("store"), "weight": 0.3},
        ]
        if anchor.get("store"):
            preferred_message = (
                message + f"同时偏好店铺“{anchor['store']}”。便宜程度和店铺偏好的重要性为7:3。"
            )
        else:
            preference = copy.deepcopy(base_gold)
            preferred_message = message + "不限定店铺。"
        add(
            "preference",
            [turn(preferred_message, preference)],
            {"unavailable_tools": ["rag_support", "rag_evidence_search"]} if index == 0 else None,
        )
        revised = copy.deepcopy(base_gold)
        revised["hard"][-1]["value"] = cheaper
        revised["soft"][0]["worst"] = cheaper
        add(
            "budget_change",
            [
                turn(message, base_gold),
                turn(
                    f"预算收紧到{cheaper:g} {currency}，其他要求保持不变。价格无法确认就不要当作符合预算。",
                    revised,
                ),
            ],
        )
        if index % 2 == 0:
            add(
                "exclude_previous",
                [
                    turn(message, base_gold),
                    dict(
                        turn(
                            "请再推荐2件，之前推荐过的商品都不要，其他要求不变。若剩余商品不足2件，明确说明。",
                            base_gold,
                        ),
                        exclude_previous=True,
                    ),
                ],
            )
        elif index in {7, 9}:
            unknown = copy.deepcopy(base_gold)
            unknown["hard"].append({"field": "warranty_years", "op": "gte", "value": 5})
            add(
                "unknown_attribute",
                [
                    turn(
                        message
                        + "还必须有至少5年保修。无法确认时请说明信息不足，不要说成确定没有符合的商品。",
                        unknown,
                    )
                ],
            )
        else:
            impossible = copy.deepcopy(base_gold)
            impossible["hard"][-1]["value"] = round(items[0]["price"] / 2, 6)
            add(
                "no_match",
                [
                    turn(
                        f"请推荐2件“{category}”，预算每件不超过{impossible['hard'][-1]['value']:g} {currency}。如果目录中没有满足条件的，明确说明没有匹配商品，不要推荐超预算的。",
                        impossible,
                    )
                ],
            )
    benchmark = {
        "schema_version": "rs-skill-benchmark/1",
        "catalog": catalog,
        "tasks": tasks,
        "environment": {
            "tool_call_budget": 16,
            "profile_preferences": {},
            "session_preferences": {},
            "catalog_scope": "frozen_fixture_only",
            "retrieval": "lexical_then_price_v1",
            "network_policy": "fixture_tools_local_only; model_endpoint_explicit",
            "task_timeout_seconds": 180,
        },
        "manifest": {
            "builder_version": "grounded-seeds/1",
            "human_reviewed": False,
            "builder_parameters": {
                "catalog_limit": catalog_limit,
                "max_scan_rows": max_scan_rows,
                "family_limit": family_limit,
                "currency": currency,
            },
            "currency": currency,
            "currency_interpretation": "explicit_source_unit; no_fx_conversion",
            "sampling": "bounded_source_prefix; category_grouped; not_population_representative",
            "sources": evidence,
            "catalog_sha256": fingerprint(catalog),
            "gold_policy": "hidden; current_turn_only; exclude_previous_resolved_from_actual_answers",
        },
    }
    validate_benchmark(benchmark)
    return benchmark
