import copy
import json
import os
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from rs_core.online_evaluation import OnlineEvaluation
from rs_core.online_evaluation.app import create_app
from rs_core.online_evaluation.bridge import improvement_jobs, reviewed_benchmarks
from rs_core.online_evaluation.requirements import RequirementExtractor
from rs_core.offline.evaluation.skill_benchmark.dataset import fingerprint, validate_benchmark
from rs_core.offline.evaluation.skill_benchmark.scoring import evaluate_turn
from rs_core.offline.evaluation.skill_benchmark.adapters import prepare_java_command
from rs_core.online_evaluation.adapters import HttpCatalog, JsonModel
from rs_core.common.openai_compatible_client import OpenAICompatibleClient

pytestmark = pytest.mark.serving


CATALOG = [{"item_id": "pen", "title": "Gel Pen 0.7mm", "category": "Gel Ink Rollerball Pens",
            "tip_mm": "0.7", "price": 30.0, "currency": "CNY"}]


def event(**updates):
    return {"session_id": "session-a", "turn_id": "turn-a", "profile_user_id": "profile-a",
            "customer_messages": ["想买笔，预算20元，帮我挑一款"],
            "assistant_message": "推荐这款笔", "item_ids": ["pen"], "observed_item_ids": ["pen"],
            "skill_version": "shopping-v1", "model_version": "test-model",
            "finish_reason": "FINAL_ANSWER", **updates}


def module(tmp_path, **kwargs):
    return OnlineEvaluation(tmp_path / "evaluation.db", salt="independent-test-salt-123",
                            catalog=lambda ids: copy.deepcopy(CATALOG), **kwargs)


def baseline():
    return {"schema_version": "rs-skill-benchmark/1", "catalog": copy.deepcopy(CATALOG),
            "environment": {"max_tool_calls_per_turn": 8},
            "manifest": {"catalog_sha256": fingerprint(CATALOG)},
            "tasks": [{"task_id": "base", "family_id": "base-family", "kind": "base", "split": "train",
                       "turns": [{"user_message": "买笔", "limit": 1,
                                  "gold": {"hard": [{"field": "price", "op": "lte", "value": 50}], "k": 1}}]}]}


def test_real_turn_is_enqueued_without_running_model_and_survives_restart(tmp_path):
    calls = []
    store = OnlineEvaluation(tmp_path / "evaluation.db", salt="independent-test-salt-123",
                             catalog=lambda ids: calls.append(ids) or copy.deepcopy(CATALOG))
    receipt = store.submit(event())
    assert calls == []
    restarted = module(tmp_path)
    report = restarted.process_one()
    assert report["turn_key"] == receipt["turn_key"]
    assert report["scores"]["constraint_score"] == 50
    assert report["checks"][0]["state"] == "fail"
    assert restarted.report(receipt["turn_key"])["status"] == "completed"


def test_idempotence_is_scoped_to_session_and_rejects_changed_payload(tmp_path):
    store = module(tmp_path)
    first = store.submit(event())
    assert store.submit(event())["duplicate"] is True
    assert store.submit(event(session_id="another"))["turn_key"] != first["turn_key"]
    with pytest.raises(ValueError, match="内容冲突"):
        store.submit(event(assistant_message="changed"))
    assert store.submit(event(session_id="a:b", turn_id="c"))["turn_key"] != store.submit(
        event(session_id="a", turn_id="b:c"))["turn_key"]


def test_missing_currency_is_unknown_not_budget_failure_or_full_score(tmp_path):
    store = module(tmp_path)
    store.submit(event(customer_messages=["预算20以内，推荐一款笔"]))
    report = store.process_one()
    assert report["scores"]["constraint_score"] is None
    assert report["scores"]["constraint_coverage"] == 0
    assert report["failures"] == []
    assert report["scores"]["satisfaction"] is None


def test_fallback_does_not_turn_minimum_budget_or_commute_into_hard_requirement():
    draft = RequirementExtractor().extract(["预算20以上，通勤用"])
    assert draft["hard"] == []
    assert draft["qualitative"]
    assert draft["coverage"] == "budget_tip_quantity_only"


def test_latest_customer_budget_replaces_old_budget_and_currency():
    draft = RequirementExtractor().extract(["预算20元", "改成预算30美元"])
    assert {(row["field"], row["value"]) for row in draft["hard"]} == {("price", 30), ("currency", "USD")}


@pytest.mark.parametrize("text", ["预算20元以上", "预算20左右", "预算2万"])
def test_fallback_does_not_misread_units_or_soft_budget(text):
    assert RequirementExtractor().extract([text])["hard"] == []


def test_removed_budget_and_non_pen_dimensions_are_not_stale_hard_requirements():
    draft = RequirementExtractor().extract(["预算20元", "预算不限，机箱宽度10.5mm"])
    assert draft["hard"] == []
    draft = RequirementExtractor().extract(["中性笔不要0.5毫米"])
    assert draft["hard"][0]["op"] == "not_in"
    assert draft["hard"][0]["value"] == ["0.5"]


def test_extractor_cannot_see_recommendations_profile_or_agent_interpretation(tmp_path):
    seen = []
    def model(instruction, payload):
        seen.append(payload)
        return {"hard": [], "soft": [], "qualitative": [], "missing": [], "quantity": None}
    store = module(tmp_path, extractor=RequirementExtractor(model))
    store.submit(event(assistant_message="用户其实预算100"))
    store.process_one()
    assert seen == [{"customer_messages": ["想买笔，预算20元，帮我挑一款"]}]


def test_fabricated_requirement_quote_is_evaluation_error_not_customer_failure(tmp_path):
    def model(instruction, payload):
        return {"hard": [{"field": "price", "op": "lte", "value": 1,
                          "message_index": 0, "quote": "不存在的顾客原话", "confidence": 1}]}
    store = module(tmp_path, extractor=RequirementExtractor(model))
    receipt = store.submit(event())
    result = store.process_one()
    assert result["scores"] is None
    assert result["evaluation_error"] == "ValueError"
    assert store.report(receipt["turn_key"])["status"] == "pending"
    assert store.candidates() == []


def test_unknown_catalog_item_is_not_claimed_nonexistent(tmp_path):
    store = OnlineEvaluation(tmp_path / "evaluation.db", salt="independent-test-salt-123", catalog=lambda ids: [])
    store.submit(event())
    result = store.process_one()
    assert result["scores"]["constraint_score"] is None
    assert all(row["state"] == "unknown" for row in result["checks"])
    assert result["failures"] == []


def test_catalog_errors_retry_durably_then_require_explicit_operator_retry(tmp_path):
    clock = [1000.0]
    def unavailable(ids):
        raise RuntimeError("Bearer secret must not be persisted")
    store = OnlineEvaluation(tmp_path / "evaluation.db", salt="independent-test-salt-123",
                             catalog=unavailable, clock=lambda: clock[0])
    receipt = store.submit(event())
    for expected in ("pending", "pending", "failed"):
        assert store.process_one()["status"] == expected
        clock[0] += 31
    assert store.process_one() is None
    assert "secret" not in json.dumps(store.report(receipt["turn_key"]))
    assert store.retry_failed(receipt["turn_key"])["status"] == "pending"
    restarted = module(tmp_path)
    assert restarted.process_one()["scores"]["hard_gate"] == "failed"
    with pytest.raises(ValueError):
        restarted.retry_failed(receipt["turn_key"])


def test_two_workers_cannot_grade_the_same_active_lease(tmp_path):
    entered, release = threading.Event(), threading.Event()
    def catalog(ids):
        entered.set()
        assert release.wait(5)
        return copy.deepcopy(CATALOG)
    store = OnlineEvaluation(tmp_path / "evaluation.db", salt="independent-test-salt-123", catalog=catalog)
    store.submit(event())
    thread = threading.Thread(target=store.process_one)
    thread.start()
    try:
        assert entered.wait(5)
        assert module(tmp_path).process_one() is None
    finally:
        release.set()
        thread.join(timeout=5)


def test_cross_profile_snapshot_is_rejected_and_authorized_snapshot_is_minimized(tmp_path):
    store = module(tmp_path)
    snapshot = {"source": "bound_profile_store", "allowed": True,
                "bound_profile_user_id": "another", "preferences": {"tip_mm": "0.7"}}
    with pytest.raises(ValueError):
        store.submit(event(profile_snapshot=snapshot))
    snapshot["bound_profile_user_id"] = "profile-a"
    store.submit(event(profile_snapshot=snapshot))
    store.process_one()
    encoded = json.dumps(store.review_pack())
    assert "bound_profile_user_id" not in encoded


def test_judge_scores_are_evidence_bound_and_profile_without_snapshot_is_unknown(tmp_path):
    def judge(instruction, payload):
        return {"dimensions": {name: {"grade": 2, "reason": "有文字依据",
               "evidence": [{"source": "assistant", "quote": "推荐这款笔"}]}
               for name in ("need_understanding", "clarification", "grounding", "profile_use")}}
    store = module(tmp_path, judge=judge)
    store.submit(event())
    result = store.process_one()
    assert result["judge"]["dimensions"]["profile_use"]["score"] is None
    assert result["judge"]["status"] == "uncalibrated_proxy"
    assert result["scores"]["constraint_score"] == 50
    assert any(row["code"] == "hard_constraint_failed" for row in result["failures"])


def test_judge_cannot_award_scores_with_fabricated_evidence(tmp_path):
    def judge(instruction, payload):
        return {"dimensions": {name: {"grade": 2, "reason": "test",
               "evidence": [{"source": "assistant", "quote": "绝不存在"}]}
               for name in ("need_understanding", "clarification", "grounding", "profile_use")}}
    store = module(tmp_path, judge=judge)
    store.submit(event())
    assert store.process_one()["scores"] is None


def test_three_distinct_sessions_and_two_profiles_trigger_isolated_candidate_not_release(tmp_path):
    store = module(tmp_path)
    for i in range(3):
        store.submit(event(session_id=f"session-{i}", profile_user_id=f"profile-{i}"))
        store.process_one()
    candidates = store.candidates()
    assert len(candidates) == 1
    assert candidates[0]["failure_code"] == "hard_constraint_failed"
    assert candidates[0]["field"] == "price"
    assert candidates[0]["independent_sessions"] == 3
    assert candidates[0]["auto_deploy"] is False
    jobs = improvement_jobs(candidates, baseline())
    assert jobs["jobs"][0]["candidate_skill_overlay"]["activation"] == "offline_only"


def test_different_model_versions_do_not_accumulate_toward_one_skill_candidate(tmp_path):
    store = module(tmp_path)
    for i in range(3):
        store.submit(event(session_id=f"session-{i}", profile_user_id=f"profile-{i}", model_version=f"model-{i}"))
        store.process_one()
    assert store.candidates() == []


def test_attribution_distinguishes_known_alternative_from_retrieval_uncertainty(tmp_path):
    catalog = CATALOG + [{**CATALOG[0], "item_id": "cheap", "price": 10.0}]
    store = OnlineEvaluation(tmp_path / "evaluation.db", salt="independent-test-salt-123",
                             catalog=lambda ids: catalog)
    store.submit(event(observed_item_ids=["pen", "cheap"]))
    report = store.process_one()
    assert report["attribution"][0]["known_feasible_observed_items"] == ["cheap"]
    assert report["attribution"][0]["hypothesis"] == "selection_or_ranking"
    assert report["attribution"][0]["skill_causality"] == "not_established"


@pytest.mark.parametrize("updates", [
    {"profile_user_id": "same-profile"},
    {"skill_version": "unknown"},
    {"context_truncated": True},
    {"finish_reason": "MODEL_ERROR"},
    {"tool_statuses": [{"tool_name": "recommend_candidates", "status": "TIMEOUT"}]},
    {"degradation_reasons": ["recommendation_unavailable"]},
])
def test_confounded_or_single_profile_failures_do_not_trigger_global_skill(tmp_path, updates):
    store = module(tmp_path)
    for i in range(3):
        store.submit(event(session_id=f"session-{i}", profile_user_id=f"profile-{i}", **{
            key: value for key, value in updates.items() if key != "profile_user_id"
        }) | ({"profile_user_id": updates["profile_user_id"]} if "profile_user_id" in updates else {}))
        store.process_one()
    assert store.candidates() == []


def test_feedback_is_delivery_bound_immutable_and_not_satisfaction(tmp_path):
    store = module(tmp_path)
    receipt = store.submit(event())
    feedback = {"event_id": "feedback-1", "type": "click", "item_id": "pen"}
    assert store.feedback(receipt["turn_key"], feedback)["duplicate"] is False
    assert store.feedback(receipt["turn_key"], feedback)["duplicate"] is True
    assert store.report(receipt["turn_key"])["feedback"][0]["satisfaction"] is None
    with pytest.raises(ValueError):
        store.feedback(receipt["turn_key"], feedback | {"type": "like"})
    with pytest.raises(ValueError):
        store.feedback(receipt["turn_key"], feedback | {"event_id": "new", "item_id": "not-delivered"})


def test_event_is_minimized_and_identity_and_basic_pii_are_redacted(tmp_path):
    store = module(tmp_path)
    store.submit(event(customer_messages=["联系 me@example.com 13812345678 Bearer abcdef"] ,
                       context={"secret": "must-not-be-stored"}))
    store.process_one()
    encoded = json.dumps(store.review_pack(), ensure_ascii=False)
    for value in ("me@example.com", "13812345678", "abcdef", "must-not-be-stored", "profile-a", "session-a"):
        assert value not in encoded


def test_authenticated_ingest_only_enqueues_and_invalid_or_oversize_events_are_rejected(tmp_path):
    store = module(tmp_path)
    client = TestClient(create_app(store, token="evaluation-test-token"))
    assert client.post("/internal/evaluation/turns", json=event()).status_code == 401
    headers = {"Authorization": "Bearer evaluation-test-token"}
    response = client.post("/internal/evaluation/turns", json=event(), headers=headers)
    assert response.status_code == 202
    key = response.json()["turn_key"]
    assert client.get(f"/internal/evaluation/turns/{key}", headers=headers).json()["status"] == "pending"
    assert client.post("/internal/evaluation/turns", json={}, headers=headers).status_code == 422
    assert client.post("/internal/evaluation/turns", content=b"x" * 120001, headers=headers).status_code == 413
    status = client.get("/internal/evaluation/status", headers=headers).json()
    assert status["turn_counts"] == {"pending": 1}
    assert status["extraction_mode"] == "limited_rules"


def test_model_proposals_cannot_be_exported_as_gold_and_frozen_baseline_is_unchanged(tmp_path):
    store = module(tmp_path)
    store.submit(event())
    store.process_one()
    pack, base = store.review_pack(), baseline()
    original = fingerprint(base)
    with pytest.raises(ValueError, match="没有已审核"):
        reviewed_benchmarks(pack, base)
    review = pack["examples"][0]["review"]
    review.update(approved=True, reviewer_id="human", export_permission=True)
    with pytest.raises(ValueError, match="填写 gold"):
        reviewed_benchmarks(pack, base)
    review["gold"] = {"k": 1, "hard": [{"field": "price", "op": "lte", "value": 50}]}
    dataset = reviewed_benchmarks(pack, base)[0]
    assert validate_benchmark(dataset)["task_count"] == 1
    assert fingerprint(base) == original
    assert dataset["manifest"]["scoring_calibration_required"] is True
    assert evaluate_turn(dataset["catalog"], review["gold"],
                         {"item_ids": ["pen"], "outcome": "recommend"})["task_score"] == 100


def test_online_cases_of_same_profile_cannot_cross_splits(tmp_path):
    store = module(tmp_path)
    for i in range(2):
        store.submit(event(session_id=f"s-{i}"))
        store.process_one()
    pack = store.review_pack()
    for i, case in enumerate(pack["examples"]):
        case["review"].update(approved=True, export_permission=True, reviewer_id="human",
                              split="train" if i == 0 else "test",
                              gold={"k": 1, "hard": [{"field": "price", "op": "lte", "value": 50}]})
    with pytest.raises(ValueError, match="跨 split"):
        reviewed_benchmarks(pack, baseline())


def test_real_java_turn_to_python_queue_independent_http_extraction_catalog_and_candidate(tmp_path, monkeypatch):
    java = os.environ.get("RS_BENCHMARK_TEST_JAVA")
    if not java:
        pytest.skip("需要构建 Java Agent 并配置 RS_BENCHMARK_TEST_JAVA")
    root = Path(__file__).resolve().parents[2]
    command = prepare_java_command(root, java)
    command[-1] = "com.sinrotic.rs.agent.benchmark.OnlineEvaluationMain"
    monkeypatch.setenv("RS_EVAL_MODEL_API_KEY", "fixture-key-not-production")
    requests = []
    context = {}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            if self.path == "/internal/evaluation/turns":
                response = context["client"].post(self.path, json=payload, headers={
                    "Authorization": self.headers.get("Authorization", "")})
                status, result = response.status_code, response.json()
            elif self.path == "/internal/catalog/context/item-embedding-texts":
                requests.append(("catalog", payload))
                status, result = 200, copy.deepcopy(CATALOG)
            elif self.path == "/v1/chat/completions":
                content = json.loads(payload["messages"][1]["content"])
                if "需求分析员" in payload["messages"][0]["content"]:
                    requests.append(("extract", content))
                    result = {"hard": [
                        {"field": "price", "op": "lte", "value": 20, "message_index": 0,
                         "quote": "预算20元", "confidence": .95},
                        {"field": "currency", "op": "eq", "value": "CNY", "message_index": 0,
                         "quote": "预算20元", "confidence": .95}], "quantity": None}
                else:
                    requests.append(("judge", content))
                    result = {"dimensions": {name: {"grade": None, "reason": "没有独立体验标签", "evidence": []}
                              for name in ("need_understanding", "clarification", "grounding", "profile_use")}}
                status, result = 200, {"choices": [{"message": {"content": json.dumps(result, ensure_ascii=False)}}]}
            else:
                status, result = 404, {}
            data = json.dumps(result, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}"
    model = JsonModel(OpenAICompatibleClient(base_url=url, api_key_env="RS_EVAL_MODEL_API_KEY",
                     allow_insecure_local_api_base=True, timeout_seconds=5), "controlled-independent-evaluator")
    store = OnlineEvaluation(tmp_path / "integration.db", salt="independent-test-salt-123",
                             catalog=HttpCatalog(url, currency="CNY"),
                             extractor=RequirementExtractor(model), judge=model)
    context["client"] = TestClient(create_app(store, token="test-token"))
    try:
        completed = subprocess.run(command, input=json.dumps({"base_url": url, "outbox": str(tmp_path / "outbox")}),
                                   text=True, capture_output=True, encoding="utf-8", timeout=20)
        assert completed.returncode == 0, completed.stderr[-2000:]
        # 在线请求只入队；推荐阶段不会触发评审模型。
        assert requests == []
        reports = [store.process_one() for _ in range(3)]
        assert all(report["scores"]["hard_gate"] == "failed" for report in reports)
        assert all(report["requirements"]["origin"] == "independent_model" for report in reports)
        extracts = [payload for kind, payload in requests if kind == "extract"]
        assert len(extracts) == 3
        assert all(set(payload) == {"customer_messages"} for payload in extracts)
        assert len([payload for kind, payload in requests if kind == "catalog"]) == 3
        assert len(store.candidates()) == 1
        assert store.candidates()[0]["auto_deploy"] is False
    finally:
        context["client"].close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
