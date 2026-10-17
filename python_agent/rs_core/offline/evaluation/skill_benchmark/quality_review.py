"""双人独立质量标注、分歧裁决与盲审校准；模型不能批准自己的金标准。"""

import copy
from collections import Counter, defaultdict

from .dataset import fingerprint, validate_benchmark
from .quality_dataset import SEMANTIC_DIMENSIONS, task_catalog
from .quality_scoring import quality_fingerprint, validate_quality_labels
from .scoring import _item_grade


def _context(benchmark, task, index, extra_item_ids=()):
    environment = dict(benchmark["environment"], **task.get("environment", {}))
    profile = benchmark.get("profiles", {}).get(task.get("profile_user_id"), {})
    if not environment.get("profile_access", {}).get("allowed", True):
        profile = {}
    catalog = task_catalog(benchmark["catalog"], environment)
    hard = task["turns"][index]["gold"]["hard"]
    category_conditions = [condition for condition in hard if condition["field"] in {"category", "category_path"}
                           and condition["op"] == "eq"]
    # 展示相关类目完整事实，保留全环境哈希；避免每道题复制900件无关商品。
    relevant = [item for item in catalog if item["item_id"] in extra_item_ids
                or all(item.get(condition["field"]) == condition["value"] for condition in category_conditions)]
    return {"customer": [turn["user_message"] for turn in task["turns"][:index + 1]],
            "profile": copy.deepcopy(profile),
            "catalog": copy.deepcopy(relevant), "catalog_sha256": fingerprint(catalog)}


def build_quality_review(benchmark, *, splits=("train", "dev"), task_limit=60, include_test=False):
    validate_benchmark(benchmark)
    if not splits or set(splits) - {"train", "dev", "test"} or ("test" in splits and not include_test):
        raise ValueError("隐藏测试标签必须显式 include_test，并与优化进程隔离保存")
    if task_limit is not None and (type(task_limit) is not int or task_limit < 1):
        raise ValueError("task_limit 必须是正整数或 None")
    groups = defaultdict(list)
    for task in benchmark["tasks"]:
        if task["split"] in splits:
            groups[(task.get("quality_scenario", "ordinary"), task["kind"])].append(task)
    selected, cluster_counts = [], Counter()
    # 场景分层轮转，避免只审最前面的类目或成功任务。
    while groups and (task_limit is None or len(selected) < task_limit):
        for key in sorted(list(groups)):
            if task_limit is not None and len(selected) >= task_limit:
                break
            position = min(range(len(groups[key])), key=lambda index: cluster_counts[
                groups[key][index].get("statistical_cluster_id", groups[key][index]["family_id"])])
            task = groups[key].pop(position)
            selected.append(task)
            cluster_counts[task.get("statistical_cluster_id", task["family_id"])] += 1
            if not groups[key]:
                del groups[key]
    entries = []
    for task in selected:
        for index, turn in enumerate(task["turns"]):
            context = _context(benchmark, task, index)
            feasible = {item["item_id"] for item in context["catalog"] if _item_grade(item, turn["gold"])["hard_pass"]}
            contract = turn["gold"]["quality_contract"]
            ratings = {dimension: {item: {"grade": None, "reason": None, "evidence": []} for item in sorted(feasible)}
                       if contract[required] else {}
                       for dimension, required in (("use_fit", "use_fit_required"), ("profile_fit", "profile_fit_required"))}
            entries.append({"task_id": task["task_id"], "turn_index": index,
                            "split": task["split"], "contract": copy.deepcopy(contract),
                            "context": context, "ratings_template": ratings, "reviews": [], "adjudication": None})
    return {"schema_version": "rs-independent-quality-review/1", "origin": "human",
            "benchmark_sha256": fingerprint(benchmark), "entries": entries,
            "contains_test_gold": "test" in splits, "auto_deploy": False,
            "instructions": "两名不同审核人各自填写 reviews：reviewer_id、origin=human、task_valid、reason、rubric、ratings。"
            "逐商品的用途/画像适合度0=不适合、1=勉强、2=合理、3=相对更适合，允许并列，证据不足保持null不批准。"
            "evidence 为 {source: customer|catalog|profile, quote: 原文}。历史正评不是购买或隐藏需求，送礼不迁移本人偏好。"
            "先独立提交再合并；分歧由第三位审核人填写 adjudication，禁止推荐模型或评价模型冒充人审。"}


def _human(row):
    if (not isinstance(row, dict) or row.get("origin") != "human"
            or not isinstance(row.get("reviewer_id"), str) or not row["reviewer_id"].strip()
            or not isinstance(row.get("reason"), str) or not row["reason"].strip()):
        raise ValueError("独立审核需要 human 来源、审核人和具体理由")
    return row["reviewer_id"]


def _consensus(entry, values):
    reviews = entry.get("reviews", [])
    if not isinstance(reviews, list) or len(reviews) != 2:
        raise ValueError("每条审核需要恰好两份独立初审")
    identities = [_human(row) for row in reviews]
    if len(set(identities)) != 2:
        raise ValueError("同一审核人不能扮演两名独立评审")
    if any(row.get("task_valid") is not True for row in reviews):
        raise ValueError("任务或事实无效，先修正题集，不批准标签")
    if values(reviews[0]) == values(reviews[1]):
        return reviews[0], identities
    decision = entry.get("adjudication")
    identity = _human(decision)
    if identity in identities or decision.get("task_valid") is not True:
        raise ValueError("分歧必须由第三名审核人独立裁决")
    return decision, identities + [identity]


def _validate_ratings(row, template, context):
    ratings = row.get("ratings")
    if not isinstance(ratings, dict) or set(ratings) != set(template):
        raise ValueError("用途和画像维度必须完整")
    import json

    sources = {name: json.dumps(value, ensure_ascii=False) for name, value in context.items()
               if name in {"customer", "catalog", "profile"}}
    for dimension, required in template.items():
        if not isinstance(ratings[dimension], dict) or set(ratings[dimension]) != set(required):
            raise ValueError("逐商品标注缺失或包含不可行商品")
        for rating in ratings[dimension].values():
            if (type(rating.get("grade")) is not int or not 0 <= rating["grade"] <= 3
                    or not isinstance(rating.get("reason"), str) or not rating["reason"].strip()
                    or not isinstance(rating.get("evidence"), list) or not rating["evidence"]):
                raise ValueError("未标注或无理由/证据的商品不能批准")
            for quote in rating["evidence"]:
                if (quote.get("source") not in sources or not isinstance(quote.get("quote"), str)
                        or not quote["quote"].strip() or quote["quote"] not in sources[quote["source"]]):
                    raise ValueError("人审证据必须存在于对应独立来源")


def apply_quality_reviews(benchmark, reviews):
    validate_benchmark(benchmark)
    result, used = copy.deepcopy(benchmark), set()
    tasks = {task["task_id"]: task for task in result["tasks"]}
    for pack in reviews:
        if (pack.get("schema_version") != "rs-independent-quality-review/1" or pack.get("origin") != "human"
                or pack.get("benchmark_sha256") != fingerprint(benchmark)):
            raise ValueError("质量标注包不属于当前冻结题集")
        for entry in pack.get("entries", []):
            if not entry.get("reviews"):
                continue
            key = entry.get("task_id"), entry.get("turn_index")
            task = tasks.get(key[0])
            if key in used or task is None or type(key[1]) is not int or not 0 <= key[1] < len(task["turns"]):
                raise ValueError("审核任务或轮次缺失/重复")
            used.add(key)
            context = _context(benchmark, task, key[1])
            if entry.get("context") != context or entry.get("split") != task["split"]:
                raise ValueError("标注事实或集合被改写")
            gold = task["turns"][key[1]]["gold"]
            if entry.get("contract") != gold["quality_contract"]:
                raise ValueError("标注契约被改写")
            # 从可信目录重新构造覆盖要求，不信任可编辑模板。
            feasible = {item["item_id"] for item in context["catalog"] if _item_grade(item, gold)["hard_pass"]}
            template = {dimension: dict.fromkeys(feasible) if gold["quality_contract"][required] else {}
                        for dimension, required in (("use_fit", "use_fit_required"), ("profile_fit", "profile_fit_required"))}
            for review in entry["reviews"]:
                _validate_ratings(review, template, context)
            chosen, identities = _consensus(entry, lambda row: {
                dimension: {item: value["grade"] for item, value in rows.items()}
                for dimension, rows in row["ratings"].items()})
            _validate_ratings(chosen, template, context)
            if not isinstance(chosen.get("rubric"), str) or not chosen["rubric"].strip():
                raise ValueError("审核须说明适合度分级锚点")
            gold["quality_judgments"] = {"origin": "independent_human_review", "status": "approved",
                "reviewer_ids": identities, "task_validated": True, "rubric": chosen["rubric"],
                "catalog_sha256": context["catalog_sha256"], **copy.deepcopy(chosen["ratings"])}
            full_catalog = task_catalog(benchmark["catalog"], dict(benchmark["environment"], **task.get("environment", {})))
            validate_quality_labels(gold, full_catalog)
            if gold["quality_contract"]["use_fit_required"] and feasible:
                gold["relevance_judgments"] = {
                    "origin": "human", "status": "approved", "reviewer_id": ",".join(identities),
                    "rubric": chosen["rubric"], "catalog_sha256": context["catalog_sha256"],
                    "grades": {item: value["grade"] for item, value in chosen["ratings"]["use_fit"].items()},
                    "reasons": {item: value["reason"] for item, value in chosen["ratings"]["use_fit"].items()},
                }
    if not used:
        raise ValueError("没有已完成的双人独立质量审核")
    for task in result["tasks"]:
        task["review_status"] = "approved" if all(turn["gold"].get("quality_judgments") for turn in task["turns"]) else "pending"
    complete = all(task["review_status"] == "approved" for task in result["tasks"])
    result["manifest"].update(quality_label_status="complete_human_labels" if complete else "partial_human_labels",
        independent_relevance_status="complete_human_labels" if complete else "partial_human_labels",
        human_reviewed=complete, quality_review_sha256=fingerprint(reviews),
        parent_benchmark_sha256=fingerprint(benchmark),
        scoring_calibration={"passed": False, "status": "recalibration_required_after_labels"})
    validate_benchmark(result)
    return result


def build_quality_calibration(benchmark, run, *, limit=120):
    if type(limit) is not int or limit < 1:
        raise ValueError("校准 limit 必须是正整数")
    if run["manifest"]["benchmark_sha256"] != fingerprint(benchmark) or run["manifest"]["split"] not in {"train", "dev"}:
        raise ValueError("校准仅使用对应题集的非测试真实运行")
    groups = defaultdict(list)
    tasks = {task["task_id"]: task for task in benchmark["tasks"]}
    for trial in run["trials"]:
        for turn in trial["turns"]:
            task = tasks[trial["task_id"]]
            scenario = task.get("quality_scenario", "ordinary")
            need = turn["gold"].get("customer_policy", {}).get("clarification_need", "not_required")
            groups[(scenario, need if scenario == "ordinary" else "exception")].append((trial, turn))
    queue, key, cluster_counts = [], [], Counter()
    expected_strata = sorted({"scenario:" + task.get("quality_scenario", "ordinary") for task in tasks.values() if task["split"] == run["manifest"]["split"]}
        | {"clarification:" + turn["gold"].get("customer_policy", {}).get("clarification_need", "not_required")
           for task in tasks.values() if task["split"] == run["manifest"]["split"] for turn in task["turns"]})
    while groups and len(queue) < limit:
        for group in sorted(list(groups)):
            if len(queue) >= limit:
                break
            position = min(range(len(groups[group])), key=lambda index: cluster_counts[
                groups[group][index][0]["statistical_cluster_id"]])
            trial, turn = groups[group].pop(position)
            cluster_counts[trial["statistical_cluster_id"]] += 1
            if not groups[group]:
                del groups[group]
            task = tasks[trial["task_id"]]
            index = turn["turn_index"]
            case_id = fingerprint([trial["task_id"], trial["repeat"], index])[:24]
            entry = {"case_id": case_id, "cluster": trial["statistical_cluster_id"],
                     "strata": ["scenario:" + task.get("quality_scenario", "ordinary"),
                                "clarification:" + turn["gold"].get("customer_policy", {}).get("clarification_need", "not_required")],
                     "context": _context(benchmark, task, index, turn["answer"].get("item_ids", [])), "answer": turn["answer"],
                     "prior_answers": [previous["answer"] for previous in trial["turns"][:index]],
                     "tools": [event for event in trial["tool_trace"] if event["turn_index"] <= index],
                     "dimensions": list(turn["quality"]["semantic"]), "reviews": [], "adjudication": None}
            queue.append(entry)
            key.append({"case_id": case_id, "cluster": entry["cluster"],
                        "strata": entry["strata"],
                        "grades": {name: row["grade"] for name, row in turn["quality"]["semantic"].items()},
                        "structural_success": turn["grade"]["success"]})
    public = {"schema_version": "rs-quality-calibration-review/1", "benchmark_sha256": fingerprint(benchmark),
              "cases": queue, "instructions": "独立盲审，不看评分键。两位审核人填写 origin=human、reviewer_id、reason、task_valid、grades(各适用维度0–3)、structural_success(bool)；分歧由第三人裁决。"}
    private = {"schema_version": "rs-quality-calibration-key/1", "benchmark_sha256": fingerprint(benchmark),
               "quality_scorer_sha256": quality_fingerprint(), "judge_identity": run["manifest"]["quality_judge_identity"],
               "review_sha256": fingerprint(public), "expected_strata": expected_strata, "cases": key}
    return {"review": public, "scoring_key": private}


def evaluate_quality_calibration(key, review):
    pristine = copy.deepcopy(review)
    for entry in pristine["cases"]:
        entry["reviews"], entry["adjudication"] = [], None
    if (key.get("schema_version") != "rs-quality-calibration-key/1"
            or key.get("review_sha256") != fingerprint(pristine)
            or key.get("benchmark_sha256") != review.get("benchmark_sha256")
            or key.get("quality_scorer_sha256") != quality_fingerprint()):
        raise ValueError("校准题目、评分键或评分器指纹不一致")
    indexed = {row["case_id"]: row for row in key["cases"]}
    if len(indexed) != len(key["cases"]):
        raise ValueError("校准键重复案例")
    statistics = defaultdict(lambda: {"n": 0, "matches": 0, "clusters": set(), "false_accepts": 0})
    seen, invalid, strata = set(), 0, defaultdict(set)
    for entry in review["cases"]:
        if entry["case_id"] in seen or entry["case_id"] not in indexed:
            raise ValueError("校准案例重复或缺失")
        seen.add(entry["case_id"])
        if not entry.get("reviews"):
            continue
        expected = indexed[entry["case_id"]]
        dimensions = set(expected["grades"])
        for human in entry["reviews"] + ([entry["adjudication"]] if entry.get("adjudication") else []):
            _human(human)
            if (not isinstance(human.get("grades"), dict) or set(human["grades"]) != dimensions
                    or any(type(value) is not int or not 0 <= value <= 3 for value in human["grades"].values())
                    or type(human.get("structural_success")) is not bool):
                raise ValueError("盲审需要完整维度等级和结构成功判断")
        if any(human.get("task_valid") is not True for human in entry["reviews"]):
            invalid += 1
            continue
        chosen, _ = _consensus(entry, lambda row: (row["grades"], row["structural_success"]))
        for stratum in expected["strata"]:
            strata[stratum].add(expected["cluster"])
        for dimension, human_grade in dict(chosen["grades"], structural_success=chosen["structural_success"]).items():
            model_grade = expected["structural_success"] if dimension == "structural_success" else expected["grades"][dimension]
            row = statistics[dimension]
            row["n"] += 1
            row["matches"] += model_grade == human_grade
            row["clusters"].add(expected["cluster"])
            row["false_accepts"] += (human_grade is False and model_grade is True
                if dimension == "structural_success" else human_grade < 2 and model_grade is not None and model_grade >= 2)
    metrics = {name: {"n": row["n"], "clusters": len(row["clusters"]),
                      "agreement": row["matches"] / row["n"], "false_accepts": row["false_accepts"]}
               for name, row in statistics.items()}
    blockers = []
    for dimension in (*SEMANTIC_DIMENSIONS, "structural_success"):
        row = metrics.get(dimension)
        if row is None or row["n"] < 30 or row["clusters"] < 10 or row["agreement"] < 0.8 or row["false_accepts"]:
            blockers.append(dimension + "_not_calibrated")
    if invalid:
        blockers.append("invalid_tasks")
    if key.get("judge_identity") == "not_configured":
        blockers.append("judge_not_configured")
    for stratum in key["expected_strata"]:
        if len(strata[stratum]) < 3:
            blockers.append("under_reviewed_stratum:" + stratum)
    report = {"schema_version": "rs-quality-calibration/1", "benchmark_sha256": key["benchmark_sha256"],
              "quality_scorer_sha256": key["quality_scorer_sha256"], "judge_identity": key["judge_identity"],
              "origin": "independent_human_review", "review_sha256": fingerprint(review), "key_sha256": fingerprint(key),
              "metrics": metrics, "invalid_tasks": invalid, "blockers": blockers, "passed": not blockers,
              "strata_clusters": {name: len(clusters) for name, clusters in strata.items()},
              "expected_strata": key["expected_strata"],
              "threshold_scope": "engineering_acceptance_not_business_satisfaction", "auto_deploy": False}
    report["receipt_sha256"] = fingerprint(report)
    return report


def quality_calibration_passes(report, benchmark_sha256, identity):
    if not isinstance(report, dict):
        return False
    content = {key: value for key, value in report.items() if key != "receipt_sha256"}
    if (report.get("schema_version") != "rs-quality-calibration/1" or report.get("passed") is not True
            or report.get("receipt_sha256") != fingerprint(content) or report.get("blockers") != []
            or report.get("origin") != "independent_human_review" or report.get("invalid_tasks") != 0
            or report.get("benchmark_sha256") != benchmark_sha256 or not report.get("review_sha256")
            or not report.get("key_sha256") or report.get("quality_scorer_sha256") != quality_fingerprint()
            or report.get("judge_identity") != identity or identity == "not_configured"):
        return False
    for dimension in (*SEMANTIC_DIMENSIONS, "structural_success"):
        row = report.get("metrics", {}).get(dimension, {})
        if (type(row.get("n")) is not int or row["n"] < 30 or type(row.get("clusters")) is not int
                or not 10 <= row["clusters"] <= row["n"] or type(row.get("agreement")) not in {float, int}
                or not 0.8 <= row["agreement"] <= 1 or row.get("false_accepts") != 0):
            return False
    if not isinstance(report.get("expected_strata"), list) or not report["expected_strata"]:
        return False
    if any(type(report.get("strata_clusters", {}).get(name)) is not int
           or report["strata_clusters"][name] < 3 for name in report["expected_strata"]):
        return False
    return True
