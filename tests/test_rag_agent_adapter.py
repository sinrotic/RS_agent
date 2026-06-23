from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit

from rs_core.agent_runtime.core import AgentRunRequest, AgentRunResult
from rs_core.agent_runtime.adapters.rag import (
    RAG_AGENT_POST_RANKING_STAGE,
    RAG_AGENT_PRE_RETRIEVAL_STAGE,
    RAG_AGENT_SYSTEM_PROMPT,
    RagAgentAdapter,
    RagAgentConfig,
    RagAgentInvocation,
    RagAgentMessageEnvelope,
    RagAgentResponse,
    RagQueryRewriteConfig,
    RagQueryRewriter,
)
from rs_core.common.openai_compatible_client import OpenAICompatibleClient
from rs_core.recsys.rag import RAG_PARENT_PROFILE_FIELD
from rs_core.recsys.types import AgentDecision
from rs_core.rsagent.schema import AgentTurn, FeedbackConstraints


def test_rag_agent_shadow_skips_without_rag_context() -> None:
    turn = _turn(rag_context=None)
    adapter = RagAgentAdapter(RagAgentConfig(enabled=True))

    report = adapter.attach_shadow_report(turn)

    assert report.status == "skipped"
    assert turn.diagnostics["rag_agent_shadow"]["action"] == "skip"
    assert "rag_agent_support" not in turn.diagnostics


def test_rag_agent_builds_compact_support_from_candidate_evidence_only() -> None:
    turn = _turn(
        rag_context={
            "query": "camp kettle",
            "candidate_item_ids": ["i1"],
            "evidence": [
                {"item_id": "i1", "field": "features", "text": "Lightweight titanium body for camping.", "metadata": {}},
                {"item_id": "outside", "field": "title", "text": "outside evidence", "metadata": {}},
            ],
            "metadata": {"retriever": "in_memory_candidate_card"},
        }
    )

    report = RagAgentAdapter(RagAgentConfig(enabled=True)).attach_shadow_report(turn)

    assert report.status == "ok"
    support = turn.diagnostics["rag_agent_support"]
    assert support["schema_version"] == "rag_agent_support_v1"
    assert support["candidate_scoped"] is True
    assert support["candidate_generation_allowed"] is False
    assert support["ranking_input_replacement_allowed"] is False
    assert support["promotion_allowed"] is False
    assert support["public_payload_allowed"] is False
    assert list(support["item_support"]) == ["i1"]
    assert support["item_support"]["i1"][0] == {
        "field": "features",
        "summary": "Lightweight titanium body for camping.",
        "evidence_hint": "candidate-scoped features",
    }
    assert "outside" not in str(support)


def test_rag_agent_compresses_parent_profile_without_raw_text_leakage() -> None:
    raw_parent_text = "Title: Titanium Kettle\nDescription: Very long raw parent profile that should not be copied verbatim."
    turn = _turn(
        rag_context={
            "query": "camp kettle",
            "candidate_item_ids": ["i1"],
            "evidence": [
                {
                    "item_id": "i1",
                    "field": RAG_PARENT_PROFILE_FIELD,
                    "text": raw_parent_text,
                    "metadata": {
                        "requires_parent_context_agent": True,
                        "direct_recommendation_input_allowed": False,
                        "parent_projection_fields": ["title", "description", "features"],
                    },
                }
            ],
        }
    )

    report = RagAgentAdapter(RagAgentConfig(enabled=True, max_text_chars=80)).attach_shadow_report(turn)

    assert report.used_parent_profile_count == 1
    support = turn.diagnostics["rag_agent_support"]
    parent_support = support["item_support"]["i1"][0]
    assert parent_support["field"] == RAG_PARENT_PROFILE_FIELD
    assert parent_support["summary"] == "商品级画像可用字段: title, description, features"
    assert parent_support["evidence_hint"] == "small2big parent profile compressed; raw text withheld"
    serialized = str(support)
    assert "Very long raw parent profile" not in serialized
    assert "direct_recommendation_input_allowed" not in serialized
    assert support["used_parent_profile_count"] == 1


def test_rag_agent_system_prompt_defines_standard_contract_sections() -> None:
    for section in (
        "Role_And_Duty",
        "Why_This_Matters",
        "Success_Standard",
        "Context_Use",
        "Subagent_Communication",
        "Evidence_Boundary",
        "Runtime_Boundary",
        "Response_Style",
        "Output_Format",
        "Good_Output_Example",
        "Bad_Output_Example",
    ):
        assert f"<{section}>" in RAG_AGENT_SYSTEM_PROMPT
        assert f"</{section}>" in RAG_AGENT_SYSTEM_PROMPT
    assert "RSAgent 内部调用" in RAG_AGENT_SYSTEM_PROMPT
    assert "call_rag_agent 子 Agent 工具" in RAG_AGENT_SYSTEM_PROMPT
    assert "pre_retrieval_query_support" in RAG_AGENT_SYSTEM_PROMPT
    assert "post_ranking_evidence_support" in RAG_AGENT_SYSTEM_PROMPT
    assert "不能新增商品" in RAG_AGENT_SYSTEM_PROMPT
    assert "raw text withheld" in RAG_AGENT_SYSTEM_PROMPT
    assert "中文或中英混合" in RAG_AGENT_SYSTEM_PROMPT
    assert "英文 normalized retrieval query" in RAG_AGENT_SYSTEM_PROMPT
    assert "public_payload_allowed=false" in RAG_AGENT_SYSTEM_PROMPT


def test_rag_agent_config_parses_string_false_as_disabled() -> None:
    config = RagAgentConfig.from_dict({"enabled": "false", "attach_support_to_diagnostics": "0"})

    assert config.enabled is False
    assert config.attach_support_to_diagnostics is False


def test_rag_query_rewrite_config_defaults_to_disabled() -> None:
    config = RagQueryRewriteConfig.from_dict({})

    assert config.enabled is False
    assert config.mode == "disabled"


def test_rag_query_rewriter_normalizes_chinese_query_with_mock_api(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RS_AGENT_TEST_KEY", "test-key")
    captured: dict[str, object] = {}

    def fake_transport(url: str, headers: dict[str, str], payload: dict[str, object], timeout_seconds: float) -> dict[str, object]:
        captured["payload"] = payload
        return {
            "id": "chatcmpl-test",
            "model": "test-model",
            "choices": [{"message": {"content": '{"query_rewrite":"portable commuter electronics accessories","semantic_query_hint":"portable commuter electronics accessories lightweight reliable","suggested_query_terms":["portable","commuter","electronics","accessories","lightweight","reliable"]}'}}],
        }

    client = OpenAICompatibleClient(base_url="https://example.test", api_key_env="RS_AGENT_TEST_KEY", transport=fake_transport)
    result = RagQueryRewriter(RagQueryRewriteConfig.from_dict({"enabled": True, "mode": "active", "model": "test-model"}), client=client).rewrite(
        "请比较两类通勤电子配件的区别"
    )

    assert result.valid is True
    assert result.query_rewrite == "portable commuter electronics accessories"
    assert result.semantic_query_hint == "portable commuter electronics accessories lightweight reliable"
    assert result.suggested_query_terms == ["portable", "commuter", "electronics", "accessories", "lightweight", "reliable"]
    assert result.diagnostics["status"] == "ok"
    assert captured["payload"]


def test_rag_query_rewriter_falls_back_on_invalid_json(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RS_AGENT_TEST_KEY", "test-key")

    def fake_transport(url: str, headers: dict[str, str], payload: dict[str, object], timeout_seconds: float) -> dict[str, object]:
        return {"choices": [{"message": {"content": "not json"}}]}

    client = OpenAICompatibleClient(base_url="https://example.test", api_key_env="RS_AGENT_TEST_KEY", transport=fake_transport)
    result = RagQueryRewriter(RagQueryRewriteConfig.from_dict({"enabled": True, "mode": "active", "model": "test-model"}), client=client).rewrite("通勤电子配件")

    assert result.valid is False
    assert result.diagnostics["status"] == "fallback"
    assert result.diagnostics["reason"] == "ValueError"


def test_rag_query_rewriter_rejects_internal_leakage(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RS_AGENT_TEST_KEY", "test-key")

    def fake_transport(url: str, headers: dict[str, str], payload: dict[str, object], timeout_seconds: float) -> dict[str, object]:
        return {"choices": [{"message": {"content": '{"query_rewrite":"sqlite_bm25 score source trace","suggested_query_terms":[]}'}}]}

    client = OpenAICompatibleClient(base_url="https://example.test", api_key_env="RS_AGENT_TEST_KEY", transport=fake_transport)
    result = RagQueryRewriter(RagQueryRewriteConfig.from_dict({"enabled": True, "mode": "active", "model": "test-model"}), client=client).rewrite("通勤电子配件")

    assert result.valid is False
    assert result.diagnostics["status"] == "fallback"
    assert "sqlite_bm25" not in str(result.diagnostics).lower()


def test_rag_agent_invocation_contract_round_trips_internal_envelope() -> None:
    invocation = RagAgentInvocation(
        description="query support",
        stage=RAG_AGENT_PRE_RETRIEVAL_STAGE,
        prompt_or_task="Support query planning.",
        session_id="s1",
        turn_index=1,
        request_id="req-1",
        payload={"query": "camp kettle"},
    )
    envelope = RagAgentMessageEnvelope(stage=invocation.stage, request_id=invocation.request_id, payload=invocation.payload)
    response = RagAgentResponse(status="skipped", stage=RAG_AGENT_PRE_RETRIEVAL_STAGE, request_id="req-1")

    assert invocation.to_dict()["agent_name"] == "rag_agent"
    assert invocation.to_dict()["visibility"] == "internal_only"
    assert envelope.to_dict()["receiver"] == "rag_agent"
    assert response.to_dict()["public_output"] == {}
    assert response.to_dict()["sft_output"] == {}


class FakeRagRunner:
    def __init__(self) -> None:
        self.requests: list[AgentRunRequest] = []

    def run(self, request: AgentRunRequest) -> AgentRunResult:
        self.requests.append(request)
        return AgentRunResult(
            agent_name=request.agent_name,
            status="ok",
            stage=request.stage,
            request_id=request.request_id,
            output={"rag_agent_response": RagAgentResponse(status="ok", stage=request.stage, request_id=request.request_id)},
            diagnostics={"status": "ok", "internal_only": True},
        )


def test_rag_agent_invoke_delegates_to_runner() -> None:
    runner = FakeRagRunner()
    response = RagAgentAdapter(runner=runner).invoke(RagAgentInvocation(
        stage=RAG_AGENT_PRE_RETRIEVAL_STAGE,
        request_id="req-runner",
        payload={"query": "camp kettle"},
    ))

    assert response.status == "ok"
    assert len(runner.requests) == 1
    request = runner.requests[0]
    assert request.agent_name == "rag_agent"
    assert request.stage == RAG_AGENT_PRE_RETRIEVAL_STAGE
    assert request.request_id == "req-runner"
    assert request.visibility == "internal_only"
    assert request.payload == {"query": "camp kettle"}


def test_rag_agent_pre_invocation_returns_internal_query_support() -> None:
    response = RagAgentAdapter().invoke(RagAgentInvocation(
        stage=RAG_AGENT_PRE_RETRIEVAL_STAGE,
        request_id="req-pre",
        payload={
            "query": "camp kettle",
            "evidence": [{"field": "features", "text": "ultralight titanium outdoor cooking"}],
            "applied": True,
            "reason": "test",
        },
    ))

    assert response.status == "ok"
    assert response.stage == RAG_AGENT_PRE_RETRIEVAL_STAGE
    assert response.query_support is not None
    assert response.query_support.schema_version == "rag_agent_query_support_v1"
    assert response.query_support.public_payload_allowed is False
    assert response.public_output == {}
    assert response.sft_output == {}


def test_rag_agent_post_invocation_returns_candidate_scoped_support() -> None:
    turn = _turn(rag_context={
        "query": "camp kettle",
        "candidate_item_ids": ["i1"],
        "evidence": [{"item_id": "i1", "field": "features", "text": "Lightweight titanium body for camping.", "metadata": {}}],
    })

    response = RagAgentAdapter(RagAgentConfig(enabled=True)).invoke(RagAgentInvocation(
        stage=RAG_AGENT_POST_RANKING_STAGE,
        request_id="req-post",
        payload={"turn": turn},
    ))

    assert response.status == "ok"
    assert response.shadow_report is not None
    assert response.support is not None
    assert response.support.schema_version == "rag_agent_support_v1"
    assert response.support.public_payload_allowed is False
    assert response.public_output == {}
    assert response.sft_output == {}


def test_rag_agent_runner_rejects_unknown_receiver_without_public_payload() -> None:
    response = RagAgentAdapter().handle_message(RagAgentMessageEnvelope(receiver="other_agent", stage=RAG_AGENT_PRE_RETRIEVAL_STAGE, request_id="req-other"))

    assert response.status == "error"
    assert response.stage == RAG_AGENT_PRE_RETRIEVAL_STAGE
    assert response.request_id == "req-other"
    assert response.diagnostics["reason"] == "agent_not_registered"
    assert response.diagnostics["internal_only"] is True
    assert response.public_output == {}
    assert response.sft_output == {}


def test_rag_agent_runner_rejects_unsupported_stage_without_public_payload() -> None:
    response = RagAgentAdapter().invoke(RagAgentInvocation(stage="unknown_stage", request_id="req-unknown"))

    assert response.status == "error"
    assert response.stage == "unknown_stage"
    assert response.request_id == "req-unknown"
    assert response.diagnostics["reason"] == "unsupported_stage"
    assert response.diagnostics["internal_only"] is True
    assert response.public_output == {}
    assert response.sft_output == {}


def test_rag_agent_builds_pre_retrieval_query_support() -> None:
    support = RagAgentAdapter().build_query_support(
        query="camp kettle",
        evidence=[{"field": "features", "text": "ultralight titanium outdoor cooking"}],
        applied=True,
        metadata={"retriever": "test"},
    ).to_dict()

    assert support["schema_version"] == "rag_agent_query_support_v1"
    assert support["call_stage"] == "pre_retrieval_query_support"
    assert support["semantic_query_hint"].startswith("camp kettle")
    assert support["suggested_query_terms"]
    assert support["retrieval_hints"]["candidate_generation_allowed"] is False
    assert support["retrieval_hints"]["ranking_input_replacement_allowed"] is False
    assert support["retrieval_hints"]["promotion_allowed"] is False
    assert support["retrieval_hints"]["public_payload_allowed"] is False
    assert support["public_payload_allowed"] is False
    assert support["diagnostics"]["internal_only"] is True


def test_rag_agent_query_support_accepts_explicit_bilingual_rewrite() -> None:
    support = RagAgentAdapter().build_query_support(
        query="请比较两类通勤电子配件的区别",
        query_rewrite="portable commuter electronics accessories comparison",
        semantic_query_hint="portable commuter electronics accessories lightweight reliable comparison",
        suggested_query_terms=["portable", "commuter", "electronics", "comparison"],
        evidence=[{"field": "features", "text": "portable lightweight reliable"}],
        applied=True,
        metadata={"query_rewrite": {"status": "ok", "mode": "active"}},
    ).to_dict()

    assert support["query"] == "请比较两类通勤电子配件的区别"
    assert support["query_rewrite"] == "portable commuter electronics accessories comparison"
    assert support["semantic_query_hint"] == "portable commuter electronics accessories lightweight reliable comparison"
    assert support["retrieval_hints"]["normalized_query"] == support["query_rewrite"]
    assert support["retrieval_hints"]["public_payload_allowed"] is False
    assert support["diagnostics"]["query_rewrite"]["status"] == "ok"


def test_rag_agent_query_support_skips_without_evidence() -> None:
    support = RagAgentAdapter().build_query_support(query="camp kettle", applied=False, reason="missing_query_or_index").to_dict()

    assert support["query"] == "camp kettle"
    assert support["semantic_query_hint"] == "camp kettle"
    assert support["suggested_query_terms"] == []
    assert support["retrieval_hints"]["applied"] is False
    assert support["diagnostics"]["status"] == "skipped"
    assert support["diagnostics"]["reason"] == "missing_query_or_index"


def test_rag_agent_config_normalizes_shadow_mode() -> None:
    config = RagAgentConfig.from_dict({"enabled": True, "mode": " Shadow "})

    assert config.mode == "shadow"


def test_rag_agent_config_rejects_unsupported_mode() -> None:
    with pytest.raises(ValueError, match="Unsupported RagAgent mode"):
        RagAgentConfig.from_dict({"enabled": True, "mode": "active"})


def test_rag_agent_truncates_summary_within_configured_max_chars() -> None:
    turn = _turn(
        rag_context={
            "query": "camp kettle",
            "candidate_item_ids": ["i1"],
            "evidence": [
                {"item_id": "i1", "field": "features", "text": "Lightweight titanium body for camping.", "metadata": {}},
            ],
        }
    )

    RagAgentAdapter(RagAgentConfig(enabled=True, max_text_chars=12)).attach_shadow_report(turn)

    summary = turn.diagnostics["rag_agent_support"]["item_support"]["i1"][0]["summary"]
    assert len(summary) <= 12
    assert summary.endswith("...")


def test_rag_agent_respects_explicit_rag_candidate_boundary() -> None:
    turn = _turn(
        rag_context={
            "query": "camp kettle",
            "candidate_item_ids": ["i1"],
            "evidence": [
                {"item_id": "i1", "field": "features", "text": "safe support", "metadata": {}},
                {"item_id": "i2", "field": "features", "text": "ranking-only evidence", "metadata": {}},
            ],
        }
    )
    turn.ranking.append({"parent_asin": "i2", "title": "Ranking only"})

    RagAgentAdapter(RagAgentConfig(enabled=True)).attach_shadow_report(turn)

    support = turn.diagnostics["rag_agent_support"]
    assert list(support["item_support"]) == ["i1"]
    assert "ranking-only evidence" not in str(support)


def test_rag_agent_redacts_internal_field_names_and_sensitive_text() -> None:
    turn = _turn(
        rag_context={
            "query": "camp kettle",
            "candidate_item_ids": ["i1"],
            "evidence": [
                {"item_id": "i1", "field": "score", "text": "source=/private/eval.json score=0.98", "metadata": {}},
            ],
        }
    )

    RagAgentAdapter(RagAgentConfig(enabled=True)).attach_shadow_report(turn)

    row = turn.diagnostics["rag_agent_support"]["item_support"]["i1"][0]
    assert row["field"] == "evidence"
    assert row["summary"] == "候选内商品证据已压缩，原始文本保留在内部 RAG 上下文。"
    assert "source=/private" not in str(turn.diagnostics["rag_agent_support"])
    assert "score=0.98" not in str(turn.diagnostics["rag_agent_support"])


def test_rag_agent_redacts_delimiter_free_sensitive_text() -> None:
    turn = _turn(
        rag_context={
            "query": "camp kettle",
            "candidate_item_ids": ["i1"],
            "evidence": [
                {"item_id": "i1", "field": "features", "text": "BM25 score 0.98 from source sqlite_bm25", "metadata": {}},
            ],
        }
    )

    RagAgentAdapter(RagAgentConfig(enabled=True)).attach_shadow_report(turn)

    support = turn.diagnostics["rag_agent_support"]
    row = support["item_support"]["i1"][0]
    assert row["field"] == "features"
    assert row["summary"] == "候选内商品证据已压缩，原始文本保留在内部 RAG 上下文。"
    assert "BM25 score" not in str(support)
    assert "sqlite_bm25" not in str(support)


def test_rag_agent_redacts_bare_retriever_identity_text() -> None:
    turn = _turn(
        rag_context={
            "query": "camp kettle",
            "candidate_item_ids": ["i1"],
            "evidence": [
                {"item_id": "i1", "field": "features", "text": "sqlite_bm25 retrieved this candidate via qdrant vector", "metadata": {}},
            ],
        }
    )

    RagAgentAdapter(RagAgentConfig(enabled=True)).attach_shadow_report(turn)

    support = turn.diagnostics["rag_agent_support"]
    assert support["item_support"]["i1"][0]["summary"] == "候选内商品证据已压缩，原始文本保留在内部 RAG 上下文。"
    for blocked in ("sqlite_bm25", "qdrant", "vector"):
        assert blocked not in str(support).lower()


def test_rag_agent_parent_profile_fallback_labels_are_allowlisted() -> None:
    turn = _turn(
        rag_context={
            "query": "camp kettle",
            "candidate_item_ids": ["i1"],
            "evidence": [
                {
                    "item_id": "i1",
                    "field": RAG_PARENT_PROFILE_FIELD,
                    "text": "Title: kettle\nSource: qdrant\nManifest: /private/manifest.json\nScore: 0.9",
                    "metadata": {"requires_parent_context_agent": True},
                },
            ],
        }
    )

    RagAgentAdapter(RagAgentConfig(enabled=True)).attach_shadow_report(turn)

    parent_support = turn.diagnostics["rag_agent_support"]["item_support"]["i1"][0]
    assert parent_support["summary"] == "商品级画像可用字段: title"
    assert "source" not in parent_support["summary"]
    assert "manifest" not in parent_support["summary"]
    assert "score" not in parent_support["summary"]


def test_rag_agent_loop_does_not_project_raw_rag_to_public_or_sft() -> None:
    turn = _turn(
        rag_context={
            "query": "camp kettle",
            "candidate_item_ids": ["i1"],
            "evidence": [{"item_id": "i1", "field": "description", "text": "safe support", "metadata": {}}],
        }
    )

    result = RagAgentAdapter(RagAgentConfig(enabled=True)).build_loop(turn).run(
        loop_input=_loop_input(turn),
    )

    assert result.public_output == {}
    assert result.sft_output == {}
    assert result.commit_intents[0].append_allowed is False
    assert "rag_agent_support" in result.internal_output
    assert "rag_context" not in str(result.public_output).lower()
    assert "raw_rag_evidence" not in str(result.internal_output).lower()


def _loop_input(turn: AgentTurn):
    from rs_core.agent_runtime.core import AgentLoopInput

    return AgentLoopInput(agent_name="rag_agent", user_input=turn.user_input, session_id="s1")


def _turn(rag_context: dict | None) -> AgentTurn:
    item = {"parent_asin": "i1", "title": "Titanium camp kettle"}
    return AgentTurn(
        turn_index=1,
        user_input="camp kettle",
        feedback_constraints=FeedbackConstraints(),
        recommendation=AgentDecision(
            user_id="u1",
            strategy_name="test",
            trigger_reason="test",
            agent_explanation="test",
            risk_flags=[],
            limitations=[],
            final_items=[dict(item)],
        ),
        candidates=[dict(item)],
        ranking=[dict(item)],
        fallback_used=False,
        diagnostics={},
        rag_context=rag_context,
    )
