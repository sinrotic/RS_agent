"""更丰富任务与校准材料通过评测构建/公式 Interface 验收。"""

import copy

import pytest

from rs_core.offline.evaluation.skill_benchmark.dataset import fingerprint
from rs_core.offline.evaluation.skill_benchmark.environment import FixtureEnvironment
from rs_core.offline.evaluation.skill_benchmark.scoring import evaluate_turn
from rs_core.offline.evaluation.skill_benchmark.readiness import (
    strengthen_benchmark,
    build_calibration_bundle,
    evaluate_calibration,
    audit_benchmark,
    calibration_passes,
)
from rs_core.offline.evaluation.skill_benchmark.runner import compare_runs


@pytest.fixture
def benchmark():
    catalog = [
        {
            "item_id": "A",
            "title": "Pen A",
            "category": "pens",
            "store": "Blue",
            "price": 10,
            "currency": "SOURCE_UNIT",
        },
        {
            "item_id": "B",
            "title": "Pen B",
            "category": "pens",
            "store": "Red",
            "price": 20,
            "currency": "SOURCE_UNIT",
        },
        {
            "item_id": "C",
            "title": "Clip C",
            "category": "clips",
            "store": "Blue",
            "price": 30,
            "currency": "SOURCE_UNIT",
        },
        {
            "item_id": "D",
            "title": "Clip D",
            "category": "clips",
            "store": "Red",
            "price": 1,
            "currency": "SOURCE_UNIT",
        },
    ]
    profiles = {
        "u": {
            "profile_user_id": "u",
            "activity_count": 8,
            "history_cutoff_exclusive": 200,
            "history": [],
            "seen_item_ids": ["Past"],
            "profile_preferences": {},
        }
    }
    gold = {
        "k": 2,
        "hard": [
            {"field": "category", "op": "in", "value": ["pens"]},
            {"field": "currency", "op": "eq", "value": "SOURCE_UNIT"},
            {"field": "price", "op": "lte", "value": 20},
            {"field": "item_id", "op": "not_in", "value": ["Past"]},
        ],
        "soft": [
            {"field": "price", "op": "minimize", "best": 0, "worst": 20, "weight": 0.3},
            {
                "field": "category",
                "op": "lookup",
                "scores": {"pens": 1, "clips": 0.5},
                "weight": 0.35,
            },
            {"field": "store", "op": "lookup", "scores": {"Blue": 1}, "weight": 0.35},
        ],
    }
    task = {
        "task_id": "f-personalized",
        "family_id": "f",
        "profile_user_id": "u",
        "kind": "personalized",
        "split": "dev",
        "review_status": "pending",
        "anchor_item_id": "A",
        "anchor_evidence": {"user_id": "u", "parent_asin": "A", "timestamp": 200, "rating": 5},
        "turns": [{"user_message": "结合我的偏好推荐2支笔，预算20。", "limit": 2, "gold": gold}],
    }
    return {
        "schema_version": "rs-skill-benchmark/1",
        "catalog": catalog,
        "profiles": profiles,
        "tasks": [task],
        "environment": {"tool_call_budget": 16},
        "manifest": {
            "catalog_sha256": fingerprint(catalog),
            "profiles_sha256": fingerprint(profiles),
            "human_reviewed": False,
        },
    }


def test_added_stress_tasks_have_distinct_verifiable_outcomes_without_mutating_old_dataset(
    benchmark,
):
    before = copy.deepcopy(benchmark)
    strengthened = strengthen_benchmark(benchmark)
    assert benchmark == before
    tasks = {task["kind"]: task for task in strengthened["tasks"]}
    assert set(tasks) == {
        "personalized",
        "no_match",
        "unknown_attribute",
        "tool_unavailable",
        "category_switch",
    }
    for kind, outcome, limitation in (
        ("no_match", "no_match", "no_matches"),
        ("unknown_attribute", "uncertain_match", "unknown_attributes"),
    ):
        gold = tasks[kind]["turns"][0]["gold"]
        assert evaluate_turn(
            strengthened["catalog"],
            gold,
            {
                "item_ids": [],
                "outcome": outcome,
                "limitations": [limitation],
                "message": "明确说明限制",
            },
        )["success"]
    assert tasks["category_switch"]["turns"][1]["gold"]["hard"][0]["value"] == ["clips"]
    with FixtureEnvironment(
        strengthened["catalog"], tasks["tool_unavailable"]["environment"]
    ) as environment:
        assert environment.call("recommend_semantic_recall", {})["status"] == "FAILED"
        assert environment.call("recommend_profile_pipeline", {})["status"] == "SUCCESS"


def test_blind_calibration_queue_excludes_test_gold_and_separates_scoring_key(benchmark):
    strengthened = strengthen_benchmark(benchmark)
    test_task = copy.deepcopy(strengthened["tasks"][0])
    test_task.update(
        task_id="held-out",
        family_id="held-out",
        profile_user_id="test-user",
        split="test",
        anchor_item_id="B",
    )
    test_task["anchor_evidence"].update(user_id="test-user", parent_asin="B")
    strengthened["profiles"]["test-user"] = dict(
        copy.deepcopy(strengthened["profiles"]["u"]), profile_user_id="test-user"
    )
    strengthened["manifest"]["profiles_sha256"] = fingerprint(strengthened["profiles"])
    strengthened["tasks"].append(test_task)
    bundle = build_calibration_bundle(strengthened, pair_limit=5)
    assert len(bundle["review_queue"]["pairs"]) == 5
    assert all(pair["split"] != "test" for pair in bundle["review_queue"]["pairs"])
    assert all(
        "gold" not in pair and "formula_score" not in pair
        for pair in bundle["review_queue"]["pairs"]
    )
    assert all(
        pair["candidate_a"]["items"] or pair["candidate_b"]["items"]
        for pair in bundle["review_queue"]["pairs"]
    )
    assert bundle["scoring_key"]["benchmark_sha256"] == fingerprint(strengthened)
    assert bundle["labels_template"]["ratings"]
    assert all(row["preference"] is None for row in bundle["labels_template"]["ratings"])
    assert "candidate_a" not in bundle["review_markdown"]
    assert "候选 A" in bundle["review_markdown"] and "候选 B" in bundle["review_markdown"]
    assert "formula_preference" not in bundle["review_markdown"]


def test_calibration_requires_independent_labels_and_reports_family_clustered_agreement():
    pairs = [
        {
            "pair_id": f"p{i}",
            "family_id": f"f{i // 3}",
            "formula_preference": "A" if i % 2 == 0 else "B",
        }
        for i in range(30)
    ]
    key = {"benchmark_sha256": "frozen-data", "review_queue_sha256": "frozen-queue", "pairs": pairs}
    labels = {
        "benchmark_sha256": "frozen-data",
        "review_queue_sha256": "frozen-queue",
        "ratings": [
            {
                "pair_id": pair["pair_id"],
                "preference": None,
                "reviewer_id": None,
                "reason": None,
                "review_origin": "human",
                "request_valid": None,
            }
            for pair in pairs
        ],
    }
    assert evaluate_calibration(key, labels)["passed"] is False
    for row, pair in zip(labels["ratings"], pairs):
        row.update(
            preference=pair["formula_preference"],
            reviewer_id="fixture-reviewer",
            reason="测试用独立标签",
            request_valid=True,
        )
    report = evaluate_calibration(key, labels)
    assert report["agreement"] == 1
    assert report["agreement_family_bootstrap_95pct"] == [1, 1]
    assert report["reviewed_families"] == 10 and report["passed"] is True
    labels["ratings"][0]["review_origin"] = "formula_generated"
    with pytest.raises(ValueError, match="human"):
        evaluate_calibration(key, labels)


def test_even_large_reviewed_test_run_cannot_promote_without_scoring_calibration():
    baseline = {
        "manifest": {
            "benchmark_sha256": "frozen",
            "catalog_sha256": "catalog",
            "run_config": {"adapter_kind": "java_rs_agent_loop"},
            "split": "test",
            "repeats": 1,
            "runtime_sha256": ["runtime"],
            "scorer_version": "v2",
            "implementation_sha256": {},
            "human_reviewed": True,
            "scoring_calibration_required": True,
            "scoring_calibration": None,
        },
        "summary": {
            "planned_trials": 20,
            "success_rate": 1,
            "mean_ranking_score": 80,
            "execution_failures": 0,
        },
        "trials": [
            {
                "task_id": f"t{i}",
                "repeat": 0,
                "family_id": f"f{i}",
                "success": True,
                "ranking_score": 80,
            }
            for i in range(20)
        ],
    }
    candidate = copy.deepcopy(baseline)
    candidate["summary"]["mean_ranking_score"] = 90
    for trial in candidate["trials"]:
        trial["ranking_score"] = 90
    comparison = compare_runs(baseline, candidate)
    assert comparison["eligible_for_promotion"] is False
    assert "scoring_calibration_missing_or_failed" in comparison["promotion_blockers"]


def test_malformed_calibration_receipts_fail_closed_without_crashing(benchmark):
    key = build_calibration_bundle(strengthen_benchmark(benchmark))["scoring_key"]
    report = {
        "passed": True,
        "review_origin": "human",
        "benchmark_sha256": key["benchmark_sha256"],
        "scorer_sha256": key["scorer_sha256"],
        "valid_reviewed_pairs": 30,
        "reviewed_families": 10,
        "invalid_pairs": 0,
        "agreement": 0.9,
        "agreement_family_bootstrap_95pct": [0.7, 1],
        "human_labels_sha256": "labels",
        "scoring_key_sha256": "key",
    }
    assert calibration_passes(report, key["benchmark_sha256"]) is True
    for field, value in (
        ("agreement", None),
        ("agreement", "0.9"),
        ("agreement", float("inf")),
        ("valid_reviewed_pairs", None),
        ("reviewed_families", True),
        ("agreement_family_bootstrap_95pct", [None, 1]),
        ("agreement_family_bootstrap_95pct", [0.9, 0.7]),
    ):
        malformed = dict(report, **{field: value})
        assert calibration_passes(malformed, key["benchmark_sha256"]) is False


def test_audit_distinguishes_formula_sanity_from_human_validated_readiness(benchmark):
    report = audit_benchmark(strengthen_benchmark(benchmark))
    assert report["ready_for_baseline_diagnostics"] is True
    assert report["ready_for_validated_skill_iteration"] is False
    assert report["independent_users_per_split"] == {"train": 0, "dev": 1, "test": 0}
    assert report["outcome_turn_counts"]["no_match"] == 1
    assert report["outcome_turn_counts"]["uncertain_match"] == 1
    assert "human_task_review_pending" in report["readiness_blockers"]
    assert "scoring_calibration_pending" in report["readiness_blockers"]


def test_affordable_unseen_category_keeps_nonzero_ranking_utility_without_relaxing_budget(
    benchmark,
):
    benchmark["catalog"] = benchmark["catalog"][:2] + [
        {
            "item_id": "Z",
            "title": "Unknown preference clip",
            "category": "clips",
            "store": "Green",
            "price": 30,
            "currency": "SOURCE_UNIT",
        }
    ]
    benchmark["manifest"]["catalog_sha256"] = fingerprint(benchmark["catalog"])
    benchmark["tasks"][0]["turns"][0]["gold"]["soft"][1]["scores"] = {"pens": 1}
    strengthened = strengthen_benchmark(benchmark)
    switched = next(task for task in strengthened["tasks"] if task["kind"] == "category_switch")
    gold = switched["turns"][1]["gold"]
    assert gold["hard"][2]["value"] == 30
    assert gold["soft"][0]["worst"] == 33
    grade = evaluate_turn(
        strengthened["catalog"],
        gold,
        {
            "item_ids": ["Z"],
            "outcome": "recommend",
            "limitations": ["insufficient_matches"],
            "message": "目录只有1件符合条件的商品。",
        },
    )
    assert grade["ranking_applicable"] is True
    assert grade["task_score"] == pytest.approx(100)
