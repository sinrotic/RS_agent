"""真实画像对照、类目修正与评分门槛；受控执行不是能力实测。"""

import copy
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.request import Request, urlopen

import pytest

from rs_core.offline.evaluation.skill_benchmark.catalog_curation import curate_item, title_traits
from rs_core.offline.evaluation.skill_benchmark.contrast_examples import (
    build_contrast_examples,
    formula_reference,
)
from rs_core.offline.evaluation.skill_benchmark.dataset import (
    fingerprint,
    load_benchmark,
    validate_benchmark,
)
from rs_core.offline.evaluation.skill_benchmark.environment import FixtureEnvironment
from rs_core.offline.evaluation.skill_benchmark.profile_dataset import (
    build_profile_contrast_benchmark,
)
from rs_core.offline.evaluation.skill_benchmark.profile_matching import (
    contrast_metrics,
    needs_preference_confirmation,
)
from rs_core.offline.evaluation.skill_benchmark.runner import run_benchmark
from rs_core.offline.evaluation.skill_benchmark.scoring import evaluate_turn


@pytest.fixture(scope="module")
def benchmark():
    source = load_benchmark(
        Path(__file__).resolve().parents[1] / "benchmarks/skill_benchmark/v3/benchmark.json"
    )
    before = fingerprint(source)
    result = build_profile_contrast_benchmark(source)
    assert fingerprint(source) == before
    return result


def member_tasks(benchmark, kind, field="tip_mm"):
    group = next(
        group
        for group in benchmark["contrast_groups"]
        if group["kind"] == kind and group["spec"]["field"] == field
    )
    lookup = {task["task_id"]: task for task in benchmark["tasks"]}
    return group, [lookup[task_id] for task_id in group["task_ids"]]


def answer(item_id):
    return {
        "item_ids": [item_id],
        "outcome": "recommend",
        "observed_item_ids": [item_id],
        "message": "参考建议",
    }


def test_builder_keeps_true_users_splits_and_adds_matched_pairs(benchmark):
    stats = validate_benchmark(benchmark)
    assert stats["profile_count"] == stats["family_count"] == 150
    assert stats["task_count"] > 1871
    assert len(benchmark["contrast_groups"]) > 20
    assert benchmark["manifest"]["catalog_curation"]["full_semantic_review"] == "pending"
    assert all(task["review_status"] == "pending" for task in benchmark["tasks"])
    for group in benchmark["contrast_groups"]:
        members = [task for task in benchmark["tasks"] if task["task_id"] in group["task_ids"]]
        assert len({task["profile_user_id"] for task in members}) == 2
        assert len({task["split"] for task in members}) == 1
        assert len({task["turns"][0]["user_message"] for task in members}) == 1


@pytest.mark.parametrize(
    "item_id,category",
    [
        ("B09PTV7FDP", "Heart Rate Monitors"),
        ("B09Z4HV86M", "Wi-Fi Range Extenders"),
        ("B0BL79KPTX", "Open-Ear Headphones"),
        ("B09BC3MG1X", "Pen Refills"),
        ("B0BWF1LXQL", "Micro SD Memory Cards"),
        ("B07DBTFKD9", "SWR Meters"),
        ("B0141EPA7S", "CB Radio Microphones"),
        ("B0B8Z2C1J8", "Sticky Note Dispensers"),
        ("B0778M33SB", "Keyboards"),
    ],
)
def test_known_category_contradictions_are_corrected_with_evidence(benchmark, item_id, category):
    item = next(item for item in benchmark["catalog"] if item["item_id"] == item_id)
    assert item["category"] == category
    assert item["category_correction"]["evidence"] == item["title"]
    assert item["category_correction"]["original_category"] != category
    assert curate_item(item) == item


@pytest.mark.parametrize(
    "task_id,turn_index,item_id",
    [
        ("profile-family-070-customer-gift_needs", 1, "B09PTV7FDP"),
        ("profile-family-001-customer-budget_change", 1, "B0BL79KPTX"),
        ("profile-family-012-customer-missing_budget", 1, "B09BC3MG1X"),
    ],
)
def test_mislabeled_product_can_no_longer_score_full_marks(benchmark, task_id, turn_index, item_id):
    task = next(task for task in benchmark["tasks"] if task["task_id"] == task_id)
    grade = evaluate_turn(benchmark["catalog"], task["turns"][turn_index]["gold"], answer(item_id))
    assert grade["task_score"] == 0 and not grade["success"]
    assert "hard_constraint_failed" in grade["violations"]


def test_missing_or_conflicting_title_attributes_remain_unknown():
    assert (
        title_traits(
            {"category": "Earbud Headphones", "title": "Bluetooth headphones with wired cable"}
        )
        == {}
    )
    assert (
        title_traits({"category": "Gel Ink Rollerball Pens", "title": "Gel pens, medium point"})
        == {}
    )
    assert (
        title_traits({"category": "Gel Ink Rollerball Pens", "title": "0.5mm and 0.7mm gel pens"})
        == {}
    )


def test_history_reward_is_confidence_discounted_and_cross_profile_controls_drop(benchmark):
    examples = build_contrast_examples(benchmark)["examples"]
    assert len(examples) == 3
    for example in examples:
        matrix = example["score_matrix_rows_users_columns_products"]
        assert matrix[0][0] == matrix[1][1] == 100
        assert matrix[0][1] < 100 and matrix[1][0] < 100
        assert example["swapped_pair_quality"] < example["matched_pair_quality"]
    pen = examples[0]
    assert pen["members"][0]["profile_evidence"]["counts"] == {"0.7": 3}
    assert pen["members"][1]["profile_evidence"]["counts"] == {"0.5": 1}
    assert pen["score_matrix_rows_users_columns_products"][0][1] == pytest.approx(62.5)
    assert pen["score_matrix_rows_users_columns_products"][1][0] == pytest.approx(75)


def test_current_override_is_a_hard_requirement_and_old_profile_cannot_compensate(benchmark):
    _, tasks = member_tasks(benchmark, "override")
    for task in tasks:
        gold = task["turns"][0]["gold"]
        assert gold["customer_policy"]["history_role"] == "disabled"
        correct = evaluate_turn(benchmark["catalog"], gold, answer("B07S5YQ16N"))
        wrong = evaluate_turn(benchmark["catalog"], gold, answer("B0BK6MRTTR"))
        assert correct["task_score"] == 100
        assert wrong["task_score"] == 0 and not wrong["success"]


def test_gift_asks_recipient_need_and_uses_same_recipient_requirement_for_both_profiles(benchmark):
    _, tasks = member_tasks(benchmark, "gift")
    assert tasks[0]["turns"] == tasks[1]["turns"]
    for task in tasks:
        for turn in task["turns"]:
            assert turn["gold"]["customer_policy"]["history_role"] == "disabled"
            grade = evaluate_turn(
                benchmark["catalog"],
                turn["gold"],
                formula_reference(benchmark["catalog"], turn["gold"]),
            )
            assert grade["success"]


def test_sparse_history_clarifies_but_stronger_history_can_recommend(benchmark):
    _, tasks = member_tasks(benchmark, "uncertain")
    assert len(tasks[0]["turns"]) == 1 and len(tasks[1]["turns"]) == 2
    thin = tasks[1]
    assert thin["turns"][0]["gold"]["customer_policy"]["required_slots"] == ["profile_preference"]
    reference = formula_reference(benchmark["catalog"], thin["turns"][0]["gold"])
    assert (
        evaluate_turn(benchmark["catalog"], thin["turns"][0]["gold"], reference)[
            "interaction_score"
        ]
        == 100
    )
    premature = evaluate_turn(benchmark["catalog"], thin["turns"][0]["gold"], answer("B07S5YQ16N"))
    assert not premature["success"]
    vague = evaluate_turn(
        benchmark["catalog"],
        thin["turns"][0]["gold"],
        {
            "item_ids": [],
            "outcome": "uncertain_match",
            "message": "你有什么偏好？",
        },
    )
    assert "missing_specific_preference_question" in vague["violations"]
    assert needs_preference_confirmation(None)


def test_no_related_history_cannot_be_transferred_from_other_categories(benchmark):
    group, tasks = member_tasks(benchmark, "cross_category", "connection_type")
    assert group["spec"]["category"] == "Earbud Headphones"
    for task in tasks:
        assert task["turns"][0]["gold"]["customer_policy"]["action"] == "clarify"
        assert task["turns"][1]["gold"]["customer_policy"]["history_role"] == "disabled"


def test_fake_profile_gold_and_missing_contrast_member_are_rejected(benchmark):
    for mode in ("profile", "member", "split", "trait", "authorization", "groups"):
        forged = copy.deepcopy(benchmark)
        group, tasks = member_tasks(forged, "authorized")
        if mode == "profile":
            match = tasks[0]["turns"][0]["gold"]["customer_policy"]["profile_match"]
            match["evidence"][0]["item_id"] = "invented"
        elif mode == "member":
            forged["tasks"] = [
                task for task in forged["tasks"] if task["task_id"] != group["task_ids"][0]
            ]
        elif mode == "split":
            tasks[0]["split"] = "test"
        elif mode == "authorization":
            tasks[0]["turns"][0]["user_message"] = "买中性笔，预算20。"
        elif mode == "groups":
            forged["contrast_groups"] = []
        else:
            forged["catalog"][0]["tip_mm"] = "0.7"
            forged["manifest"]["catalog_sha256"] = fingerprint(forged["catalog"])
        with pytest.raises(ValueError):
            validate_benchmark(forged)


def test_contrast_metrics_include_missing_member_as_zero(benchmark):
    group, tasks = member_tasks(benchmark, "authorized")
    minimal = dict(benchmark, contrast_groups=[group])
    metrics = contrast_metrics(
        minimal,
        [{"task_id": tasks[0]["task_id"], "repeat": 0, "success": True, "ranking_score": 100}],
        split=group["split"],
        repeats=1,
    )
    assert metrics["mean_paired_quality"] == 0
    assert metrics["incomplete_group_trials"] == 1


def test_runner_scores_both_bound_profiles_with_independent_tool_provenance(benchmark):
    group, tasks = member_tasks(benchmark, "authorized")
    subset = copy.deepcopy(benchmark)
    subset["tasks"], subset["contrast_groups"] = copy.deepcopy(tasks), [copy.deepcopy(group)]
    subset["manifest"]["contrast_groups_sha256"] = fingerprint(subset["contrast_groups"])

    def adapter(request):
        assert "gold" not in request and "contrast_group_id" not in request

        def post(path, data):
            http = Request(
                request["fixture_url"] + path,
                data=json.dumps(data).encode(),
                headers={"Content-Type": "application/json"},
            )
            with urlopen(http) as response:
                return json.load(response)

        memory = post("/tool", {"tool_name": "session_memory", "arguments": {}})
        assert memory["profile_user_id"] == request["profile_user_id"]
        match = next(
            match for match in memory["behavioral_preferences"] if match["field"] == "tip_mm"
        )
        value = max(match["counts"], key=match["counts"].get)
        found = post(
            "/tool",
            {
                "tool_name": "recommend_candidates",
                "arguments": {
                    "constraints": {
                        "category": "Gel Ink Rollerball Pens",
                        "tip_mm": value,
                        "price_max": 20,
                    }
                },
            },
        )
        selected = found["items"][0]["item_id"]
        result = {
            "item_ids": [selected],
            "outcome": "recommend",
            "message": "按过去笔尖记录选的参考款。",
        }
        assert post("/customer", {"turn_index": 0, "answer": result})["done"]
        return {"turns": [result]}

    report = run_benchmark(
        subset, adapter, {"model": "controlled", "adapter_kind": "engineering_only"}
    )
    assert report["summary"]["success_rate"] == 1
    assert report["summary"]["profile_contrasts"]["mean_paired_quality"] == 100
    assert report["summary"]["independent_statistical_clusters"] == 1
    assert all(trial["profile_snapshot_sha256"] for trial in report["trials"])


def test_environment_exposes_corrected_facts_and_scoped_history_only_for_bound_user(benchmark):
    _, tasks = member_tasks(benchmark, "authorized")
    profile = benchmark["profiles"][tasks[0]["profile_user_id"]]
    with FixtureEnvironment(
        benchmark["catalog"], {"profile": profile, "exclude_seen_items": False}
    ) as env:
        memory = env.call("session_memory", {})
        assert memory["behavioral_preferences"]
        assert env.call("session_memory", {"profile_user_id": "another"})["status"] == "FAILED"
        speakers = env.call(
            "recommend_candidates",
            {"constraints": {"category": "Portable Bluetooth Speakers", "price_max": 40}},
        )
        assert "B09PTV7FDP" not in {item["item_id"] for item in speakers["items"]}


@pytest.mark.skipif(not os.environ.get("RS_BENCHMARK_TEST_JAVA"), reason="需要已构建的 JDK21 入口")
def test_real_java_loop_receives_distinct_profiles_and_attribute_filtered_products(benchmark):
    from rs_core.offline.evaluation.skill_benchmark.adapters import prepare_java_command
    from rs_core.offline.evaluation.skill_benchmark.runner import SubprocessAgent

    group, tasks = member_tasks(benchmark, "authorized")
    subset = copy.deepcopy(benchmark)
    subset["tasks"], subset["contrast_groups"] = copy.deepcopy(tasks), [copy.deepcopy(group)]
    subset["manifest"]["contrast_groups_sha256"] = fingerprint(subset["contrast_groups"])
    received = []

    class Model(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            context = json.loads(body["messages"][0]["content"].rsplit("\n", 1)[-1])
            profile = context["benchmark_profile_snapshot"]
            match = next(
                match for match in profile["behavioral_preferences"] if match["field"] == "tip_mm"
            )
            value = max(match["counts"], key=match["counts"].get)
            received.append(value)
            if not any(
                result["tool_name"] == "recommend_semantic_recall"
                for result in context.get("tool_results", [])
            ):
                name, arguments = (
                    "recommend_semantic_recall",
                    {
                        "query": "gel pen",
                        "constraints": {
                            "category": "Gel Ink Rollerball Pens",
                            "tip_mm": value,
                            "price_max": 20,
                        },
                        "return_count": 2,
                    },
                )
            else:
                name, arguments = (
                    "emit_final_answer",
                    {
                        "blocks": [
                            {
                                "type": "product_cards",
                                "item_ids": ["B0BK6MRTTR" if value == "0.7" else "B07S5YQ16N"],
                            }
                        ]
                    },
                )
            payload = json.dumps(
                {
                    "choices": [
                        {
                            "message": {
                                "tool_calls": [
                                    {
                                        "id": f"controlled-{len(received)}",
                                        "type": "function",
                                        "function": {
                                            "name": name,
                                            "arguments": json.dumps(arguments),
                                        },
                                    }
                                ]
                            }
                        }
                    ]
                }
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(payload)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Model)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        command = prepare_java_command(
            Path(__file__).resolve().parents[2], os.environ["RS_BENCHMARK_TEST_JAVA"]
        )
        report = run_benchmark(
            subset,
            SubprocessAgent(command, timeout=60),
            {
                "model": "controlled",
                "base_url": f"http://127.0.0.1:{server.server_port}/v1",
                "adapter_kind": "java_rs_agent_loop",
            },
        )
        assert report["summary"]["profile_contrasts"]["mean_paired_quality"] == 100
        assert report["summary"]["success_rate"] == 1
        assert set(received) == {"0.5", "0.7"}
        assert all(trial["runtime"]["profile_snapshot_sha256"] for trial in report["trials"])
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
