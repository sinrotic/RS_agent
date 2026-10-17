"""补足诊断场景与评测就绪证据，不把工程通过或合成标注当成人工校准。"""

import copy
import random
import statistics
import html
import math
from collections import Counter, defaultdict

from .dataset import fingerprint, validate_benchmark
from .scoring import evaluate_turn, scorer_fingerprint


def calibration_passes(report, benchmark_sha256):
    """已冻结数据与当前评分器的校准收据；阈值来自评测规则，不接受只翻转 passed。"""
    if not isinstance(report, dict):
        return False
    pairs, families = report.get("valid_reviewed_pairs"), report.get("reviewed_families")
    agreement, interval = report.get("agreement"), report.get("agreement_family_bootstrap_95pct")

    def finite_number(value):
        return type(value) in (int, float) and math.isfinite(value)

    if (
        type(pairs) is not int
        or type(families) is not int
        or not finite_number(agreement)
        or not isinstance(interval, list)
        or len(interval) != 2
        or not all(finite_number(value) for value in interval)
    ):
        return False
    return bool(
        report.get("passed") is True
        and report.get("review_origin") == "human"
        and report.get("benchmark_sha256") == benchmark_sha256
        and report.get("scorer_sha256") == scorer_fingerprint()
        and pairs >= 30
        and 10 <= families <= pairs
        and type(report.get("invalid_pairs")) is int
        and report["invalid_pairs"] == 0
        and 0.8 <= agreement <= 1
        and 0.6 <= interval[0] <= interval[1] <= 1
        and report.get("human_labels_sha256")
        and report.get("scoring_key_sha256")
    )


def strengthen_benchmark(benchmark):
    """每个画像任务族加入无解、未知、可恢复工具故障与换类目 Session。"""
    validate_benchmark(benchmark)
    result = copy.deepcopy(benchmark)
    if not result.get("profiles") or result["manifest"].get("stress_suite_version"):
        raise ValueError("需要画像任务集，且压力任务不能重复添加")
    catalog = result["catalog"]
    groups = defaultdict(list)
    for item in catalog:
        groups[item["category"]].append(item)
    base_tasks = [task for task in result["tasks"] if task["kind"] == "personalized"]
    if not base_tasks:
        raise ValueError("缺少 personalized 基础任务")
    for index, base in enumerate(base_tasks):
        gold = copy.deepcopy(base["turns"][0]["gold"])
        profile = result["profiles"][base["profile_user_id"]]
        allowed = gold["hard"][0]["value"]
        feasible_items = [
            item
            for item in catalog
            if item["category"] in allowed and item["item_id"] not in profile["seen_item_ids"]
        ]

        def add(kind, turns, environment=None):
            task = copy.deepcopy(base)
            task.update(
                task_id=f"{base['family_id']}-{kind}",
                kind=kind,
                turns=turns,
                environment=environment or {},
                review_status="pending",
            )
            result["tasks"].append(task)

        def turn(message, current_gold):
            return {"user_message": message, "limit": current_gold["k"], "gold": current_gold}

        impossible = copy.deepcopy(gold)
        budget = min(item["price"] for item in feasible_items) / 2
        impossible["hard"][2]["value"] = budget
        impossible["soft"][0]["worst"] = budget
        add(
            "no_match",
            [
                turn(
                    base["turns"][0]["user_message"]
                    + f"预算改为每件最多{budget:g} {gold['hard'][1]['value']}。没有符合条件的商品时明确说明，不要推荐超预算商品。",
                    impossible,
                )
            ],
        )
        unknown = copy.deepcopy(gold)
        if any(item.get("warranty_years") is not None for item in feasible_items):
            raise ValueError("未知保修任务要求当前冻结目录确实缺少保修证据")
        unknown["hard"].append({"field": "warranty_years", "op": "gte", "value": 5})
        add(
            "unknown_attribute",
            [
                turn(
                    base["turns"][0]["user_message"]
                    + "另外必须有至少5年保修；如果无法确认，请说明信息不足，不要推断成肯定符合或肯定没有符合商品。",
                    unknown,
                )
            ],
        )
        add(
            "tool_unavailable",
            copy.deepcopy(base["turns"]),
            {
                "unavailable_tools": ["recommend_semantic_recall"],
                "fault_policy": "remaining_recall_tools_available",
            },
        )
        alternatives = [
            category
            for category in sorted(groups)
            if category not in allowed
            and any(item["item_id"] not in profile["seen_item_ids"] for item in groups[category])
        ]
        if not alternatives:
            raise ValueError("目录缺少可验证的换类目候选")
        new_category = alternatives[index % len(alternatives)]
        new_budget = max(
            item["price"]
            for item in groups[new_category]
            if item["item_id"] not in profile["seen_item_ids"]
        )
        switched = copy.deepcopy(gold)
        switched["hard"][0]["value"] = [new_category]
        switched["hard"][2]["value"] = new_budget
        switched["soft"][0]["worst"] = new_budget
        add(
            "category_switch",
            [
                copy.deepcopy(base["turns"][0]),
                turn(
                    f"现在换个方向，只推荐“{new_category}”类目，每件预算改为{new_budget:g} {gold['hard'][1]['value']}。数量和历史排除要求不变，继续按之前的偏好与价格权重排序；不要沿用之前的类目限制。不足数量时明确说明。",
                    switched,
                ),
            ],
        )
    # 预算仍是硬上限；软价格标尺的零点留在 1.1B，避免可行但无已知偏好的商品全为零。
    for task in result["tasks"]:
        for turn in task["turns"]:
            budget = next(
                criterion["value"]
                for criterion in turn["gold"]["hard"]
                if criterion["field"] == "price" and criterion["op"] == "lte"
            )
            for criterion in turn["gold"].get("soft", []):
                if criterion["field"] == "price" and criterion["op"] == "minimize":
                    criterion["worst"] = budget * 1.1
            turn["user_message"] += (
                "便宜程度按1−原价/(当前预算×1.1)归一化；预算仍是不得超过的硬条件。"
            )
    result["tasks"].sort(key=lambda task: (task["family_id"], task["kind"]))
    result["manifest"].update(
        stress_suite_version="personalized-stress/1",
        human_reviewed=False,
        scoring_calibration_required=True,
        scoring_calibration={"status": "pending_human_labels", "passed": False},
        readiness_policy="human_task_review_and_independent_scoring_calibration_before_promotion",
    )
    result["manifest"]["profile_scoring_policy"] = (
        "past_frequency/max_frequency; category_.35_store_.35_price_.30; price=1-price/(1.1*budget); no_store_category_.70"
    )
    result["manifest"]["price_scale_policy"] = {
        "zero_utility_budget_multiplier": 1.1,
        "hard_budget_unchanged": True,
        "reason": "nonzero_gain_for_affordable_items_with_unknown_preference",
    }
    validate_benchmark(result)
    return result


def build_calibration_bundle(benchmark, *, pair_limit=60, seed=42):
    """盲审非保留任务的配对结果；公式键分离保存，不自动生成或批准真人标签。"""
    validate_benchmark(benchmark)
    if type(pair_limit) is not int or pair_limit < 1 or type(seed) is not int:
        raise ValueError("校准数量/种子无效")
    candidates = [task for task in benchmark["tasks"] if task["split"] == "dev"]
    if not candidates:
        candidates = [task for task in benchmark["tasks"] if task["split"] == "train"]
    if not candidates:
        raise ValueError("不能使用保留测试集进行校准")
    groups = defaultdict(list)
    for task in candidates:
        groups[task["family_id"]].append(task)
    rng = random.Random(seed)
    families = sorted(groups)
    rng.shuffle(families)
    for tasks in groups.values():
        rng.shuffle(tasks)
    ordered = [
        groups[family][index]
        for index in range(max(map(len, groups.values())))
        for family in families
        if index < len(groups[family])
    ][:pair_limit]
    if benchmark.get("contrast_groups"):
        # 现有开发用户未必有两种相反且目录可供的偏好；把非测试的画像对照
        # 优先加入盲审，不用测试集补校准，也不让新规则被大量旧任务淹没。
        priority = sorted(
            (
                task
                for task in benchmark["tasks"]
                if task["split"] != "test" and task.get("contrast_group_id")
            ),
            key=lambda task: (task["family_id"], task["kind"], task["task_id"]),
        )
        prioritized_ids = {task["task_id"] for task in priority}
        ordered = (priority + [task for task in ordered if task["task_id"] not in prioritized_ids])[
            :pair_limit
        ]
    catalog = benchmark["catalog"]
    facts = {item["item_id"]: item for item in catalog}
    dataset_hash = fingerprint(benchmark)
    queue, scoring, labels = [], [], []
    for index, task in enumerate(ordered):
        turn_index = (
            0
            if task["kind"] in {"personalized_exclude_previous", "reject_previous"}
            or task["turns"][0]["gold"].get("customer_policy", {}).get("action")
            in {"clarify", "recommend_or_clarify"}
            else len(task["turns"]) - 1
        )
        if task["kind"] == "compatibility_unknown" and index % 2:
            turn_index = len(task["turns"]) - 1
        gold = task["turns"][turn_index]["gold"]
        diagnostic = evaluate_turn(catalog, gold, {"item_ids": list(facts), "outcome": "recommend"})
        feasible = [grade for grade in diagnostic["items"] if grade["hard_pass"]]
        ranked = sorted(feasible, key=lambda grade: (-grade["relevance"], grade["item_id"]))
        count, outcome = diagnostic["required_count"], diagnostic["expected_outcome"]
        limitation = (
            "no_matches"
            if outcome == "no_match"
            else "unknown_attributes"
            if outcome == "uncertain_match"
            else "insufficient_matches"
            if count < gold["k"]
            else None
        )
        reference = {
            "item_ids": [grade["item_id"] for grade in ranked[:count]],
            "outcome": outcome,
            "limitations": [limitation] if limitation else [],
            "message": "目录中没有符合已知要求的商品。"
            if outcome == "no_match"
            else "信息不足，无法确认必须的属性。"
            if outcome == "uncertain_match"
            else "符合条件的商品数量不足，未凑数。"
            if limitation
            else "推荐以下商品。",
        }
        if gold.get("customer_policy", {}).get("action") in {"clarify", "defer"}:
            from .customer import customer_reference

            reference = customer_reference(gold)
        if ranked:
            cheap = sorted(
                feasible, key=lambda grade: (facts[grade["item_id"]]["price"], grade["item_id"])
            )
            other_ids = [grade["item_id"] for grade in cheap[:count]]
            if other_ids == reference["item_ids"]:
                other_ids = [grade["item_id"] for grade in ranked[-count:]][::-1]
            other = dict(reference, item_ids=other_ids)
        else:
            other = {
                "item_ids": [task["anchor_item_id"]],
                "outcome": "recommend",
                "limitations": [],
                "message": "推荐以下商品，它符合全部要求。",
            }
        answers = [reference, other]
        rng.shuffle(answers)
        grades = [evaluate_turn(catalog, gold, answer) for answer in answers]
        values = [
            (grade["success"], grade["task_score"] if grade["ranking_applicable"] else 0)
            for grade in grades
        ]
        preference = "A" if values[0] > values[1] else "B" if values[1] > values[0] else "tie"
        pair_id = f"calibration-{index:03d}"

        def display(answer):
            return {
                "message": answer["message"],
                "outcome": answer["outcome"],
                "items": [copy.deepcopy(facts[item]) for item in answer["item_ids"]],
            }

        queue.append(
            {
                "pair_id": pair_id,
                "task_id": task["task_id"],
                "family_id": task["family_id"],
                "statistical_cluster_id": task.get("statistical_cluster_id", task["family_id"]),
                "split": task["split"],
                "kind": task["kind"],
                "turn_index": turn_index,
                "user_messages": [turn["user_message"] for turn in task["turns"][: turn_index + 1]],
                "profile": copy.deepcopy(benchmark["profiles"][task["profile_user_id"]]),
                "candidate_a": display(answers[0]),
                "candidate_b": display(answers[1]),
            }
        )
        scoring.append(
            {
                "pair_id": pair_id,
                "task_id": task["task_id"],
                "family_id": task["family_id"],
                "statistical_cluster_id": task.get("statistical_cluster_id", task["family_id"]),
                "formula_preference": preference,
                "candidate_a": grades[0],
                "candidate_b": grades[1],
            }
        )
        labels.append(
            {
                "pair_id": pair_id,
                "preference": None,
                "reviewer_id": None,
                "reason": None,
                "review_origin": "human",
                "request_valid": None,
            }
        )
    review_queue = {
        "schema_version": "rs-skill-calibration-queue/1",
        "benchmark_sha256": dataset_hash,
        "instructions": "独立判断哪组结果更符合用户要求和过去偏好，填写 A/B/tie/invalid，并说明理由；先判断预算、类目、数量、未知属性等硬要求。不要读取 scoring-key.json；invalid 表示需求或标注本身不合理。",
        "candidate_origin": "deterministic_formula_and_control_recommenders; not_real_agent_outputs",
        "pairs": queue,
    }
    if benchmark["manifest"].get("task_design"):
        review_queue["instructions"] = (
            "根据当前顾客明确要求独立判断 A/B/tie/invalid，并填写理由和需求是否合理。"
            "缺少关键信息时检查问题是否必要、是否重复已知信息、是否过多；顾客不知道设备型号时应提供核实步骤而非保证兼容。"
            "没有明确价格或店铺优先要求时，满足硬条件的候选可以并列；未经顾客确认的历史偏好不作硬条件或主分。"
            "顾客明确确认过去店铺偏好时才按当前明确优先要求判断；送礼和替别人购买不要套用本人历史。"
            "不要读取 scoring-key.json；invalid 表示需求、类目表达或标注本身不合理。"
        )
        if benchmark.get("contrast_groups"):
            review_queue["instructions"] += (
                "顾客公开授权按过去习惯选择时，检查同类目内的历史证据与商品属性是否匹配；"
                "记录次数少或属性覆盖不足不能当成稳定偏好。顾客改变要求或送礼时，当前要求与收礼人优先。"
                "本包优先收录非测试集画像对照，包含训练对照及开发任务；评分仍是待校准代理。"
            )
        if benchmark["manifest"].get("builder_version") == "natural-profile-customer-scenarios/1":
            review_queue["instructions"] = (
                "独立判断 A/B/tie/invalid，填写理由和需求是否合理；不要读取 scoring-key.json。"
                "画像由已绑定且允许使用的环境提供，不需要顾客台词授权。历史频率是弱证据，不是本次隐藏硬要求；"
                "正向评价不证明购买、稳定喜好或真实满意度。当前要求和收礼人优先。"
                "关键兼容信息缺失必须澄清；低风险偏好既可先给保守参考，也可问一个相关问题，不因历史条数少强制提问。"
                "参考分仅表示当前条件满足；若你觉得代理无法区分推荐质量，请在理由中指出并填写独立相关性标注包。"
                "原始币种未确认，所有预算按目录标价单位理解。invalid 用于表达、类目或标注错误，不是对模型不满意。"
            )
        # instructions 属于盲审材料本身，必须在计算绑定指纹前冻结。
        queue_hash = fingerprint(review_queue)
    else:
        queue_hash = fingerprint(review_queue)
    return {
        "review_queue": review_queue,
        "review_markdown": _render_review(review_queue),
        "scoring_key": {
            "schema_version": "rs-skill-calibration-key/1",
            "benchmark_sha256": dataset_hash,
            "scorer_sha256": scorer_fingerprint(),
            "review_queue_sha256": queue_hash,
            "pairs": scoring,
        },
        "labels_template": {
            "schema_version": "rs-skill-calibration-labels/1",
            "benchmark_sha256": dataset_hash,
            "review_queue_sha256": queue_hash,
            "ratings": labels,
        },
    }


def _render_review(queue):
    def cell(value):
        text = (
            html.escape(str(value if value is not None else "未知"))
            .replace("\n", " ")
            .replace("\r", " ")
        )
        for character in "\\|[]!*`_":
            text = text.replace(character, "\\" + character)
        return text

    lines = [
        "# 推荐评分人工盲审",
        "",
        queue["instructions"],
        "",
        "填写 labels.json 中对应 pair_id 的 preference、reviewer_id、reason 和 request_valid。候选是确定性对照结果，不是真实 Agent 输出；这里不展示公式分或正确选项。",
        "",
    ]
    for pair in queue["pairs"]:
        lines.extend(
            [
                f"## 配对 {pair['pair_id']}",
                "",
                f"任务类型：{pair['kind']}，集合：{pair['split']}。",
                "",
            ]
        )
        for index, message in enumerate(pair["user_messages"]):
            lines.extend([f"用户表达 {index + 1}：{cell(message)}", ""])
        profile = pair["profile"]
        preferences = profile["profile_preferences"]
        lines.extend(["过去正向历史偏好：", "", "| 维度 | 值 | 次数 |", "| --- | --- | ---: |"])
        for field, title in (("category_counts", "类目"), ("store_counts", "店铺")):
            for value, count in preferences.get(field, {}).items():
                lines.append(f"| {title} | {cell(value)} | {count} |")
        lines.extend(
            [
                "",
                f"历史交互数：{profile.get('activity_count', '未知')}；可回填正向历史：{profile.get('history_metadata_count', len(profile['history']))}。",
                "",
            ]
        )
        for label, candidate in (("A", pair["candidate_a"]), ("B", pair["candidate_b"])):
            lines.extend([f"### 候选 {label}", "", cell(candidate["message"]), ""])
            if candidate["items"]:
                lines.extend(
                    [
                        "| 顺序 | 商品 ID | 标题 | 类目 | 店铺 | 原始价格 | 币种 | 保修年数 |",
                        "| ---: | --- | --- | --- | --- | ---: | --- | --- |",
                    ]
                )
                for position, item in enumerate(candidate["items"], 1):
                    values = [
                        position,
                        item["item_id"],
                        item.get("title"),
                        item.get("category"),
                        item.get("store"),
                        item.get("price"),
                        item.get("currency"),
                        item.get("warranty_years"),
                    ]
                    lines.append("| " + " | ".join(cell(value) for value in values) + " |")
                lines.append("")
            else:
                lines.extend(["没有推荐商品。", ""])
        lines.extend(
            ["判断：A / B / tie / invalid。请注明硬约束、偏好权衡或需求不合理的具体理由。", ""]
        )
    return "\n".join(lines)


def evaluate_calibration(scoring_key, human_labels):
    """只接受显式人审输入；按画像任务族评估一致性，不能证明标记者身份或线上效果。"""
    for field in ("benchmark_sha256", "review_queue_sha256"):
        if scoring_key.get(field) != human_labels.get(field) or not scoring_key.get(field):
            raise ValueError("校准输入指纹不一致")
    pairs = {pair["pair_id"]: pair for pair in scoring_key["pairs"]}
    if len(pairs) != len(scoring_key["pairs"]):
        raise ValueError("公式键存在重复 pair_id")
    seen, families, disagreements = set(), defaultdict(list), []
    reviewed, invalid = 0, 0
    for rating in human_labels["ratings"]:
        pair_id = rating["pair_id"]
        if pair_id not in pairs or pair_id in seen:
            raise ValueError("人审 pair_id 未知或重复")
        seen.add(pair_id)
        preference = rating.get("preference")
        if preference is None:
            continue
        if rating.get("review_origin") != "human":
            raise ValueError("校准仅接受 human 标签，不能用公式或模型伪造人工审核")
        if (
            preference not in {"A", "B", "tie", "invalid"}
            or not rating.get("reviewer_id")
            or not rating.get("reason")
        ):
            raise ValueError("人审标签缺少有效偏好、审核人或理由")
        if type(rating.get("request_valid")) is not bool:
            raise ValueError("人审必须明确需求是否合理")
        reviewed += 1
        if preference == "invalid" or not rating["request_valid"]:
            invalid += 1
            disagreements.append(
                {"pair_id": pair_id, "reason": rating["reason"], "type": "invalid_task"}
            )
            continue
        agrees = preference == pairs[pair_id]["formula_preference"]
        families[pairs[pair_id].get("statistical_cluster_id", pairs[pair_id]["family_id"])].append(
            float(agrees)
        )
        if not agrees:
            disagreements.append(
                {
                    "pair_id": pair_id,
                    "human_preference": preference,
                    "formula_preference": pairs[pair_id]["formula_preference"],
                    "reason": rating["reason"],
                    "type": "scoring_disagreement",
                }
            )
    values = [value for group in families.values() for value in group]
    agreement = statistics.mean(values) if values else None
    interval = None
    if families:
        groups = list(families.values())
        rng, samples = random.Random(0), []
        for _ in range(2000):
            sample = [value for group in rng.choices(groups, k=len(groups)) for value in group]
            samples.append(statistics.mean(sample))
        samples.sort()
        interval = [samples[50], samples[1950]]
    blockers = []
    if len(values) < 30:
        blockers.append("fewer_than_30_valid_human_pairs")
    if len(families) < 10:
        blockers.append("fewer_than_10_independent_reviewed_users")
    if invalid:
        blockers.append("invalid_tasks_need_correction")
    if agreement is None or agreement < 0.8 or interval[0] < 0.6:
        blockers.append("formula_human_agreement_not_established")
    return {
        "schema_version": "rs-skill-calibration-report/1",
        "benchmark_sha256": scoring_key["benchmark_sha256"],
        "scorer_sha256": scoring_key.get("scorer_sha256"),
        "review_queue_sha256": scoring_key["review_queue_sha256"],
        "scoring_key_sha256": fingerprint(scoring_key),
        "human_labels_sha256": fingerprint(human_labels),
        "review_origin": "human",
        "reviewed_pairs": reviewed,
        "valid_reviewed_pairs": len(values),
        "invalid_pairs": invalid,
        "reviewed_families": len(families),
        "agreement": agreement,
        "agreement_family_bootstrap_95pct": interval,
        "disagreements": disagreements,
        "policy": {
            "min_valid_pairs": 30,
            "min_independent_families": 10,
            "min_agreement": 0.8,
            "min_bootstrap_lower": 0.6,
            "note": "engineering_acceptance_thresholds; not_guaranteed_business_validity",
        },
        "passed": not blockers,
        "blockers": blockers,
        "auto_deploy": False,
    }


def audit_benchmark(benchmark, calibration_report=None):
    """审核统计/参考路径/评分区分度；公式参考不是 Agent 能力或真人满意度。"""
    summary = validate_benchmark(benchmark)
    dataset_hash = fingerprint(benchmark)
    catalog = benchmark["catalog"]
    facts = {item["item_id"]: item for item in catalog}
    outcomes, failures, zero_idcg, cheap_scores = Counter(), [], [], []
    for task in benchmark["tasks"]:
        previous = []
        for index, turn in enumerate(task["turns"]):
            gold = copy.deepcopy(turn["gold"])
            if turn.get("exclude_previous"):
                gold["hard"].append(
                    {"field": "item_id", "op": "not_in", "value": list(dict.fromkeys(previous))}
                )
            if gold.get("customer_policy", {}).get("action") in {"clarify", "defer"}:
                from .customer import customer_reference

                grade = evaluate_turn(catalog, gold, customer_reference(gold))
                outcomes[grade["expected_outcome"]] += 1
                if not grade["success"]:
                    failures.append(
                        {
                            "task_id": task["task_id"],
                            "turn_index": index,
                            "violations": grade["violations"],
                        }
                    )
                continue
            diagnostic = evaluate_turn(
                catalog, gold, {"item_ids": list(facts), "outcome": "recommend"}
            )
            feasible = [grade for grade in diagnostic["items"] if grade["hard_pass"]]
            feasible.sort(key=lambda grade: (-grade["relevance"], grade["item_id"]))
            count, outcome = diagnostic["required_count"], diagnostic["expected_outcome"]
            outcomes[outcome] += 1
            limitation = (
                "no_matches"
                if outcome == "no_match"
                else "unknown_attributes"
                if outcome == "uncertain_match"
                else "insufficient_matches"
                if count < gold["k"]
                else None
            )
            reference = {
                "item_ids": [item["item_id"] for item in feasible[:count]],
                "outcome": outcome,
                "limitations": [limitation] if limitation else [],
                "message": "公式参考路径明确说明数量或事实限制。",
            }
            grade = evaluate_turn(catalog, gold, reference)
            if not grade["success"]:
                failures.append(
                    {
                        "task_id": task["task_id"],
                        "turn_index": index,
                        "violations": grade["violations"],
                    }
                )
            if outcome == "recommend" and not grade["ranking_applicable"]:
                zero_idcg.append({"task_id": task["task_id"], "turn_index": index})
            if grade["ranking_applicable"]:
                cheap = sorted(
                    feasible, key=lambda item: (facts[item["item_id"]]["price"], item["item_id"])
                )[:count]
                cheap_grade = evaluate_turn(
                    catalog, gold, dict(reference, item_ids=[item["item_id"] for item in cheap])
                )
                cheap_scores.append(cheap_grade["task_score"])
            previous.extend(reference["item_ids"])
    users = {
        split: len(
            {
                task.get("profile_user_id", task["family_id"])
                for task in benchmark["tasks"]
                if task["split"] == split
            }
        )
        for split in ("train", "dev", "test")
    }
    calibrated = calibration_passes(calibration_report, dataset_hash)
    blockers = []
    if not summary["human_reviewed"]:
        blockers.append("human_task_review_pending")
    if not calibrated:
        blockers.append("scoring_calibration_pending")
    if users["test"] < 20:
        blockers.append("fewer_than_20_independent_test_users")
    if failures:
        blockers.append("formula_reference_path_failed")
    if zero_idcg:
        blockers.append("zero_idcg_recommendation_turns_need_review")
    if benchmark["manifest"].get("catalog_curation", {}).get("full_semantic_review") == "pending":
        blockers.append("full_catalog_semantic_review_pending")
    if benchmark["manifest"].get("independent_relevance_status") not in {
        None,
        "complete_human_labels",
    }:
        blockers.append(
            "independent_relevance_pending; no_validated_personalization_quality_objective"
        )
    return {
        "schema_version": "rs-skill-readiness-audit/1",
        "benchmark_sha256": dataset_hash,
        "summary": summary,
        "independent_users_per_split": users,
        "independent_statistical_clusters_per_split": {
            split: len(
                {
                    task.get("statistical_cluster_id", task["family_id"])
                    for task in benchmark["tasks"]
                    if task["split"] == split
                }
            )
            for split in ("train", "dev", "test")
        },
        "profile_contrast_groups_per_split": {
            split: dict(
                Counter(
                    group["kind"]
                    for group in benchmark.get("contrast_groups", [])
                    if group["split"] == split
                )
            )
            for split in ("train", "dev", "test")
        },
        "catalog_curation": benchmark["manifest"].get("catalog_curation"),
        "outcome_turn_counts": dict(outcomes),
        "reference_path_failures": failures,
        "zero_idcg_recommendation_turns": zero_idcg,
        "profile_history_metadata_min": min(
            (
                p.get("history_metadata_count", len(p["history"]))
                for p in benchmark.get("profiles", {}).values()
            ),
            default=0,
        ),
        "formula_controls": {
            "origin": "not_real_agent; diagnostic_only; oracle_exclusion_path",
            "price_only_mean_ranking_score": statistics.mean(cheap_scores)
            if cheap_scores
            else None,
            "price_only_nonoptimal_turns": sum(score < 99.999 for score in cheap_scores),
            "ranking_turns": len(cheap_scores),
        },
        "ready_for_baseline_diagnostics": not failures,
        "ready_for_validated_skill_iteration": not blockers,
        "readiness_blockers": blockers,
        "auto_deploy": False,
    }
