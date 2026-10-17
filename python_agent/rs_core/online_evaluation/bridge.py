"""把人工确认的真实案例转换成现有 runner 可读的补充题集，不覆写冻结基准。"""

import copy

from rs_core.offline.evaluation.skill_benchmark.dataset import (
    fingerprint, validate_benchmark, validate_gold,
)


def reviewed_benchmarks(pack, baseline):
    validate_benchmark(baseline)
    if pack.get("schema_version") != "rs-online-review/1":
        raise ValueError("不支持的在线审核包")
    result = []
    families = {}
    baseline_hash = fingerprint(baseline)
    for example in pack["examples"]:
        review = example["review"]
        if review.get("approved") is not True:
            continue
        if (not isinstance(review.get("reviewer_id"), str) or not review["reviewer_id"].strip()
                or review.get("export_permission") is not True):
            raise ValueError("导出需要明确审核人及脱敏案例使用授权")
        event, report = example["event"], example["evaluation"]
        if report["turn_key"] != event["turn_key"] or report.get("context_truncated"):
            raise ValueError("不完整上下文或跨 Turn 审核记录不能成为金标准")
        gold = copy.deepcopy(review.get("gold"))
        if not isinstance(gold, dict):
            raise ValueError("必须由审核人填写 gold，不能自动使用模型抽取结果")
        validate_gold(gold)
        if gold.get("customer_policy", {}).get("profile_match"):
            raise ValueError("本导出不包含长期画像；个性化标签需要另行审核绑定与权限")
        family = "online-profile-" + event["profile_key"]
        split = review.get("split", "train")
        if split not in {"train", "dev", "test"}:
            raise ValueError("审核 split 无效")
        if families.setdefault(family, split) != split:
            raise ValueError("同一画像用户的在线案例禁止跨 split")
        catalog = copy.deepcopy(report["catalog"])
        if not catalog:
            raise ValueError("导出缺少独立商品快照")
        task = {"task_id": "online-" + event["turn_key"], "family_id": family,
                "statistical_cluster_id": family, "split": split,
                "kind": "reviewed_online_replay", "review_status": "approved",
                "turns": [{"user_message": "\n".join(event["customer_messages"]),
                           "limit": gold["k"], "gold": gold}],
                "environment": {"profile_access": {"allowed": False}}}
        benchmark = {"schema_version": "rs-skill-benchmark/1", "catalog": catalog,
                     "profiles": {}, "tasks": [task],
                     "environment": copy.deepcopy(baseline["environment"]),
                     "manifest": {"catalog_sha256": fingerprint(catalog),
                                  "human_reviewed": True, "scoring_calibration_required": True,
                                  "baseline_benchmark_sha256": baseline_hash,
                                  "online_turn_key": event["turn_key"],
                                  "reviewer_id": review["reviewer_id"],
                                  "catalog_scope": "restricted_replay_snapshot_not_original_full_catalog",
                                  "identity_overlap_review_required": True,
                                  "auto_deploy": False}}
        validate_benchmark(benchmark)
        result.append(benchmark)
    if not result:
        raise ValueError("没有已审核、获准导出的案例")
    return result


def improvement_jobs(candidates, baseline):
    validate_benchmark(baseline)
    return {"schema_version": "rs-skill-improvement-jobs/1",
            "baseline_benchmark_sha256": fingerprint(baseline),
            "jobs": [{**candidate,
                      "candidate_skill_overlay": {"instructions": candidate["candidate_instruction"],
                                                  "activation": "offline_only"},
                      "required_comparisons": ["frozen_existing_benchmark", "reviewed_online_replays",
                                               "held_out_cases_not_used_to_write_candidate"],
                      "offline_evolution_entrypoint": "scripts/evaluation/skill_evolution.py evolve",
                      "evolution_requirements": ["independent_human_quality_labels", "structural_calibration",
                                                 "semantic_quality_calibration", "train_dev_test_isolation"],
                      "online_evidence_role": "reviewed_training_feedback_only; not_gold_or_release_authority",
                      "status": "candidate_draft_pending_attribution_review"}
                     for candidate in candidates], "auto_deploy": False}
