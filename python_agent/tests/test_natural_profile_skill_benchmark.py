"""通过评分、隔离环境和运行接口验证自然购物；不用合成标签冒充人审。"""

import copy
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from rs_core.offline.evaluation.skill_benchmark.scoring import evaluate_turn


@pytest.fixture
def pens():
    return [
        {
            "item_id": "A",
            "category": "pens",
            "category_path": ["pens"],
            "price": 15,
            "currency": "SOURCE_UNIT",
            "tip_mm": 0.7,
        },
        {
            "item_id": "B",
            "category": "pens",
            "category_path": ["pens"],
            "price": 12,
            "currency": "SOURCE_UNIT",
            "tip_mm": 0.5,
        },
    ]


@pytest.fixture
def natural_gold():
    return {
        "k": 1,
        "hard": [
            {"field": "category", "op": "eq", "value": "pens"},
            {"field": "category_path", "op": "eq", "value": ["pens"]},
            {"field": "price", "op": "lte", "value": 20},
        ],
        "soft": [],
        "customer_policy": {
            "action": "recommend",
            "history_role": "environment_reference",
            "history_authorization": "bound_profile_permission",
            "known_slots": ["budget", "category", "quantity"],
            "evaluation_policy": "natural-shopping/1",
            "profile_match": {
                "version": "category-scoped-positive-history/1",
                "category": "pens",
                "category_path": ["pens"],
                "field": "tip_mm",
                "counts": {"0.7": 3},
                "distribution": {"0.7": 1.0},
                "known_items": 3,
                "relevant_items": 3,
                "coverage": 1.0,
                "confidence": 0.6,
                "evidence": [
                    {"item_id": f"old-{index}", "timestamp": index, "value": "0.7"}
                    for index in range(3)
                ],
            },
        },
    }


def suggestion(item_id, **extra):
    return {
        "item_ids": [item_id],
        "observed_item_ids": [item_id],
        "outcome": "recommend",
        "message": "先参考这款。",
        **extra,
    }


def test_natural_profile_is_evidence_not_a_hidden_hard_requirement(pens, natural_gold):
    matching = evaluate_turn(pens, natural_gold, suggestion("A"))
    alternative = evaluate_turn(pens, natural_gold, suggestion("B"))
    assert matching["task_score"] == alternative["task_score"] == 100
    assert matching["profile_evidence"]["score"] == pytest.approx(60)
    assert alternative["profile_evidence"]["score"] == 0
    assert matching["profile_evidence"]["used_for_primary_score"] is False
    assert matching["quality_basis"] == "declared_constraints_only"


def test_low_risk_preference_allows_recommendation_or_one_targeted_question(pens, natural_gold):
    gold = copy.deepcopy(natural_gold)
    gold["customer_policy"].update(
        action="recommend_or_clarify",
        clarification_need="optional",
        required_slots=["profile_preference"],
        clarification_field="tip_mm",
        max_questions=2,
    )
    direct = evaluate_turn(pens, gold, suggestion("B"))
    question = evaluate_turn(
        pens,
        gold,
        {
            "item_ids": [],
            "outcome": "clarify",
            "message": "笔尖想要细一点还是粗一点？",
        },
    )
    assert direct["success"] and question["success"]
    assert direct["interaction_action"] == "recommend"
    assert question["interaction_action"] == "clarify"
    assert question["clarification_need"] == "optional"
    repeated = evaluate_turn(
        pens,
        gold,
        {
            "item_ids": [],
            "outcome": "clarify",
            "message": "笔尖要多粗？预算多少？",
        },
    )
    assert not repeated["success"]
    assert "reasks_known_information" in repeated["violations"]


def test_builder_removes_trigger_phrases_and_binds_permission_to_real_profile():
    from rs_core.offline.evaluation.skill_benchmark.dataset import load_benchmark, fingerprint
    from rs_core.offline.evaluation.skill_benchmark.natural_dataset import build_natural_benchmark

    source = load_benchmark(
        Path(__file__).resolve().parents[1] / "benchmarks/skill_benchmark/v5/benchmark.json"
    )
    before = fingerprint(source)
    benchmark = build_natural_benchmark(source)
    assert fingerprint(source) == before
    assert benchmark["profiles"] == source["profiles"]
    assert len(benchmark["tasks"]) >= len(source["tasks"])
    for task in benchmark["tasks"]:
        assert (
            task["environment"]["profile_access"]["bound_profile_user_id"]
            == task["profile_user_id"]
        )
        for turn in task["turns"]:
            assert "照我以前的习惯" not in turn["user_message"]
            assert "按我以前的习惯" not in turn["user_message"]
            assert turn["gold"]["customer_policy"]["history_role"] != "authorized_reference"
    assert {group["kind"] for group in benchmark["contrast_groups"]} >= {
        "implicit_profile",
        "optional_preference",
        "current_override",
        "gift",
        "unrelated_history",
        "critical_compatibility",
    }


def test_independent_quality_labels_can_disagree_with_history_proxy(pens, natural_gold):
    from rs_core.offline.evaluation.skill_benchmark.dataset import fingerprint

    gold = copy.deepcopy(natural_gold)
    gold["relevance_judgments"] = {
        "origin": "human",
        "status": "approved",
        "reviewer_id": "test-reviewer",
        "rubric": "synthetic_test_only; not_real_customer_satisfaction",
        "catalog_sha256": fingerprint(pens),
        "grades": {"A": 2, "B": 3},
    }
    matching = evaluate_turn(pens, gold, suggestion("A"))
    alternative = evaluate_turn(pens, gold, suggestion("B"))
    assert matching["task_score"] == pytest.approx(200 / 3)
    assert alternative["task_score"] == 100
    assert matching["profile_evidence"]["score"] == pytest.approx(60)
    assert alternative["quality_basis"] == "independent_human_relevance"


def test_customer_environment_only_reveals_preference_reply_after_valid_question(
    pens, natural_gold
):
    from rs_core.offline.evaluation.skill_benchmark.environment import FixtureEnvironment

    first = copy.deepcopy(natural_gold)
    first["customer_policy"].update(
        action="recommend_or_clarify",
        clarification_need="optional",
        required_slots=["profile_preference"],
        clarification_field="tip_mm",
        max_questions=2,
    )
    following = copy.deepcopy(natural_gold)
    following["hard"].append({"field": "tip_mm", "op": "eq", "value": 0.5})
    turns = [
        {"user_message": "买支笔，20以内。", "limit": 1, "gold": first},
        {
            "user_message": "想要0.5mm。",
            "limit": 1,
            "gold": following,
            "continuation": "only_after_clarification",
        },
    ]
    with FixtureEnvironment(pens, {"customer_turns": turns}) as environment:
        environment.call("catalog_card", {"item_id": "A"})
        finished = environment.advance_customer(0, suggestion("A"))
        assert finished == {"done": True, "blocked": False}
    with FixtureEnvironment(pens, {"customer_turns": turns}) as environment:
        next_turn = environment.advance_customer(
            0,
            {
                "item_ids": [],
                "outcome": "clarify",
                "message": "笔尖想要粗一点还是细一点？",
            },
        )
        assert next_turn["next_turn"]["user_message"] == "想要0.5mm。"
        assert "gold" not in next_turn["next_turn"]
    with FixtureEnvironment(pens, {"customer_turns": turns}) as environment:
        blocked = environment.advance_customer(
            0,
            {
                "item_ids": [],
                "outcome": "clarify",
                "message": "你的手机号是多少？",
            },
        )
        assert blocked == {"done": True, "blocked": True}


def test_gift_question_can_target_recipient_preference_without_a_fixed_sentence(pens, natural_gold):
    gold = copy.deepcopy(natural_gold)
    gold["customer_policy"].pop("profile_match")
    gold["customer_policy"].pop("history_authorization")
    gold["customer_policy"].update(
        action="recommend_or_clarify",
        history_role="disabled",
        clarification_need="optional",
        required_slots=["recipient_need"],
        clarification_field="tip_mm",
        max_questions=2,
    )
    grade = evaluate_turn(
        pens,
        gold,
        {
            "item_ids": [],
            "outcome": "clarify",
            "message": "家人平时用笔喜欢细字还是粗字？",
        },
    )
    assert grade["success"]
    assert grade["asked_slots"] == ["recipient_need"]


@pytest.mark.parametrize(
    "message,violation",
    [
        ("你一直喜欢0.7mm，这支笔很适合你。", "overstated_history_preference"),
        ("你以前买过这种笔，我再推荐这支。", "review_history_presented_as_purchase"),
        ("这支笔售价3。", "unsupported_price_claim"),
        ("这支笔售价15元。", "unsupported_currency_claim"),
    ],
)
def test_explanation_cannot_turn_weak_history_or_catalog_gaps_into_facts(
    pens, natural_gold, message, violation
):
    grade = evaluate_turn(pens, natural_gold, suggestion("A", message=message))
    assert not grade["success"]
    assert violation in grade["violations"]
    assert grade["explanation"]["checked_claims"] > 0


def small_session(pens, natural_gold):
    from rs_core.offline.evaluation.skill_benchmark.dataset import fingerprint
    from rs_core.offline.evaluation.skill_benchmark.profile_matching import build_profile_match

    profile = {
        "profile_user_id": "u",
        "history_cutoff_exclusive": 5,
        "seen_item_ids": [f"old-{index}" for index in range(3)],
        "profile_preferences": {},
        "history": [
            {
                "user_id": "u",
                "timestamp": index,
                "parent_asin": f"old-{index}",
                "rating": 5,
                "item": {"category": "pens", "category_path": ["pens"], "tip_mm": 0.7},
            }
            for index in range(3)
        ],
    }
    first = copy.deepcopy(natural_gold)
    first["customer_policy"].update(
        action="recommend_or_clarify",
        clarification_need="optional",
        max_questions=2,
        required_slots=["profile_preference"],
        clarification_field="tip_mm",
        profile_match=build_profile_match(profile, "pens", ["pens"], "tip_mm"),
    )
    final = copy.deepcopy(natural_gold)
    final["customer_policy"].update(history_role="disabled")
    final["customer_policy"].pop("profile_match")
    final["customer_policy"].pop("history_authorization")
    final["hard"].append({"field": "tip_mm", "op": "eq", "value": 0.5})
    return {
        "schema_version": "rs-skill-benchmark/1",
        "catalog": pens,
        "profiles": {"u": profile},
        "manifest": {
            "catalog_sha256": fingerprint(pens),
            "profiles_sha256": fingerprint({"u": profile}),
            "human_reviewed": False,
            "independent_relevance_status": "pending_human_labels",
        },
        "environment": {},
        "tasks": [
            {
                "task_id": "optional",
                "family_id": "family",
                "profile_user_id": "u",
                "split": "dev",
                "kind": "optional",
                "review_status": "pending",
                "dialogue_policy": "conditional_customer/1",
                "environment": {"profile_access": {"allowed": True, "bound_profile_user_id": "u"}},
                "turns": [
                    {"user_message": "买支笔，20以内。", "limit": 1, "gold": first},
                    {
                        "user_message": "想要0.5mm。",
                        "limit": 1,
                        "gold": final,
                        "continuation": "only_after_clarification",
                    },
                ],
            }
        ],
    }


def http_agent(*, ask=False, direct_item="A"):
    import json
    from urllib.request import Request, urlopen

    def adapter(request):
        def post(path, payload):
            with urlopen(
                Request(
                    request["fixture_url"] + path,
                    data=json.dumps(payload).encode(),
                    headers={"Content-Type": "application/json"},
                ),
                timeout=5,
            ) as response:
                return json.load(response)

        assert len(request["turns"]) == 1
        assert "gold" not in request["turns"][0]
        turns = []
        post("/turn", {"turn_index": 0})
        if ask:
            answer = {"item_ids": [], "outcome": "clarify", "message": "笔尖想用什么粗细？"}
            turns.append(answer)
            next_turn = post("/customer", {"turn_index": 0, "answer": answer})
            assert next_turn["next_turn"]["user_message"] == "想要0.5mm。"
            post("/turn", {"turn_index": 1})
        post(
            "/tool",
            {"tool_name": "catalog_card", "arguments": {"item_id": "B" if ask else direct_item}},
        )
        answer = suggestion("B" if ask else direct_item)
        turns.append(answer)
        post("/customer", {"turn_index": len(turns) - 1, "answer": answer})
        return {"turns": turns}

    return adapter


def test_runner_counts_both_valid_optional_paths_as_completed(pens, natural_gold):
    from rs_core.offline.evaluation.skill_benchmark.runner import run_benchmark

    benchmark = small_session(pens, natural_gold)
    for ask, count in ((False, 1), (True, 2)):
        report = run_benchmark(benchmark, http_agent(ask=ask), {"model": "controlled-http"})
        assert report["summary"]["success_rate"] == 1
        assert report["trials"][0]["executed_turns"] == count
        assert report["summary"]["mean_ranking_score"] == 100
        assert report["summary"]["natural_metrics"]["required_clarification_turns"] == 0
        assert report["summary"]["natural_metrics"]["optional_clarification_turns"] == int(ask)


def test_hidden_profile_is_hidden_in_both_request_and_memory_tool(pens, natural_gold):
    import json
    from urllib.request import Request, urlopen
    from rs_core.offline.evaluation.skill_benchmark.runner import run_benchmark

    seen = []

    def adapter(request):
        assert request["profile_snapshot"] == {"profile_user_id": "u"}
        with urlopen(
            Request(
                request["fixture_url"] + "/tool",
                data=json.dumps(
                    {
                        "tool_name": "session_memory",
                        "arguments": {},
                    }
                ).encode(),
                headers={"Content-Type": "application/json"},
            ),
            timeout=5,
        ) as response:
            seen.append(json.load(response))
        return http_agent()(request)

    run_benchmark(
        small_session(pens, natural_gold),
        adapter,
        {"model": "controlled-http"},
        profile_visibility="hidden",
    )
    assert seen[0]["profile_history"] == []
    assert seen[0]["profile_preferences"] == {}
    assert seen[0]["profile_access"]["allowed"] is False


def test_profile_ablation_does_not_claim_gain_without_independent_labels(pens, natural_gold):
    from rs_core.offline.evaluation.skill_benchmark.runner import (
        run_benchmark,
        compare_profile_ablation,
    )

    benchmark = small_session(pens, natural_gold)
    hidden = run_benchmark(
        benchmark, http_agent(), {"model": "controlled-http"}, profile_visibility="hidden"
    )
    visible = run_benchmark(benchmark, http_agent(), {"model": "controlled-http"})
    comparison = compare_profile_ablation(hidden, visible)
    assert comparison["paired_trials"] == 1
    assert comparison["comparable_labeled_trials"] == 0
    assert comparison["personalization_quality_delta"] is None
    assert comparison["auto_deploy"] is False


def test_labeled_ablation_can_report_negative_gain_despite_matching_history(pens, natural_gold):
    from rs_core.offline.evaluation.skill_benchmark.dataset import fingerprint
    from rs_core.offline.evaluation.skill_benchmark.runner import (
        run_benchmark,
        compare_profile_ablation,
    )

    benchmark = small_session(pens, natural_gold)
    benchmark["tasks"][0]["turns"][0]["gold"]["relevance_judgments"] = {
        "origin": "human",
        "status": "approved",
        "reviewer_id": "unit-test-not-real-human",
        "rubric": "unit_test_only",
        "catalog_sha256": fingerprint(pens),
        "grades": {"A": 2, "B": 3},
    }
    hidden = run_benchmark(
        benchmark,
        http_agent(direct_item="B"),
        {"model": "controlled-http"},
        profile_visibility="hidden",
    )
    visible = run_benchmark(benchmark, http_agent(direct_item="A"), {"model": "controlled-http"})
    comparison = compare_profile_ablation(hidden, visible)
    assert visible["trials"][0]["profile_evidence_score"] == 60
    assert comparison["comparable_labeled_trials"] == 1
    assert comparison["personalization_quality_delta"] == pytest.approx(-100 / 3)


def test_natural_examples_show_separate_history_evidence_not_fake_satisfaction():
    from rs_core.offline.evaluation.skill_benchmark.dataset import load_benchmark
    from rs_core.offline.evaluation.skill_benchmark.natural_dataset import build_natural_benchmark
    from rs_core.offline.evaluation.skill_benchmark.natural_examples import build_natural_examples

    source = load_benchmark(
        Path(__file__).resolve().parents[1] / "benchmarks/skill_benchmark/v5/benchmark.json"
    )
    examples = build_natural_examples(build_natural_benchmark(source))
    assert examples["test_gold_not_exported"]
    assert len(examples["examples"]) == 3
    pens = examples["examples"][0]
    assert "买支" not in pens["members"][0]["customer_message"]
    assert pens["current_request_score_matrix"] == [[100, 100], [100, 100]]
    assert pens["history_evidence_score_matrix"][0] == [60, 0]
    assert pens["history_evidence_score_matrix"][1] == pytest.approx([0, 100 / 3])
    assert all(example["split"] != "test" for example in examples["examples"])


def test_relevance_review_pack_is_empty_human_work_not_automatically_generated_truth(
    pens, natural_gold
):
    from rs_core.offline.evaluation.skill_benchmark.relevance_review import (
        build_relevance_review,
        apply_relevance_review,
    )

    benchmark = small_session(pens, natural_gold)
    pack = build_relevance_review(benchmark)
    assert pack["entries"][0]["grades"] == {"A": None, "B": None}
    assert pack["entries"][0]["approved"] is False
    with pytest.raises(ValueError, match="批准"):
        apply_relevance_review(benchmark, pack)
    pack["entries"][0].update(
        approved=True,
        reviewer_id="unit-test-not-real-review",
        rubric="test_only",
        grades={"A": 2, "B": 3},
        reasons={"A": "test_only", "B": "test_only"},
    )
    labeled = apply_relevance_review(benchmark, pack)
    grade = evaluate_turn(pens, labeled["tasks"][0]["turns"][0]["gold"], suggestion("A"))
    assert grade["task_score"] == pytest.approx(200 / 3)
    assert labeled["manifest"]["human_reviewed"] is False


def test_successful_compatibility_guidance_is_not_zero_ranking_quality():
    from rs_core.offline.evaluation.skill_benchmark.profile_matching import contrast_metrics

    benchmark = {
        "tasks": [
            {"task_id": item, "turns": [{"gold": {"customer_policy": {"action": "defer"}}}]}
            for item in ("a", "b")
        ],
        "contrast_groups": [
            {
                "group_id": "g",
                "kind": "critical_compatibility",
                "split": "dev",
                "task_ids": ["a", "b"],
            }
        ],
    }
    trials = [
        {
            "task_id": item,
            "repeat": 0,
            "success": True,
            "ranking_score": None,
            "dialogue_complete": True,
        }
        for item in ("a", "b")
    ]
    report = contrast_metrics(benchmark, trials, split="dev", repeats=1)
    assert report["groups"][0]["paired_quality"] is None
    assert report["paired_success_rate"] == 1


def test_critical_compatibility_requires_question_even_with_repeated_history(pens, natural_gold):
    gold = copy.deepcopy(natural_gold)
    gold["customer_policy"].update(
        action="clarify",
        clarification_need="required",
        required_slots=["device"],
        max_questions=2,
        unverified_claims=["compatibility"],
    )
    premature = evaluate_turn(pens, gold, suggestion("A"))
    question = evaluate_turn(
        pens,
        gold,
        {
            "item_ids": [],
            "outcome": "clarify",
            "message": "手机是什么型号或接口呢？",
        },
    )
    assert not premature["success"] and question["success"]
    gold["customer_policy"].update(action="defer", clarification_need="verification_guidance")
    answer = {
        "item_ids": [],
        "outcome": "uncertain_match",
        "message": "暂时无法确认兼容性，请查看手机设置或说明书里的型号与接口。",
    }
    assert evaluate_turn(pens, gold, answer)["interaction_score"] == 100
    answer["message"] += "不过保证兼容。"
    false_claim = evaluate_turn(pens, gold, answer)
    assert not false_claim["success"]
    assert "unsupported_compatibility_claim" in false_claim["violations"]


def test_gift_explanation_cannot_apply_givers_history_to_recipient(pens, natural_gold):
    gold = copy.deepcopy(natural_gold)
    gold["customer_policy"].update(history_role="disabled")
    gold["customer_policy"].pop("profile_match")
    gold["customer_policy"].pop("history_authorization")
    grade = evaluate_turn(pens, gold, suggestion("A", message="按你的历史偏好给家人推荐这支笔。"))
    assert not grade["success"]
    assert "misapplied_profile_for_recipient" in grade["violations"]


@pytest.mark.parametrize("change", ["missing_item", "wrong_catalog", "model_origin"])
def test_independent_labels_cannot_hide_unjudged_items_or_wrong_sources(pens, natural_gold, change):
    from rs_core.offline.evaluation.skill_benchmark.dataset import fingerprint

    gold = copy.deepcopy(natural_gold)
    labels = {
        "origin": "human",
        "status": "approved",
        "reviewer_id": "test-only",
        "rubric": "test-only",
        "catalog_sha256": fingerprint(pens),
        "grades": {"A": 2, "B": 3},
    }
    if change == "missing_item":
        del labels["grades"]["B"]
    elif change == "wrong_catalog":
        labels["catalog_sha256"] = "other"
    else:
        labels["origin"] = "model"
    gold["relevance_judgments"] = labels
    with pytest.raises(ValueError):
        evaluate_turn(pens, gold, suggestion("A"))


@pytest.mark.parametrize("ask", [False, True])
def test_actual_java_loop_completes_both_natural_customer_paths(pens, natural_gold, ask):
    from rs_core.offline.evaluation.skill_benchmark.adapters import prepare_java_command
    from rs_core.offline.evaluation.skill_benchmark.runner import run_benchmark, SubprocessAgent

    java = os.environ.get("RS_BENCHMARK_TEST_JAVA")
    if not java:
        pytest.skip("需要显式指定 RS_BENCHMARK_TEST_JAVA，以运行真实 Java Loop 工程测试")
    root = Path(__file__).resolve().parents[2]
    requests = []

    class ControlledModel(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append(body)
            context = json.loads(body["messages"][0]["content"].rsplit("\n", 1)[-1])
            message = body["messages"][1]["content"]
            if ask and message == "买支笔，20以内。":
                name, arguments = (
                    "emit_final_answer",
                    {"blocks": [{"type": "followup_question", "content": "笔尖想用什么粗细？"}]},
                )
            elif not any(
                event["tool_name"] == "recommend_semantic_recall"
                for event in context.get("tool_results", [])
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
                    {"blocks": [{"type": "product_cards", "item_ids": ["B" if ask else "A"]}]},
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
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    server = ThreadingHTTPServer(("127.0.0.1", 0), ControlledModel)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        report = run_benchmark(
            small_session(pens, natural_gold),
            SubprocessAgent(prepare_java_command(root, java)),
            {
                "model": "controlled-external-model",
                "base_url": f"http://127.0.0.1:{server.server_port}/v1",
                "adapter_kind": "java_rs_agent_loop",
                "temperature": 0,
                "max_tokens": 256,
                "seed": 0,
            },
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
    assert report["summary"]["execution_failures"] == 0
    assert report["summary"]["success_rate"] == 1
    assert report["trials"][0]["executed_turns"] == (2 if ask else 1)
    assert "想要0.5mm。" not in json.dumps(requests[0], ensure_ascii=False)
