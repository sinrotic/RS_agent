"""运行、审计和成对比较；不修改生产 Skill，不启动自进化优化器。"""

import copy
import json
import random
import statistics
import subprocess
import time
import uuid
from collections import Counter, defaultdict
from pathlib import Path
import hashlib

from .dataset import fingerprint, validate_benchmark
from .environment import FixtureEnvironment
from .scoring import evaluate_turn, scorer_fingerprint
from .readiness import calibration_passes
from .profile_matching import contrast_metrics
from .natural import natural_metrics


class SubprocessAgent:
    """一次 JSON stdin → JSON stdout；每个 Task/重复新进程，Session 内多轮同进程。"""

    def __init__(self, command, timeout=180):
        self.command, self.timeout = list(command), timeout

    def __call__(self, request):
        completed = subprocess.run(
            self.command,
            input=json.dumps(request, ensure_ascii=False),
            text=True,
            encoding="utf-8",
            capture_output=True,
            timeout=min(
                self.timeout,
                request.get("execution_limits", {}).get("task_timeout_seconds", self.timeout),
            ),
            check=False,
        )
        if completed.returncode != 0:
            # stderr 可能包含服务凭证；不把它原样持久化。
            raise RuntimeError(f"AGENT_PROCESS_EXIT_{completed.returncode}")
        return json.loads(completed.stdout)


def run_benchmark(
    benchmark,
    adapter,
    run_config,
    *,
    split=None,
    repeats=1,
    skills=None,
    calibration_report=None,
    profile_visibility="visible",
    quality_judge=None,
    quality_calibration=None,
):
    """adapter 仅收到公开用户表达、Skill overlay 和隔离环境地址，不收到 gold。"""
    stats = validate_benchmark(benchmark)
    if profile_visibility not in {"visible", "hidden"}:
        raise ValueError("profile_visibility 必须是 visible 或 hidden；只改变输入，不改变评测真值")
    benchmark_hash = fingerprint(benchmark)
    from .quality_dataset import task_catalog
    from .quality_scoring import evaluate_quality, judge_identity, outage_grade, quality_fingerprint, normalize_fixture_projection
    from .quality_review import quality_calibration_passes

    quality_enabled = bool(benchmark["manifest"].get("quality_contract_version"))
    identity = judge_identity(quality_judge) if quality_enabled else "not_applicable"
    quality_calibrated = quality_calibration_passes(quality_calibration, benchmark_hash, identity) if quality_enabled else False
    if quality_calibration is not None and not quality_calibrated:
        raise ValueError("质量校准未通过或不对应题集、裁判与评分器")
    calibration_required = bool(
        benchmark["manifest"].get("scoring_calibration_required")
        or benchmark["manifest"].get("population_sha256")
    )
    if calibration_report is not None and not calibration_passes(
        calibration_report, benchmark_hash
    ):
        raise ValueError("人工评分校准收据未通过，或不对应当前冻结数据/评分器")
    if type(repeats) is not int or not 1 <= repeats <= 20:
        raise ValueError("repeats 必须为 1..20")
    if split is not None and split not in {"train", "dev", "test"}:
        raise ValueError("无效 split")
    if any(
        "key" in key.lower() or "token" in key.lower() and key != "max_tokens" for key in run_config
    ):
        raise ValueError("运行配置不允许包含密钥；使用模型进程环境变量")
    tasks = [task for task in benchmark["tasks"] if split is None or task["split"] == split]
    if not tasks:
        raise ValueError("所选 split 没有任务")
    trials = []
    for task in tasks:
        config = dict(benchmark["environment"], **task.get("environment", {}))
        evaluation_catalog = task_catalog(benchmark["catalog"], config)
        adaptive = task.get("dialogue_policy") == "conditional_customer/1"
        if adaptive:
            config["customer_turns"] = copy.deepcopy(task["turns"])
        profile = benchmark.get("profiles", {}).get(task.get("profile_user_id"))
        exposed_profile = copy.deepcopy(profile or {})
        profile_allowed = config.get("profile_access", {}).get("allowed", True)
        if profile is not None and (profile_visibility == "hidden" or not profile_allowed):
            exposed_profile = {"profile_user_id": task["profile_user_id"]}
            config["profile_access"] = {
                "allowed": False,
                "bound_profile_user_id": task["profile_user_id"],
            }
        if profile is not None:
            # 绑定来自受验证的任务事实，不接受任务环境覆写成另一名用户。
            config["profile"] = copy.deepcopy(exposed_profile)
        for repeat in range(repeats):
            start = time.monotonic()
            with FixtureEnvironment(evaluation_catalog, config) as environment:
                request = {
                    "protocol": "rs-skill-agent/1",
                    "session_id": f"eval-{uuid.uuid4().hex}",
                    "profile_user_id": task.get(
                        "profile_user_id", f"eval-profile-{uuid.uuid4().hex}"
                    ),
                    "profile_snapshot": copy.deepcopy(exposed_profile),
                    "fixture_url": environment.url,
                    "execution_limits": {
                        "task_timeout_seconds": config.get("task_timeout_seconds", 180)
                    },
                    "turns": [
                        {"user_message": turn["user_message"], "limit": turn["limit"]}
                        for turn in (task["turns"][:1] if adaptive else task["turns"])
                    ],
                    "skills": copy.deepcopy(skills or {}),
                    "model": dict(run_config, seed=run_config.get("seed", 0) + repeat),
                }
                if adaptive:
                    request["customer_dialogue"] = True
                    request["customer_turn_limit"] = len(task["turns"])
                    request["shopping_context"] = copy.deepcopy(config.get("shopping_context", {}))
                failure, response = None, {}
                try:
                    response = adapter(request)
                    if not isinstance(response, dict) or not isinstance(
                        response.get("turns"), list
                    ):
                        raise ValueError("INVALID_AGENT_PROTOCOL")
                    if (not adaptive and len(response["turns"]) != len(task["turns"])) or (
                        adaptive and not 1 <= len(response["turns"]) <= len(task["turns"])
                    ):
                        raise ValueError("INCOMPLETE_AGENT_PROTOCOL")
                except Exception as error:
                    failure = type(error).__name__
                actual_runtime = response.get("runtime", {}) if isinstance(response, dict) else {}
                # 实际 Runtime 快照及 overlay 应用证明是正式模型实验的必要条件。
                if run_config.get("adapter_kind") == "java_rs_agent_loop":
                    if not actual_runtime.get("runtime_sha256"):
                        failure = "MissingRuntimeAttestation"
                    if profile is not None and (
                        actual_runtime.get("profile_user_id") != task["profile_user_id"]
                        or actual_runtime.get("profile_snapshot_sha256")
                        != fingerprint(exposed_profile)
                    ):
                        failure = "MissingProfileBindingAttestation"
                for name, skill in (skills or {}).items():
                    if actual_runtime.get("skill_sha256", {}).get(name) != fingerprint(
                        skill["content"]
                    ):
                        failure = "SkillOverlayNotApplied"
                answers = response.get("turns", []) if isinstance(response, dict) else []
                dialogue_complete = not adaptive or (
                    bool(answers)
                    and len(environment.customer_trace) == len(answers)
                    and environment.customer_trace[-1]["done"]
                    and all(
                        event["answer_sha256"] == fingerprint(answer) and not event["blocked"]
                        for event, answer in zip(environment.customer_trace, answers)
                    )
                )
                turns, previous = [], []
                for index, turn in enumerate(
                    task["turns"][: len(answers)] if adaptive and answers else task["turns"]
                ):
                    gold = copy.deepcopy(turn["gold"])
                    if turn.get("exclude_previous"):
                        gold["hard"].append(
                            {
                                "field": "item_id",
                                "op": "not_in",
                                "value": list(dict.fromkeys(previous)),
                            }
                        )
                    answer = (
                        copy.deepcopy(answers[index])
                        if index < len(answers) and isinstance(answers[index], dict)
                        else {}
                    )
                    # 不信任 Agent 自报的来源：从独立环境到该 Turn 为止的工具返回计算。
                    observed = {
                        item["item_id"]
                        for event in environment.trace
                        if event["turn_index"] <= index
                        for item in event["result"].get("items", [])
                    }
                    answer["observed_item_ids"] = sorted(observed)
                    if failure:
                        answer["status"] = "failed"
                    try:
                        if quality_enabled:
                            answer = normalize_fixture_projection(task, answer)
                        grade = (outage_grade(task, answer, environment.trace)
                                 if task.get("quality_scenario") == "tool_outage"
                                 else evaluate_turn(evaluation_catalog, gold, answer))
                    except (TypeError, ValueError, KeyError):
                        answer = {"status": "failed", "item_ids": [], "outcome": "invalid_output"}
                        grade = evaluate_turn(evaluation_catalog, gold, answer)
                        failure = "InvalidAgentOutput"
                    previous.extend(answer.get("item_ids", []))
                    turns.append(
                        {
                            "turn_index": index,
                            "executed": index < len(answers),
                            "gold": gold,
                            "answer": answer,
                            "grade": grade,
                        }
                    )
                    if quality_enabled:
                        turns[-1]["quality"] = evaluate_quality(
                            task, index, answer, evaluation_catalog, exposed_profile, environment.trace, grade,
                            judge=quality_judge, calibrated=quality_calibrated, active_gold=gold,
                            prior_answers=[turn["answer"] for turn in turns[:-1]])
                ranking = [
                    turn["grade"]["task_score"]
                    for turn in turns
                    if turn["grade"]["ranking_applicable"]
                ]
                if failure is None and any(
                    turn["answer"].get("status", "ok") != "ok" for turn in turns
                ):
                    failure = "AgentTurnFailed"
                task_success = dialogue_complete and all(turn["grade"]["success"] for turn in turns)
                if adaptive and not dialogue_complete and turns:
                    turns[-1]["grade"]["violations"].append("customer_dialogue_incomplete")
                planned_ranking = adaptive and task.get("quality_scenario") != "tool_outage" and any(
                    evaluate_turn(
                        evaluation_catalog,
                        turn["gold"],
                        {"item_ids": [], "outcome": "invalid_output"},
                    )["ranking_applicable"]
                    for turn in task["turns"]
                )
                trials.append(
                    {
                        "task_id": task["task_id"],
                        "family_id": task["family_id"],
                        "statistical_cluster_id": task.get(
                            "statistical_cluster_id", task["family_id"]
                        ),
                        "contrast_group_id": task.get("contrast_group_id"),
                        "split": task["split"],
                        "repeat": repeat,
                        "kind": task["kind"],
                        "profile_user_id": task.get("profile_user_id"),
                        "profile_snapshot_sha256": fingerprint(profile)
                        if profile is not None
                        else None,
                        "exposed_profile_sha256": fingerprint(exposed_profile),
                        "profile_evidence_score": statistics.mean(
                            turn["grade"]["profile_evidence"]["score"]
                            for turn in turns
                            if turn["grade"].get("profile_evidence")
                        )
                        if any(turn["grade"].get("profile_evidence") for turn in turns)
                        else None,
                        "failure": failure,
                        "success": task_success,
                        "dialogue_complete": dialogue_complete,
                        "planned_turns": len(task["turns"]),
                        "executed_turns": len(answers),
                        "interaction_score": statistics.mean(
                            turn["grade"]["interaction_score"]
                            for turn in turns
                            if "interaction_score" in turn["grade"]
                        )
                        if any("interaction_score" in turn["grade"] for turn in turns)
                        else None,
                        "ranking_score": (statistics.mean(ranking) if task_success else 0.0)
                        if ranking
                        else 0.0
                        if planned_ranking
                        else None,
                        "turn_ranking_score": statistics.mean(ranking) if ranking else None,
                        "elapsed_seconds": time.monotonic() - start,
                        "turns": turns,
                        "tool_trace": environment.trace,
                        "customer_trace": copy.deepcopy(environment.customer_trace),
                        "agent_trace": response.get("trace", [])
                        if isinstance(response, dict)
                        else [],
                        "runtime": actual_runtime,
                    }
                )
                if quality_enabled:
                    quality_turns = [turn["quality"] for turn in turns]
                    trials[-1]["quality_success"] = (False if failure or not dialogue_complete
                        or any(row["verified_success"] is False for row in quality_turns)
                        else True if all(row["verified_success"] is True for row in quality_turns) else None)
                    trials[-1]["quality_complete"] = all(row["complete"] for row in quality_turns)
                    trials[-1]["quality_scores"] = {
                        name: statistics.mean(values) if (values := [
                            turn["quality"]["scores"].get(name) if name in {"use_fit", "profile_fit"}
                            else turn["quality"]["semantic"].get(name, {}).get("score")
                            for turn in turns
                            if (turn["quality"]["scores"].get(name) if name in {"use_fit", "profile_fit"}
                                else turn["quality"]["semantic"].get(name, {}).get("score")) is not None]) else None
                        for name in ("use_fit", "profile_fit", "clarification", "grounding", "profile_use", "exception_handling")}
    ranked = [trial["ranking_score"] for trial in trials if trial["ranking_score"] is not None]
    runtimes = sorted({trial["runtime"].get("runtime_sha256", "missing") for trial in trials})
    failures = Counter(
        reason
        for trial in trials
        for turn in trial["turns"]
        for reason in turn["grade"]["violations"]
    )
    kinds = {}
    for kind in sorted({trial["kind"] for trial in trials}):
        group = [trial for trial in trials if trial["kind"] == kind]
        quality = [trial["ranking_score"] for trial in group if trial["ranking_score"] is not None]
        kinds[kind] = {
            "trials": len(group),
            "success_rate": sum(trial["success"] for trial in group) / len(group),
            "mean_ranking_score": statistics.mean(quality) if quality else None,
        }
    clarification_grades = [
        turn["grade"]
        for trial in trials
        for turn in trial["turns"]
        if turn["gold"].get("customer_policy", {}).get("action") == "clarify"
    ]
    guidance_grades = [
        turn["grade"]
        for trial in trials
        for turn in trial["turns"]
        if turn["gold"].get("customer_policy", {}).get("action") == "defer"
    ]
    history_grades = [
        turn["grade"]["history_alignment"]
        for trial in trials
        for turn in trial["turns"]
        if turn["grade"].get("history_alignment")
    ]
    planned_clarifications = repeats * sum(
        turn["gold"].get("customer_policy", {}).get("action") == "clarify"
        for task in tasks
        for turn in task["turns"]
    )
    planned_guidance = repeats * sum(
        turn["gold"].get("customer_policy", {}).get("action") == "defer"
        for task in tasks
        for turn in task["turns"]
    )
    return {
        "schema_version": "rs-skill-run/1",
        "manifest": {
            "benchmark_sha256": benchmark_hash,
            "scoring_calibration_required": calibration_required,
            "scoring_calibration": copy.deepcopy(calibration_report),
            "catalog_sha256": benchmark["manifest"]["catalog_sha256"],
            "human_reviewed": stats["human_reviewed"],
            "profile_visibility": profile_visibility,
            "independent_relevance_status": benchmark["manifest"].get(
                "independent_relevance_status"
            ),
            "run_config": copy.deepcopy(run_config),
            "split": split,
            "repeats": repeats,
            "skills_sha256": fingerprint(skills or {}),
            "implementation_sha256": {
                path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                for path in sorted(Path(__file__).parent.glob("*.py"))
            },
            "runtime_sha256": runtimes,
            "scorer_version": "customer-interaction-and-request-ndcg/1"
            if any(task.get("dialogue_policy") for task in tasks)
            else "hard-gated-linear-ndcg/2",
            "scorer_sha256": scorer_fingerprint(),
            **({"quality_scorer_sha256": quality_fingerprint(), "quality_judge_identity": identity,
                "quality_calibration": copy.deepcopy(quality_calibration),
                "quality_label_status": benchmark["manifest"].get("quality_label_status")} if quality_enabled else {}),
        },
        "summary": {
            "planned_trials": len(tasks) * repeats,
            "recorded_trials": len(trials),
            "success_rate": sum(trial["success"] for trial in trials) / len(trials),
            "mean_ranking_score": statistics.mean(ranked) if ranked else None,
            "execution_failures": sum(trial["failure"] is not None for trial in trials),
            "family_count": len({trial["family_id"] for trial in trials}),
            "independent_statistical_clusters": len(
                {trial["statistical_cluster_id"] for trial in trials}
            ),
            "profile_contrasts": contrast_metrics(benchmark, trials, split=split, repeats=repeats),
            "natural_metrics": natural_metrics(benchmark, trials, split=split, repeats=repeats),
            "failure_reasons": dict(failures),
            "by_kind": kinds,
            "total_elapsed_seconds": sum(trial["elapsed_seconds"] for trial in trials),
            "fixture_tool_calls": sum(len(trial["tool_trace"]) for trial in trials),
            "ranking_trials": len(ranked),
            "non_ranking_trials": len(trials) - len(ranked),
            **({"quality": {
                "calibrated": quality_calibrated,
                "complete_trials": sum(trial["quality_complete"] for trial in trials),
                "verified_success_rate": sum(trial["quality_success"] is True for trial in trials) / len(trials)
                    if all(trial["quality_success"] is not None for trial in trials) else None,
                "unknown_success_trials": sum(trial["quality_success"] is None for trial in trials),
                "evaluation_errors": sum(len(turn["quality"]["evaluation_errors"]) for trial in trials for turn in trial["turns"]),
                "satisfaction": None, "auto_deploy": False,
            }} if quality_enabled else {}),
            "customer_metrics": {
                "planned_clarification_turns": planned_clarifications,
                "planned_guidance_turns": planned_guidance,
                "clarification_turns": len(clarification_grades),
                "clarification_success_rate": sum(
                    grade["success"] for grade in clarification_grades
                )
                / planned_clarifications
                if planned_clarifications
                else None,
                "guidance_turns": len(guidance_grades),
                "guidance_success_rate": sum(grade["success"] for grade in guidance_grades)
                / planned_guidance
                if planned_guidance
                else None,
                "incomplete_dialogues": sum(not trial["dialogue_complete"] for trial in trials),
                "history_alignment": {
                    field: statistics.mean(values)
                    if (
                        values := [
                            grade[field] for grade in history_grades if grade[field] is not None
                        ]
                    )
                    else None
                    for field in ("category_mean", "store_mean")
                },
                "implicit_history_used_for_primary_score_or_promotion": False,
            },
        },
        "trials": trials,
    }


def compare_runs(baseline, candidate, *, bootstrap_samples=2000):
    """同任务/重复成对比较；按 family 做 bootstrap，报告不自动晋升或部署。"""
    if type(bootstrap_samples) is not int or bootstrap_samples < 100:
        raise ValueError("bootstrap_samples 必须至少为 100")
    for key in (
        "benchmark_sha256",
        "catalog_sha256",
        "run_config",
        "split",
        "repeats",
        "runtime_sha256",
        "scorer_version",
        "implementation_sha256",
    ):
        if baseline["manifest"][key] != candidate["manifest"][key]:
            raise ValueError(f"不可比实验：{key} 不一致")
    for key in ("scoring_calibration_required", "scoring_calibration", "scorer_sha256"):
        if baseline["manifest"].get(key) != candidate["manifest"].get(key):
            raise ValueError(f"不可比实验：{key} 不一致")
    if baseline["manifest"].get("profile_visibility") != candidate["manifest"].get(
        "profile_visibility"
    ):
        raise ValueError("Skill 比较必须使用同样画像可见性；画像消融使用独立比较接口")

    def indexed(run):
        result = {(trial["task_id"], trial["repeat"]): trial for trial in run["trials"]}
        if len(result) != len(run["trials"]) or len(result) != run["summary"]["planned_trials"]:
            raise ValueError("实验缺少计划中的试验或有重复记录")
        return result

    old, new = indexed(baseline), indexed(candidate)
    if old.keys() != new.keys():
        raise ValueError("成对任务不一致")
    families, ranking_families = defaultdict(list), defaultdict(list)
    applicability_changed = False
    regressions = []
    for key in old:
        a, b = old[key], new[key]
        cluster = a.get("statistical_cluster_id", a["family_id"])
        families[cluster].append(float(b["success"]) - float(a["success"]))
        if (a["ranking_score"] is None) != (b["ranking_score"] is None):
            applicability_changed = True
        elif a["ranking_score"] is not None:
            ranking_families[cluster].append(b["ranking_score"] - a["ranking_score"])
        if a["success"] and not b["success"]:
            regressions.append({"task_id": key[0], "repeat": key[1]})

    def confidence_interval(groups):
        if not groups:
            return None
        randomizer = random.Random(0)
        sampled = []
        for _ in range(bootstrap_samples):
            values = [
                value for group in randomizer.choices(groups, k=len(groups)) for value in group
            ]
            sampled.append(statistics.mean(values))
        sampled.sort()
        return [
            sampled[int(0.025 * len(sampled))],
            sampled[min(len(sampled) - 1, int(0.975 * len(sampled)))],
        ]

    interval = confidence_interval(list(families.values()))
    ranking_interval = confidence_interval(list(ranking_families.values()))
    blockers = []
    if candidate["manifest"].get("independent_relevance_status") not in {
        None,
        "complete_human_labels",
    }:
        blockers.append(
            "independent_relevance_pending; history_proxy_cannot_authorize_personalization_improvement"
        )
    if candidate["manifest"].get("scoring_calibration_required") and not calibration_passes(
        candidate["manifest"].get("scoring_calibration"), candidate["manifest"]["benchmark_sha256"]
    ):
        blockers.append("scoring_calibration_missing_or_failed")
    if not candidate["manifest"]["human_reviewed"]:
        blockers.append("dataset_pending_human_review")
    if candidate["manifest"]["run_config"].get("adapter_kind") != "java_rs_agent_loop":
        blockers.append("not_real_java_agent_experiment")
    if (
        "missing" in candidate["manifest"]["runtime_sha256"]
        or len(candidate["manifest"]["runtime_sha256"]) != 1
    ):
        blockers.append("runtime_not_frozen_or_unattested")
    if len(families) < 20:
        blockers.append("insufficient_independent_families")
    if candidate["manifest"]["split"] != "test":
        blockers.append("not_held_out_test")
    if candidate["summary"]["execution_failures"] or baseline["summary"]["execution_failures"]:
        blockers.append("execution_failures_need_audit")
    if regressions:
        blockers.append("success_regressions")
    if interval[0] < 0:
        blockers.append("success_noninferiority_not_established")
    if not (interval[0] > 0 or ranking_interval is not None and ranking_interval[0] > 0):
        blockers.append("improvement_not_established")
    if applicability_changed:
        blockers.append("ranking_applicability_changed")
    old_rank, new_rank = (
        baseline["summary"]["mean_ranking_score"],
        candidate["summary"]["mean_ranking_score"],
    )
    if old_rank is not None and (
        new_rank is None
        or new_rank < old_rank
        or ranking_interval is not None
        and ranking_interval[0] < 0
    ):
        blockers.append("ranking_quality_regressed")
    return {
        "schema_version": "rs-skill-comparison/1",
        "paired_trials": len(old),
        "family_count": len(families),
        "success_rate_delta": candidate["summary"]["success_rate"]
        - baseline["summary"]["success_rate"],
        "success_delta_family_bootstrap_95pct": interval,
        "ranking_delta_family_bootstrap_95pct": ranking_interval,
        "ranking_score_delta": new_rank - old_rank
        if old_rank is not None and new_rank is not None
        else None,
        "regressions": regressions,
        "promotion_blockers": blockers,
        "eligible_for_promotion": not blockers,
        "auto_deploy": False,
    }


def compare_profile_ablation(hidden, visible, *, bootstrap_samples=2000):
    """同 Skill 的去画像对照；无独立标签时不输出虚假的个性化质量增益。"""
    if type(bootstrap_samples) is not int or bootstrap_samples < 100:
        raise ValueError("bootstrap_samples 必须至少为 100")
    if (
        hidden["manifest"].get("profile_visibility") != "hidden"
        or visible["manifest"].get("profile_visibility") != "visible"
    ):
        raise ValueError("画像消融需要 hidden 与 visible 两个不同输入条件")
    for key in (
        "benchmark_sha256",
        "catalog_sha256",
        "run_config",
        "split",
        "repeats",
        "skills_sha256",
        "runtime_sha256",
        "scorer_version",
        "scorer_sha256",
        "implementation_sha256",
        "scoring_calibration",
        "independent_relevance_status",
    ):
        if hidden["manifest"].get(key) != visible["manifest"].get(key):
            raise ValueError(f"画像消融不可比：{key} 不一致；只能改变画像输入")

    def index(run):
        trials = {(trial["task_id"], trial["repeat"]): trial for trial in run["trials"]}
        if len(trials) != len(run["trials"]) or len(trials) != run["summary"]["planned_trials"]:
            raise ValueError("画像消融试验缺失或重复")
        return trials

    old, new = index(hidden), index(visible)
    if old.keys() != new.keys():
        raise ValueError("画像消融必须使用同一组任务和重复")
    clusters, excluded = defaultdict(list), Counter()
    deltas = []
    for key in old:
        a, b = old[key], new[key]
        ranked_a = [turn for turn in a["turns"] if turn["grade"]["ranking_applicable"]]
        ranked_b = [turn for turn in b["turns"] if turn["grade"]["ranking_applicable"]]
        if (
            not ranked_a
            or not ranked_b
            or any(
                turn["grade"].get("quality_basis") != "independent_human_relevance"
                for turn in ranked_a + ranked_b
            )
        ):
            excluded["independent_relevance_missing"] += 1
            continue
        if [fingerprint(turn["gold"]) for turn in ranked_a] != [
            fingerprint(turn["gold"]) for turn in ranked_b
        ]:
            excluded["different_customer_information_path"] += 1
            continue
        delta = b["ranking_score"] - a["ranking_score"]
        deltas.append(delta)
        clusters[b.get("statistical_cluster_id", b["family_id"])].append(delta)
    interval = None
    if clusters:
        rng = random.Random(0)
        groups = list(clusters.values())
        values = sorted(
            statistics.mean(
                value for group in rng.choices(groups, k=len(groups)) for value in group
            )
            for _ in range(bootstrap_samples)
        )
        interval = [
            values[int(0.025 * len(values))],
            values[min(len(values) - 1, int(0.975 * len(values)))],
        ]
    return {
        "schema_version": "rs-profile-ablation-comparison/1",
        "paired_trials": len(old),
        "comparable_labeled_trials": len(deltas),
        "independent_clusters": len(clusters),
        "personalization_quality_delta": statistics.mean(deltas) if deltas else None,
        "quality_delta_cluster_bootstrap_95pct": interval,
        "excluded_trials": dict(excluded),
        "status": "independent_quality_comparison" if deltas else "pending_independent_relevance",
        "history_proxy_used_as_quality_truth": False,
        "auto_deploy": False,
    }
