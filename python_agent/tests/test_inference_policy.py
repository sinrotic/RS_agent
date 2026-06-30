from __future__ import annotations

import importlib

import pytest

pytestmark = pytest.mark.unit

from rs_core.online.recall.candidate_merge import RecallCandidate, merge_candidates
from rs_core.online.ranking import rank_candidates
from rs_core.agent.inference import (
    InferencePolicyError,
    ModelOutputParseError,
    QWEN_POLICY_TYPE,
    RerankPolicyResult,
    RerankSignal,
    apply_optional_inference_policy,
    resolve_inference_policy_config,
)
from rs_core.agent.rollout import turn_to_rollout_record
from rs_core.agent.contracts.schema import AgentSession, AgentTurn, FeedbackConstraints
from rs_core.workflow.hybrid_demo import recommend_for_user


class FakeClient:
    def __init__(self, signals: list[RerankSignal], diagnostics: dict | None = None) -> None:
        self.signals = signals
        self.diagnostics = diagnostics or {}
        self.calls = []

    def rerank(self, **kwargs) -> RerankPolicyResult:
        self.calls.append(kwargs)
        return RerankPolicyResult(QWEN_POLICY_TYPE, self.signals, self.diagnostics)


class FailingClient:
    def rerank(self, **kwargs) -> RerankPolicyResult:
        raise InferencePolicyError("model failed")


class FakeOpenAIClient:
    def __init__(self, content: str) -> None:
        self.content = content
        self.calls: list[dict] = []

    def chat_completion(self, **kwargs) -> dict:
        self.calls.append(kwargs)
        return {
            "id": "chatcmpl-unit",
            "model": kwargs["model"],
            "choices": [{"message": {"content": self.content}, "finish_reason": "stop"}],
            "usage": {"total_tokens": 11},
        }


def test_disabled_inference_policy_leaves_candidates_unchanged():
    candidates = merge_candidates([RecallCandidate("a", "popular", 1.0)])

    updated, diagnostics = apply_optional_inference_policy(
        user_sequence={"user_id": "u1"},
        candidates=candidates,
        feedback_constraints=None,
        config={},
        client=FakeClient([RerankSignal("a", 1.0)]),
    )

    assert updated == candidates
    assert diagnostics["inference_policy"]["enabled"] is False
    assert diagnostics["inference_policy"]["policy_type"] == "deterministic_baseline"


def test_default_inference_policy_is_disabled_provider():
    policy = resolve_inference_policy_config({})

    assert policy["enabled"] is False
    assert policy["provider"] == "disabled"
    assert policy["available_providers"] == ["disabled", "openai_compatible", "local_transformers"]
    assert policy["model"]["local_files_only"] is True


def test_openai_compatible_env_policy_selects_provider(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("RS_AGENT_INFERENCE_POLICY", "openai_compatible")
    monkeypatch.setenv("RS_AGENT_OPENAI_COMPATIBLE_BASE_URL", "http://localhost:8000/v1")
    monkeypatch.setenv("RS_AGENT_OPENAI_COMPATIBLE_MODEL", "qwen-unit")

    policy = resolve_inference_policy_config({})

    assert policy["enabled"] is True
    assert policy["provider"] == "openai_compatible"
    assert policy["openai_compatible"]["base_url"] == "http://localhost:8000/v1"
    assert policy["openai_compatible"]["model"] == "qwen-unit"
    assert policy["model"]["model_id"] == "qwen-unit"


    policy = resolve_inference_policy_config(
        {
            "inference_policy": {
                "enabled": True,
                "provider": "openai_compatible",
                "openai_compatible": {
                    "api_base_env": "RS_AGENT_OPENAI_COMPATIBLE_BASE_URL",
                    "api_key_env": "RS_AGENT_OPENAI_COMPATIBLE_API_KEY",
                    "model_env": "RS_AGENT_OPENAI_COMPATIBLE_MODEL",
                },
            }
        }
    )

    assert policy["enabled"] is True
    assert policy["provider"] == "openai_compatible"
    assert policy["openai_compatible"]["api_key_env"] == "RS_AGENT_OPENAI_COMPATIBLE_API_KEY"
    assert policy["model"]["local_files_only"] is True


def test_openai_compatible_provider_without_endpoint_falls_back_without_local_model_load(monkeypatch: pytest.MonkeyPatch):
    candidates = merge_candidates([RecallCandidate("a", "popular", 1.0)])
    monkeypatch.delenv("RS_AGENT_OPENAI_COMPATIBLE_BASE_URL", raising=False)
    monkeypatch.delenv("RS_AGENT_OPENAI_COMPATIBLE_API_KEY", raising=False)

    updated, diagnostics = apply_optional_inference_policy(
        user_sequence={"user_id": "u1"},
        candidates=candidates,
        feedback_constraints=None,
        config={"inference_policy": {"enabled": True, "provider": "openai_compatible"}},
    )

    assert updated == candidates
    assert diagnostics["inference_policy"]["fallback_used"] is True
    assert diagnostics["inference_policy"]["fallback_reason"] == "InferencePolicyError"
    assert diagnostics["inference_policy"]["route"] == "openai_compatible"


def test_openai_compatible_adapter_success_parses_signal():
    from rs_core.agent.model_clients.openai_rerank_client import OpenAICompatibleRerankClient

    candidates = merge_candidates([RecallCandidate("a", "popular", 1.0, category="Audio")])
    client = OpenAICompatibleRerankClient(
        {
            "provider": "openai_compatible",
            "policy_type": QWEN_POLICY_TYPE,
            "model": {"model_id": "unit-model"},
            "openai_compatible": {"model": "unit-model", "max_tokens": 64, "temperature": 0.0},
        },
        client=FakeOpenAIClient('{"signals":[{"item_id":"a","delta":0.4,"confidence":0.5,"reason":"match","tags":["audio"]}],"policy_notes":"ok"}'),
    )

    result = client.rerank(user_sequence={"user_id": "u1"}, feedback_constraints=None, candidates=candidates, config={})

    assert result.signals == [RerankSignal("a", 0.4, confidence=0.5, reason="match", tags=["audio"])]
    assert result.diagnostics["provider"] == "openai_compatible"
    assert result.diagnostics["response_metadata"]["id"] == "chatcmpl-unit"


def test_openai_compatible_adapter_invalid_json_falls_back():
    from rs_core.agent.model_clients.openai_rerank_client import OpenAICompatibleRerankClient

    candidates = merge_candidates([RecallCandidate("a", "popular", 1.0)])
    client = OpenAICompatibleRerankClient(
        {"provider": "openai_compatible", "model": {"model_id": "unit-model"}, "openai_compatible": {"model": "unit-model"}},
        client=FakeOpenAIClient("not json"),
    )

    updated, diagnostics = apply_optional_inference_policy(
        user_sequence={"user_id": "u1"},
        candidates=candidates,
        feedback_constraints=None,
        config={"inference_policy": {"enabled": True, "provider": "openai_compatible"}},
        client=client,
    )

    assert updated == candidates
    assert diagnostics["inference_policy"]["fallback_used"] is True
    assert diagnostics["inference_policy"]["fallback_reason"] == "ModelOutputParseError"


def test_openai_compatible_adapter_invalid_json_raises_when_strict():
    from rs_core.agent.model_clients.openai_rerank_client import OpenAICompatibleRerankClient

    candidates = merge_candidates([RecallCandidate("a", "popular", 1.0)])
    client = OpenAICompatibleRerankClient(
        {"provider": "openai_compatible", "model": {"model_id": "unit-model"}, "openai_compatible": {"model": "unit-model"}},
        client=FakeOpenAIClient("not json"),
    )

    with pytest.raises(ModelOutputParseError):
        apply_optional_inference_policy(
            user_sequence={"user_id": "u1"},
            candidates=candidates,
            feedback_constraints=None,
            config={"inference_policy": {"enabled": True, "provider": "openai_compatible", "strict": True}},
            client=client,
        )


def test_local_transformers_provider_keeps_local_files_only_default():
    policy = resolve_inference_policy_config({"inference_policy": {"enabled": True, "provider": "local_transformers"}})

    assert policy["provider"] == "local_transformers"
    assert policy["model"]["model_id"] == "Qwen/Qwen3.5-4B"
    assert policy["model"]["local_files_only"] is True


def test_legacy_qwen_local_provider_aliases_to_local_transformers():
    policy = resolve_inference_policy_config({"inference_policy": {"enabled": True, "provider": "qwen_local"}})

    assert policy["provider"] == "local_transformers"


def test_fake_qwen_signal_adds_agent_boost_and_rerank_event():
    candidates = merge_candidates([RecallCandidate("speaker_1", "itemcf_weak", 2.0, category="Audio")])

    updated, diagnostics = apply_optional_inference_policy(
        user_sequence={"user_id": "u1"},
        candidates=candidates,
        feedback_constraints=FeedbackConstraints(preferred_keywords={"bluetooth": 1.0}),
        config={"inference_policy": {"enabled": True}},
        client=FakeClient([RerankSignal("speaker_1", 0.5, confidence=0.8, reason="matches audio", tags=["match"])]),
    )
    ranking = rank_candidates("u1", updated, {"top_k": 1, "rank_weights": {"itemcf_weak": 1.0, "feedback_model_rerank": 10.0}})

    assert diagnostics["inference_policy"]["accepted_signal_count"] == 1
    assert updated[0].source_scores["feedback_model_rerank"] == 0.4
    assert ranking.items[0]["base_score"] == 2.0
    assert ranking.items[0]["agent_boost"] == 4.0
    assert ranking.items[0]["final_score"] == 6.0
    assert ranking.items[0]["rerank_events"][0]["type"] == "qwen_rerank_signal"
    assert ranking.items[0]["rerank_events"][0]["reason"] == "matches audio"


def test_unknown_model_item_ids_are_rejected():
    candidates = merge_candidates([RecallCandidate("known", "popular", 1.0)])

    updated, diagnostics = apply_optional_inference_policy(
        user_sequence={"user_id": "u1"},
        candidates=candidates,
        feedback_constraints=None,
        config={"inference_policy": {"enabled": True}},
        client=FakeClient([RerankSignal("invented", 1.0)]),
    )

    assert updated[0].sources == ["popular"]
    assert diagnostics["inference_policy"]["accepted_signal_count"] == 0
    assert diagnostics["inference_policy"]["rejected_signal_count"] == 1
    assert diagnostics["inference_policy"]["rejected_signals"] == [{"item_id": "invented", "reason": "unknown_candidate_item_id"}]


def test_delta_and_confidence_are_clamped():
    candidates = merge_candidates([RecallCandidate("a", "popular", 1.0)])

    updated, diagnostics = apply_optional_inference_policy(
        user_sequence={"user_id": "u1"},
        candidates=candidates,
        feedback_constraints=None,
        config={"inference_policy": {"enabled": True, "signals": {"min_delta": -0.2, "max_delta": 0.2}}},
        client=FakeClient([RerankSignal("a", 5.0, confidence=2.0)]),
    )

    assert updated[0].source_scores["feedback_model_rerank"] == 0.2
    event = updated[0].metadata["model_rerank_events"][0]
    assert event["delta"] == 0.2
    assert event["confidence"] == 1.0
    assert event["applied_delta"] == 0.2
    assert diagnostics["inference_policy"]["accepted_signal_count"] == 1


def test_only_after_feedback_gate_skips_first_turn_without_calling_client():
    candidates = merge_candidates([RecallCandidate("a", "popular", 1.0)])
    client = FakeClient([RerankSignal("a", 1.0)])

    updated, diagnostics = apply_optional_inference_policy(
        user_sequence={"user_id": "u1"},
        candidates=candidates,
        feedback_constraints=None,
        config={"inference_policy": {"enabled": True, "trigger": {"only_after_feedback": True}}},
        client=client,
        turn_index=1,
    )

    assert updated == candidates
    assert client.calls == []
    assert diagnostics["inference_policy"] == {
        "enabled": True,
        "policy_type": QWEN_POLICY_TYPE,
        "route": "gated",
        "fallback_used": False,
        "accepted_signal_count": 0,
        "rejected_signal_count": 0,
        "gate_reason": "no_feedback",
        "model_id": "Qwen/Qwen3.5-4B",
    }


def test_only_after_feedback_allows_call_after_feedback():
    candidates = merge_candidates([RecallCandidate("a", "popular", 1.0)])
    client = FakeClient([RerankSignal("a", 0.2)])

    updated, diagnostics = apply_optional_inference_policy(
        user_sequence={"user_id": "u1"},
        candidates=candidates,
        feedback_constraints=FeedbackConstraints(preferred_keywords={"bluetooth": 1.0}),
        config={"inference_policy": {"enabled": True, "trigger": {"only_after_feedback": True}}},
        client=client,
        turn_index=2,
    )

    assert len(client.calls) == 1
    assert updated[0].source_scores["feedback_model_rerank"] == 0.2
    assert diagnostics["inference_policy"]["route"] == "local_transformers"
    assert diagnostics["inference_policy"]["accepted_signal_count"] == 1


def test_min_turn_index_gate_skips_early_turns():
    candidates = merge_candidates([RecallCandidate("a", "popular", 1.0)])
    client = FakeClient([RerankSignal("a", 1.0)])

    updated, diagnostics = apply_optional_inference_policy(
        user_sequence={"user_id": "u1"},
        candidates=candidates,
        feedback_constraints=FeedbackConstraints(preferred_keywords={"bluetooth": 1.0}),
        config={"inference_policy": {"enabled": True, "trigger": {"min_turn_index": 3}}},
        client=client,
        turn_index=2,
    )

    assert updated == candidates
    assert client.calls == []
    assert diagnostics["inference_policy"]["route"] == "gated"
    assert diagnostics["inference_policy"]["gate_reason"] == "min_turn_index"


def test_client_failure_falls_back_when_not_strict():
    candidates = merge_candidates([RecallCandidate("a", "popular", 1.0)])

    updated, diagnostics = apply_optional_inference_policy(
        user_sequence={"user_id": "u1"},
        candidates=candidates,
        feedback_constraints=None,
        config={"inference_policy": {"enabled": True, "strict": False}},
        client=FailingClient(),
    )

    assert updated == candidates
    assert diagnostics["inference_policy"]["fallback_used"] is True
    assert diagnostics["inference_policy"]["fallback_reason"] == "InferencePolicyError"


def test_client_failure_raises_when_strict():
    candidates = merge_candidates([RecallCandidate("a", "popular", 1.0)])

    try:
        apply_optional_inference_policy(
            user_sequence={"user_id": "u1"},
            candidates=candidates,
            feedback_constraints=None,
            config={"inference_policy": {"enabled": True, "strict": True}},
            client=FailingClient(),
        )
    except InferencePolicyError as exc:
        assert str(exc) == "model failed"
    else:
        raise AssertionError("strict inference failure should raise")


def test_qwen_client_import_does_not_require_model_dependencies():
    module = importlib.import_module("rs_core.agent.model_clients.qwen_client")

    assert hasattr(module, "QwenLocalClient")


def test_qwen_payload_rejects_non_numeric_signal_fields():
    module = importlib.import_module("rs_core.agent.model_clients.qwen_client")

    try:
        module._signals_from_payload({"signals": [{"item_id": "a", "delta": "bad"}]})
    except module.ModelOutputParseError as exc:
        assert "numeric" in str(exc)
    else:
        raise AssertionError("non-numeric model deltas should fail as parse errors")


def test_extract_json_skips_qwen_thinking_block():
    module = importlib.import_module("rs_core.agent.model_clients.qwen_client")

    parsed = module.extract_first_json_object('<think>{"ignored": true}</think>\n{"signals": [], "policy_notes": "ok"}')

    assert parsed == {"signals": [], "policy_notes": "ok"}


def test_extract_json_repairs_single_missing_signal_object_brace():
    module = importlib.import_module("rs_core.agent.model_clients.qwen_client")

    parsed = module.extract_first_json_object('{"signals":[{"item_id":"a","delta":0.3,"confidence":0.7,"reason":"match"],"policy_notes":"match"}\n')

    assert parsed == {"signals": [{"item_id": "a", "delta": 0.3, "confidence": 0.7, "reason": "match"}], "policy_notes": "match"}


def test_rerank_prompt_lists_real_candidate_ids_without_placeholder_schema():
    module = importlib.import_module("rs_core.agent.model_clients.qwen_client")

    prompt = module._format_rerank_prompt({"candidates": [{"item_id": "speaker_1"}, {"item_id": "earbuds_1"}]})

    assert 'speaker_1' in prompt
    assert 'earbuds_1' in prompt
    assert 'existing candidate item_id' not in prompt
    assert 'Payload JSON' not in prompt
    assert 'output_schema' not in prompt


def test_recommend_for_user_passes_turn_index_to_min_turn_gate():
    sequence = {"user_id": "u1", "recent_item_sequence": [], "recent_positive_item_sequence": ["seed"], "recent_strong_positive_item_sequence": []}
    client = FakeClient([RerankSignal("speaker_1", 0.3, confidence=1.0)])

    result = recommend_for_user(
        sequence,
        [],
        {"seed": [RecallCandidate("speaker_1", "itemcf_weak", 2.0, category="Audio")]},
        {},
        {},
        {"seed": "Audio"},
        {"top_k": 1, "inference_policy": {"enabled": True, "trigger": {"min_turn_index": 2}}},
        feedback_constraints=FeedbackConstraints(preferred_keywords={"bluetooth": 1.0}),
        inference_client=client,
        turn_index=1,
    )

    assert client.calls == []
    assert result.diagnostics["inference_policy"]["route"] == "gated"
    assert result.diagnostics["inference_policy"]["gate_reason"] == "min_turn_index"
    assert "skipped by the inference gate" in result.decision.agent_explanation
    assert "Qwen-generated bounded rerank signals" not in result.decision.agent_explanation
    assert result.decision.risk_flags == []


def test_recommend_for_user_records_qwen_policy_metadata_in_rollout():
    sequence = {"user_id": "u1", "recent_item_sequence": [], "recent_positive_item_sequence": ["seed"], "recent_strong_positive_item_sequence": []}
    result = recommend_for_user(
        sequence,
        [],
        {"seed": [RecallCandidate("speaker_1", "itemcf_weak", 2.0, category="Audio")]},
        {},
        {},
        {"seed": "Audio"},
        {"top_k": 1, "rank_weights": {"itemcf_weak": 1.0, "feedback_model_rerank": 10.0}, "inference_policy": {"enabled": True}},
        inference_client=FakeClient([RerankSignal("speaker_1", 0.3, confidence=1.0)]),
    )
    session = AgentSession(session_id="s1", user_id="u1")
    turn = AgentTurn(
        turn_index=1,
        user_input="",
        feedback_constraints=FeedbackConstraints(),
        recommendation=result.decision,
        candidates=[],
        ranking=result.ranking.items,
        fallback_used=result.fallback_used,
        diagnostics=result.diagnostics,
    )

    record = turn_to_rollout_record(turn, session, sequence)

    assert record["policy_type"] == QWEN_POLICY_TYPE
    assert record["metadata"]["inference_policy_enabled"] is True
    assert record["metadata"]["inference_policy_fallback_used"] is False
    assert record["agent_decision"]["risk_flags"] == []
    assert "Qwen-generated bounded rerank signals" in record["agent_decision"]["agent_explanation"]
