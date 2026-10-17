"""顾客会话通过已有评分、工具环境和执行 Interface 验收。"""

import copy
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.request import Request, urlopen

import pytest

from rs_core.offline.evaluation.skill_benchmark import evaluate_turn
from rs_core.offline.evaluation.skill_benchmark.dataset import fingerprint, validate_benchmark
from rs_core.offline.evaluation.skill_benchmark.environment import FixtureEnvironment
from rs_core.offline.evaluation.skill_benchmark.runner import run_benchmark


@pytest.fixture
def catalog():
    return [
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
    ]


@pytest.fixture
def gold():
    return {
        "k": 1,
        "hard": [{"field": "category", "op": "eq", "value": "pens"}],
        "soft": [],
        "customer_policy": {
            "action": "clarify",
            "required_slots": ["budget"],
            "known_slots": ["category", "quantity"],
            "max_questions": 2,
            "history_role": "weak_reference",
        },
    }


def test_missing_budget_rewards_targeted_question_not_premature_recommendation(catalog, gold):
    question = evaluate_turn(
        catalog,
        gold,
        {"item_ids": [], "outcome": "uncertain_match", "message": "你的预算大概是多少？"},
    )
    assert question["success"] is True
    assert question["interaction_score"] == 100
    assert question["ranking_applicable"] is False
    premature = evaluate_turn(
        catalog, gold, {"item_ids": ["A"], "outcome": "recommend", "message": "这个符合你的预算。"}
    )
    assert premature["success"] is False
    assert "premature_recommendation" in premature["violations"]


def test_clarification_rejects_reasking_known_fields_and_self_reported_slots(catalog, gold):
    for answer, violation in (
        (
            {
                "item_ids": [],
                "outcome": "uncertain_match",
                "message": "你想买什么商品？预算是多少？",
            },
            "reasks_known_information",
        ),
        (
            {
                "item_ids": [],
                "outcome": "uncertain_match",
                "message": "还需要其他信息。",
                "asked_slots": ["budget"],
            },
            "missing_required_clarification",
        ),
        (
            {"item_ids": [], "outcome": "uncertain_match", "message": "预算多少？请告诉我手机号？"},
            "irrelevant_personal_information_request",
        ),
    ):
        grade = evaluate_turn(catalog, gold, answer)
        assert not grade["success"] and violation in grade["violations"]


def test_user_cannot_supply_device_model_gets_safe_guidance_not_invented_compatibility(
    catalog, gold
):
    gold["customer_policy"].update(action="defer")
    guide = evaluate_turn(
        catalog,
        gold,
        {
            "item_ids": [],
            "outcome": "uncertain_match",
            "message": "现在无法确认兼容性，先在设备设置里查看型号，再核对接口。",
        },
    )
    assert guide["success"] is True
    vague = evaluate_turn(
        catalog, gold, {"item_ids": [], "outcome": "uncertain_match", "message": "信息不足。"}
    )
    assert vague["success"] is False


def test_history_is_diagnostic_not_a_hidden_customer_requirement(catalog, gold):
    gold["customer_policy"] = {
        "action": "recommend",
        "history_role": "weak_reference",
        "history_reference": {"store_scores": {"Blue": 1}, "category_scores": {"pens": 1}},
    }
    grade = evaluate_turn(catalog, gold, {"item_ids": ["B"], "outcome": "recommend"})
    assert grade["success"] and grade["task_score"] == 100
    assert grade["history_alignment"]["store_mean"] == 0
    assert grade["history_alignment"]["used_for_primary_score"] is False
    gold["customer_policy"]["history_role"] = "disabled"
    gift = evaluate_turn(catalog, gold, {"item_ids": ["B"], "outcome": "recommend"})
    assert gift["history_alignment"] is None


def test_customer_environment_allows_repurchase_and_history_does_not_override_price(catalog):
    catalog[0]["price"], catalog[1]["price"] = 30, 10
    profile = {
        "profile_user_id": "u",
        "seen_item_ids": ["A"],
        "profile_preferences": {"category_scores": {"pens": 1}, "store_scores": {"Blue": 1}},
    }
    with FixtureEnvironment(
        catalog,
        {
            "profile": profile,
            "exclude_seen_items": False,
            "history_retrieval_role": "weak_reference",
        },
    ) as environment:
        answer = environment.call(
            "recommend_profile_pipeline", {"constraints": {"category": "pens"}, "return_count": 2}
        )
        assert [item["item_id"] for item in answer["items"]] == ["B", "A"]


def test_runner_releases_customer_budget_only_after_actual_valid_question(catalog, gold):
    final_gold = copy.deepcopy(gold)
    final_gold["customer_policy"]["action"] = "recommend"
    final_gold["hard"].append({"field": "price", "op": "lte", "value": 20})
    benchmark = {
        "schema_version": "rs-skill-benchmark/1",
        "catalog": catalog,
        "manifest": {"catalog_sha256": fingerprint(catalog), "human_reviewed": False},
        "environment": {},
        "tasks": [
            {
                "task_id": "customer",
                "family_id": "family",
                "split": "dev",
                "kind": "missing_budget",
                "review_status": "pending",
                "dialogue_policy": "conditional_customer/1",
                "turns": [
                    {"user_message": "想买支笔，帮我选1款。", "limit": 1, "gold": gold},
                    {"user_message": "预算20以内。", "limit": 1, "gold": final_gold},
                ],
            }
        ],
    }

    def post(request, path, value):
        http = Request(
            request["fixture_url"] + path,
            data=json.dumps(value).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urlopen(http) as response:
            return json.load(response)

    def customer_adapter(request):
        assert len(request["turns"]) == 1 and "预算20" not in json.dumps(
            request, ensure_ascii=False
        )
        first = {"item_ids": [], "outcome": "uncertain_match", "message": "预算大概是多少？"}
        continuation = post(request, "/customer", {"turn_index": 0, "answer": first})
        assert continuation["next_turn"]["user_message"] == "预算20以内。"
        post(request, "/turn", {"turn_index": 1})
        post(request, "/tool", {"tool_name": "catalog_card", "arguments": {"item_ids": ["A"]}})
        second = {"item_ids": ["A"], "outcome": "recommend", "message": "这个不超过20。"}
        assert post(request, "/customer", {"turn_index": 1, "answer": second})["done"] is True
        return {"turns": [first, second]}

    report = run_benchmark(
        benchmark, customer_adapter, {"model": "controlled", "adapter_kind": "engineering_only"}
    )
    assert report["summary"]["success_rate"] == 1
    assert report["trials"][0]["dialogue_complete"] is True

    def premature_adapter(request):
        first = {"item_ids": ["A"], "outcome": "recommend", "message": "我猜你预算20。"}
        stop = post(request, "/customer", {"turn_index": 0, "answer": first})
        assert stop["done"] and stop["blocked"] and "next_turn" not in stop
        return {"turns": [first]}

    failed = run_benchmark(
        benchmark, premature_adapter, {"model": "controlled", "adapter_kind": "engineering_only"}
    )
    assert failed["summary"]["success_rate"] == 0
    assert failed["trials"][0]["ranking_score"] == 0
    assert failed["trials"][0]["dialogue_complete"] is False


@pytest.mark.skipif(
    not os.environ.get("RS_BENCHMARK_TEST_JAVA"), reason="需要已构建的 JDK21 评测入口"
)
def test_real_java_loop_asks_then_receives_hidden_customer_reply(catalog, gold):
    from rs_core.offline.evaluation.skill_benchmark.adapters import prepare_java_command
    from rs_core.offline.evaluation.skill_benchmark.runner import SubprocessAgent

    final_gold = copy.deepcopy(gold)
    final_gold["customer_policy"]["action"] = "recommend"
    final_gold["hard"].append({"field": "price", "op": "lte", "value": 20})
    benchmark = {
        "schema_version": "rs-skill-benchmark/1",
        "catalog": catalog,
        "manifest": {"catalog_sha256": fingerprint(catalog), "human_reviewed": False},
        "environment": {},
        "tasks": [
            {
                "task_id": "customer",
                "family_id": "family",
                "split": "dev",
                "kind": "missing_budget",
                "review_status": "pending",
                "dialogue_policy": "conditional_customer/1",
                "turns": [
                    {"user_message": "想买支笔，帮我选1款。", "limit": 1, "gold": gold},
                    {"user_message": "预算20以内。", "limit": 1, "gold": final_gold},
                ],
            }
        ],
    }
    requests = []

    class Model(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append(body)
            context = json.loads(body["messages"][0]["content"].rsplit("\n", 1)[-1])
            if body["messages"][1]["content"] == "想买支笔，帮我选1款。":
                name, arguments = (
                    "emit_final_answer",
                    {"blocks": [{"type": "followup_question", "content": "你的预算大概是多少？"}]},
                )
            elif not any(
                result["tool_name"] == "recommend_semantic_recall"
                for result in context.get("tool_results", [])
            ):
                name, arguments = (
                    "recommend_semantic_recall",
                    {
                        "query": "pens",
                        "constraints": {"category": "pens", "price_max": 20},
                        "return_count": 2,
                    },
                )
            else:
                name, arguments = (
                    "emit_final_answer",
                    {"blocks": [{"type": "product_cards", "item_ids": ["A"]}]},
                )
            payload = json.dumps(
                {
                    "choices": [
                        {
                            "message": {
                                "tool_calls": [
                                    {
                                        "id": f"controlled-{len(requests)}",
                                        "type": "function",
                                        "function": {
                                            "name": name,
                                            "arguments": json.dumps(arguments, ensure_ascii=False),
                                        },
                                    }
                                ]
                            }
                        }
                    ]
                },
                ensure_ascii=False,
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
            benchmark,
            SubprocessAgent(command, timeout=60),
            {
                "model": "controlled",
                "base_url": f"http://127.0.0.1:{server.server_port}/v1",
                "adapter_kind": "engineering_only_java_loop",
            },
        )
        assert report["summary"]["success_rate"] == 1
        assert report["trials"][0]["turns"][0]["answer"]["questions"] == ["你的预算大概是多少？"]
        assert "预算20" not in json.dumps(requests[0], ensure_ascii=False)
        assert "customer_turns" not in json.dumps(requests, ensure_ascii=False)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_customer_version_preserves_evidence_but_replaces_hidden_profile_requirements():
    from rs_core.offline.evaluation.skill_benchmark.dataset import load_benchmark
    from rs_core.offline.evaluation.skill_benchmark.customer_dataset import build_customer_benchmark

    source = load_benchmark(
        Path(__file__).resolve().parents[1] / "benchmarks/skill_benchmark/v3/benchmark.json"
    )
    original_hash = fingerprint(source)
    built = build_customer_benchmark(source)
    stats = validate_benchmark(built)
    assert stats["profile_count"] == 150 and stats["family_count"] == 150
    assert fingerprint(source) == original_hash
    assert built["catalog"] == source["catalog"] and built["profiles"] == source["profiles"]
    for task in built["tasks"]:
        assert task["dialogue_policy"] == "conditional_customer/1"
        for turn in task["turns"]:
            assert not any(
                token in turn["user_message"]
                for token in ("画像", "35%", "权重", "SOURCE_UNIT", "归一化", "评价过")
            )
            assert not any(c["op"] == "lookup" for c in turn["gold"]["soft"])
            assert not any(c["op"] == "not_in" for c in turn["gold"]["hard"])
            assert turn["gold"]["customer_policy"]["history_role"] in {"weak_reference", "disabled"}
    gifts = [task for task in built["tasks"] if task["kind"] == "gift_needs"]
    assert len(gifts) == 150 and all(
        task["turns"][0]["gold"]["customer_policy"]["history_role"] == "disabled" for task in gifts
    )
    assert "compatibility_unknown" in stats["kind_counts"]
    assert "repeat_purchase" in stats["kind_counts"]
    assert stats["kind_counts"]["confirmed_history_preference"] == 150


def test_customer_confirmed_past_store_is_an_explicit_priority_not_an_inferred_weight(
    catalog, gold
):
    gold["customer_policy"] = {"action": "recommend", "history_role": "weak_reference"}
    gold["soft"] = [{"field": "store", "op": "eq", "value": "Blue", "weight": 1}]
    chosen = evaluate_turn(catalog, gold, {"item_ids": ["A"], "outcome": "recommend"})
    alternative = evaluate_turn(catalog, gold, {"item_ids": ["B"], "outcome": "recommend"})
    assert chosen["task_score"] == 100
    assert alternative["success"] and alternative["task_score"] == 50


def test_explicit_store_preference_does_not_zero_all_valid_alternatives(catalog, gold):
    gold["customer_policy"] = {
        "action": "recommend",
        "history_role": "disabled",
        "known_slots": ["budget", "category", "quantity"],
    }
    gold["soft"] = [{"field": "store", "op": "eq", "value": "UnknownStore", "weight": 1}]
    grade = evaluate_turn(catalog, gold, {"item_ids": ["B"], "outcome": "recommend"})
    assert grade["ranking_applicable"] and grade["task_score"] == 100
    unnecessary = evaluate_turn(
        catalog,
        gold,
        {
            "item_ids": ["B"],
            "outcome": "recommend",
            "questions": ["预算是多少？"],
            "message": "预算是多少？",
        },
    )
    assert not unnecessary["success"] and "unnecessary_clarification" in unnecessary["violations"]


def test_full_category_path_distinguishes_same_named_accessories(catalog):
    catalog[0].update(category="Stands", category_path=["Speaker Accessories", "Stands"])
    catalog[1].update(category="Stands", category_path=["Laptop Accessories", "Stands"])
    with FixtureEnvironment(catalog, {"exclude_seen_items": False}) as environment:
        result = environment.call(
            "recommend_candidates",
            {
                "constraints": {
                    "category": "Stands",
                    "category_path": ["Laptop Accessories", "Stands"],
                }
            },
        )
        assert [item["item_id"] for item in result["items"]] == ["B"]
