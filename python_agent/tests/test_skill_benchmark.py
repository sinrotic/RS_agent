"""评测公共 Interface 的行为验收，不依赖 Agent 自报分数。"""

import pytest
import os

from rs_core.offline.evaluation.skill_benchmark import evaluate_turn
from rs_core.offline.evaluation.skill_benchmark.environment import FixtureEnvironment
from rs_core.offline.evaluation.skill_benchmark.dataset import build_benchmark, validate_benchmark
from rs_core.offline.evaluation.skill_benchmark.runner import run_benchmark, compare_runs


@pytest.fixture
def catalog():
    return [
        {
            "item_id": "A",
            "category": "headphones",
            "price": 260,
            "currency": "CNY",
            "wireless": True,
            "weight": 150,
            "color": "black",
        },
        {
            "item_id": "B",
            "category": "headphones",
            "price": 290,
            "currency": "CNY",
            "wireless": True,
            "weight": 225,
            "color": "black",
        },
        {
            "item_id": "C",
            "category": "headphones",
            "price": 320,
            "currency": "CNY",
            "wireless": True,
            "weight": 100,
            "color": "black",
        },
        {
            "item_id": "D",
            "category": "headphones",
            "price": 180,
            "currency": "CNY",
            "wireless": False,
            "weight": 150,
            "color": "black",
        },
        {
            "item_id": "E",
            "category": "headphones",
            "price": 220,
            "currency": "CNY",
            "wireless": True,
            "weight": 225,
            "color": "white",
        },
    ]


@pytest.fixture
def gold():
    return {
        "k": 2,
        "hard": [
            {"field": "category", "op": "eq", "value": "headphones"},
            {"field": "currency", "op": "eq", "value": "CNY"},
            {"field": "price", "op": "lte", "value": 300},
            {"field": "wireless", "op": "eq", "value": True},
        ],
        "soft": [
            {"field": "weight", "op": "minimize", "best": 150, "worst": 300, "weight": 0.6},
            {"field": "color", "op": "eq", "value": "black", "weight": 0.4},
        ],
    }


def test_ranking_quality_uses_frozen_catalog_and_independent_known_example(catalog, gold):
    result = evaluate_turn(catalog, gold, {"item_ids": ["B", "A"], "outcome": "recommend"})
    assert result["task_score"] == pytest.approx(92.31984112820403)


def test_unproven_product_provenance_cannot_pass_even_with_perfect_ids(catalog, gold):
    result = evaluate_turn(
        catalog, gold, {"item_ids": ["A", "B"], "outcome": "recommend", "observed_item_ids": ["A"]}
    )
    assert "unobserved_item" in result["violations"]


def test_fixture_tools_obey_actual_filters_instead_of_replaying_next_answer(catalog):
    with FixtureEnvironment(catalog, {"tool_call_budget": 8}) as environment:
        answer = environment.call(
            "recommend_semantic_recall", {"constraints": {"max_price": 230}, "return_count": 10}
        )
        assert [item["item_id"] for item in answer["items"]] == ["D", "E"]


def test_seed_tasks_are_grounded_and_family_splits_do_not_leak(tmp_path):
    import json

    source = tmp_path / "metadata.jsonl"
    rows = [
        {
            "parent_asin": f"p{group}-{i}",
            "title": f"Product {group} {i}",
            "categories": ["Electronics", f"type-{group}"],
            "main_category": "All Electronics",
            "price": 10 + i,
            "store": "Shop",
        }
        for group in range(10)
        for i in range(4)
    ]
    source.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
    benchmark = build_benchmark([source], catalog_limit=40, max_scan_rows=100)
    assert validate_benchmark(benchmark)["task_count"] == 40
    assert benchmark["manifest"]["human_reviewed"] is False


def test_failed_rollouts_stay_in_denominator_and_gold_is_not_exposed(catalog, gold):
    from rs_core.offline.evaluation.skill_benchmark.dataset import fingerprint

    benchmark = {
        "schema_version": "rs-skill-benchmark/1",
        "catalog": catalog,
        "manifest": {"catalog_sha256": fingerprint(catalog), "human_reviewed": False},
        "environment": {},
        "tasks": [
            {
                "task_id": "task-1",
                "family_id": "f1",
                "kind": "clear",
                "review_status": "pending",
                "split": "dev",
                "turns": [{"user_message": "请推荐2件耳机", "limit": 2, "gold": gold}],
            }
        ],
    }

    def unavailable_agent(request):
        assert "gold" not in str(request)
        raise TimeoutError("model unavailable")

    run = run_benchmark(
        benchmark,
        unavailable_agent,
        {"model": "test", "adapter_kind": "engineering_only"},
        repeats=2,
    )
    assert run["summary"]["planned_trials"] == 2
    assert run["summary"]["success_rate"] == 0
    assert run["summary"]["failure_reasons"]["execution_failed"] == 2
    assert compare_runs(run, run)["eligible_for_promotion"] is False


def test_insufficient_matches_require_an_explicit_limitation(catalog, gold):
    gold["hard"].append({"field": "item_id", "op": "eq", "value": "A"})
    result = evaluate_turn(catalog, gold, {"item_ids": ["A"], "outcome": "recommend"})
    assert "missing_limitation_explanation" in result["violations"]


@pytest.mark.smoke
@pytest.mark.skipif(
    not os.environ.get("RS_BENCHMARK_TEST_JAVA"), reason="需显式提供 JDK21 和已编译 Java 评测入口"
)
def test_real_java_loop_uses_fixture_and_isolates_candidate_skill():
    from pathlib import Path
    from rs_core.offline.evaluation.skill_benchmark.adapters import prepare_java_command
    from rs_core.offline.evaluation.skill_benchmark.engineering import run_java_selfcheck

    command = prepare_java_command(
        Path(__file__).resolve().parents[2], os.environ["RS_BENCHMARK_TEST_JAVA"]
    )
    result = run_java_selfcheck(command)
    assert result["baseline"]["summary"]["mean_ranking_score"] == pytest.approx(100)
    assert result["candidate"]["summary"]["mean_ranking_score"] == pytest.approx(92.31984112820403)
    assert result["comparison"]["eligible_for_promotion"] is False
    assert (
        result["baseline"]["trials"][0]["turns"][0]["answer"]["message"]
        == "这是受控模型的工程验证结果，不代表真实模型能力。"
    )


def test_malformed_recommendation_list_is_not_silently_interpreted_as_ids(catalog, gold):
    with pytest.raises(ValueError, match="item_ids"):
        evaluate_turn(catalog, gold, {"item_ids": "AB", "outcome": "recommend"})


def test_numeric_one_is_not_evidence_of_wireless_true(catalog, gold):
    catalog[0]["wireless"] = 1
    result = evaluate_turn(catalog, gold, {"item_ids": ["A", "B"], "outcome": "recommend"})
    assert result["success"] is False


def test_rank_improvement_can_be_detected_when_both_versions_already_succeed():
    import copy

    baseline = {
        "manifest": {
            "benchmark_sha256": "dataset",
            "catalog_sha256": "catalog",
            "run_config": {"adapter_kind": "java_rs_agent_loop"},
            "split": "test",
            "repeats": 1,
            "runtime_sha256": ["runtime"],
            "scorer_version": "v1",
            "implementation_sha256": {},
            "human_reviewed": True,
        },
        "summary": {
            "planned_trials": 20,
            "success_rate": 1,
            "mean_ranking_score": 80,
            "execution_failures": 0,
        },
        "trials": [
            {
                "task_id": f"task-{i}",
                "family_id": f"family-{i}",
                "repeat": 0,
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
    assert compare_runs(baseline, candidate)["eligible_for_promotion"] is True


def test_incomplete_multiturn_task_has_zero_gated_ranking_score(catalog, gold):
    import json
    from urllib.request import Request, urlopen
    from rs_core.offline.evaluation.skill_benchmark.dataset import fingerprint

    turns = [{"user_message": "请推荐2件耳机", "limit": 2, "gold": gold}] * 2
    benchmark = {
        "schema_version": "rs-skill-benchmark/1",
        "catalog": catalog,
        "manifest": {"catalog_sha256": fingerprint(catalog), "human_reviewed": False},
        "environment": {},
        "tasks": [
            {
                "task_id": "multi",
                "family_id": "f",
                "kind": "budget_change",
                "review_status": "pending",
                "split": "dev",
                "turns": turns,
            }
        ],
    }

    def model(request):
        data = json.dumps(
            {"tool_name": "catalog_card", "arguments": {"item_ids": ["A", "B"]}}
        ).encode()
        with urlopen(
            Request(
                request["fixture_url"] + "/tool",
                data=data,
                headers={"Content-Type": "application/json"},
            ),
            timeout=2,
        ) as response:
            assert response.status == 200
        return {
            "turns": [
                {"item_ids": ["A", "B"], "outcome": "recommend"},
                {"item_ids": [], "outcome": "recommend"},
            ]
        }

    run = run_benchmark(benchmark, model, {"adapter_kind": "engineering_only"})
    assert run["trials"][0]["ranking_score"] == 0


def test_dataset_builder_can_expand_independent_families(tmp_path):
    import json

    source = tmp_path / "larger.jsonl"
    rows = [
        {
            "parent_asin": f"x{group}-{i}",
            "title": f"Item {group} {i}",
            "categories": [f"type-{group}"],
            "price": 20 + i,
        }
        for group in range(12)
        for i in range(4)
    ]
    source.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
    benchmark = build_benchmark([source], catalog_limit=48, max_scan_rows=100, family_limit=12)
    assert validate_benchmark(benchmark)["task_count"] == 48


@pytest.mark.parametrize(
    "ids,score,ndcg",
    [
        (["A", "B"], 100, 1),
        (["A", "E"], 82.49424225238899, 0.8249424225238899),
        (["A", "C"], 0, 0.6936492394168075),
        (["A"], 0, 0.6936492394168075),
        (["A", "A"], 0, 0.6936492394168075),
        (["A", "B", "C"], 0, 1),
        ([], 0, 0),
    ],
)
def test_full_returned_list_is_gated_without_hiding_bad_or_missing_items(
    catalog, gold, ids, score, ndcg
):
    result = evaluate_turn(catalog, gold, {"item_ids": ids, "outcome": "recommend"})
    assert result["task_score"] == pytest.approx(score)
    assert result["ndcg"] == pytest.approx(ndcg)


def test_missing_soft_fact_keeps_its_weight_in_denominator(catalog, gold):
    catalog[0]["weight"] = None
    result = evaluate_turn(catalog, gold, {"item_ids": ["A", "B"], "outcome": "recommend"})
    assert result["items"][0]["utility"] == pytest.approx(0.4)
    assert result["items"][0]["soft_coverage"] == pytest.approx(0.4)


@pytest.mark.parametrize(
    "known_violation,expected,limitation",
    [
        (False, "uncertain_match", "unknown_attributes"),
        (True, "no_match", "no_matches"),
    ],
)
def test_unknown_attribute_and_proven_no_match_are_different(
    catalog, gold, known_violation, expected, limitation
):
    gold["hard"].append({"field": "warranty_years", "op": "gte", "value": 5})
    if known_violation:
        gold["hard"].append({"field": "category", "op": "eq", "value": "not_in_catalog"})
    result = evaluate_turn(
        catalog,
        gold,
        {
            "item_ids": [],
            "outcome": expected,
            "message": "当前目录信息不足" if not known_violation else "当前目录没有匹配商品",
            "limitations": [limitation],
        },
    )
    assert result["success"] is True
    assert result["ndcg"] is None


def test_environment_budget_faults_and_trial_state_are_isolated(catalog):
    with FixtureEnvironment(catalog, {"tool_call_budget": 1}) as first:
        first.call("catalog_card", {"item_ids": ["A"]})
        assert first.call("catalog_card", {"item_ids": ["B"]})["error"] == "TOOL_BUDGET_EXCEEDED"
    with FixtureEnvironment(catalog, {"unavailable_tools": ["rag_support"]}) as second:
        assert second.observed_item_ids == set()
        assert second.call("rag_support", {})["error"] == "TOOL_UNAVAILABLE"
        assert second.call("catalog_card", {"item_ids": ["B"]})["items"][0]["item_id"] == "B"


def test_invalid_soft_scale_is_an_evaluator_error_not_an_agent_failure(catalog, gold):
    gold["soft"][0]["best"] = 300
    with pytest.raises(ValueError, match="标尺方向"):
        evaluate_turn(catalog, gold, {"item_ids": ["A", "B"], "outcome": "recommend"})


def test_family_split_leakage_is_rejected(tmp_path):
    import json
    import copy

    source = tmp_path / "metadata.jsonl"
    source.write_text(
        "\n".join(
            json.dumps(
                {
                    "parent_asin": f"p{group}-{i}",
                    "title": "Item",
                    "categories": [str(group)],
                    "price": 10 + i,
                }
            )
            for group in range(10)
            for i in range(4)
        ),
        encoding="utf-8",
    )
    benchmark = build_benchmark([source], catalog_limit=40, max_scan_rows=100)
    leaked = copy.deepcopy(benchmark["tasks"][0])
    leaked.update(task_id="leaked", split="test")
    benchmark["tasks"].append(leaked)
    with pytest.raises(ValueError, match="泄漏"):
        validate_benchmark(benchmark)
