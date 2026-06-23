from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest

pytestmark = pytest.mark.unit

from rs_core.common.openai_compatible_client import OpenAICompatibleClient
from rs_core.simulation.policy import RolePolicy
from rs_core.simulation.schema import RoleAction, RoleState, SimulatedCustomerRole
from scripts.training.judge_sft_samples import _safe_project_path
from rs_core.training.multi_turn_sft_generator import (
    MULTI_TURN_RUN_SCHEMA_VERSION,
    OpenAICompletionAdapter,
    RecommendationAgentComposer,
    _compose_grounded_response,
    _flatten_turn_samples,
    _manifest,
    _role_action_from_payload,
    _run_one_scene,
    _sanitize_dialogue_only_assistant_message,
    _simulated_user_messages,
    _terminal_turn_record,
    _turn_record,
    run_multi_turn_sft_generation,
    validate_multi_turn_sft_sample,
)
from rs_core.training.sft_judge import SFT_JUDGE_SCHEMA_VERSION, judge_sft_sample, judge_sft_samples


def test_multi_turn_sft_dry_run_generates_scene_without_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RS_agent", raising=False)

    result = run_multi_turn_sft_generation("configs/training/multi_turn_sft_gpt53.yaml", limit=2)

    assert result["dry_run"] is True
    assert result["api_called"] is False
    assert result["generated_count"] == 2
    assert result["model"]["model"] == "gpt-5.3-codex-spark"
    assert result["model"]["api_key_env"] == "RS_agent"
    assert result["quality_summary"]["min_dialogue_turn_count"] >= 2
    assert result["first_sample_preview"]["dialogue_turn_count"] >= 2
    first_turn = result["first_sample_preview"]["first_turn"]
    assert "Prefer categories" not in first_turn["user_message"]
    assert "parent_asin" not in first_turn["user_message"]
    assert "not sure" in first_turn["user_message"].lower() or "looking for" in first_turn["user_message"].lower()
    assert "simulator_private_context" in result["first_sample_preview"]
    assert result["first_sample_preview"]["simulator_private_context"]["past_interactions_summary"]
    assert "tool_supervision" in first_turn
    assert {"conversation_intent", "agent_action", "should_recommend", "expected_tool_calls", "agent_tool_events", "tool_call_summary"} <= set(first_turn["tool_supervision"])


def test_validate_multi_turn_sft_rejects_unknown_selected_item() -> None:
    sample = {
        "schema_version": "rs_agent_multi_turn_sft_sample_v1",
        "sample_id": "sample-1",
        "dialogue": [
            {
                "turn_index": 1,
                "user_message": "show me audio",
                "assistant_message": "try item a",
                "display_item_ids": ["a"],
                "selected_item_ids": ["missing"],
                "target_action": {"allowed_item_ids": ["a"], "selected_item_ids": ["missing"], "must_select_from_candidates": True},
            },
            {
                "turn_index": 2,
                "user_message": "why?",
                "assistant_message": "because it matches",
                "display_item_ids": ["a"],
                "selected_item_ids": [],
                "target_action": {"allowed_item_ids": ["a"], "selected_item_ids": [], "must_select_from_candidates": True},
            },
        ],
        "grounding": {"forbidden_eval_fields_present": False},
    }

    with pytest.raises(ValueError, match="selected_item_ids"):
        validate_multi_turn_sft_sample(sample)


def test_validate_multi_turn_sft_rejects_accept_without_selected_item() -> None:
    sample = {
        "schema_version": "rs_agent_multi_turn_sft_sample_v1",
        "sample_id": "sample-accept-empty",
        "dialogue": [
            {
                "turn_index": 1,
                "user_message": "show me audio",
                "assistant_message": "try item a",
                "display_item_ids": ["a"],
                "selected_item_ids": [],
                "target_action": {"allowed_item_ids": ["a"], "selected_item_ids": [], "must_select_from_candidates": True},
            },
            {
                "turn_index": 2,
                "user_message": "I will take it",
                "assistant_message": "用户接受了当前推荐。",
                "action_type": "accept",
                "display_item_ids": ["a"],
                "selected_item_ids": [],
                "target_action": {
                    "strategy_name": "accept_displayed_item",
                    "allowed_item_ids": ["a"],
                    "selected_item_ids": [],
                    "must_select_from_candidates": True,
                },
            },
        ],
        "grounding": {"forbidden_eval_fields_present": False},
    }

    with pytest.raises(ValueError, match="accept.*selected_item_ids"):
        validate_multi_turn_sft_sample(sample)


def test_terminal_accept_supervision_uses_real_diagnostics() -> None:
    record = _terminal_turn_record(
        2,
        RoleAction.accept("a", "I will take this."),
        {"items": [{"parent_asin": "a", "title": "Shown item"}]},
        "用户接受了当前推荐。",
        diagnostics={
            "conversation_intent": "preference_feedback",
            "agent_action": "record_acceptance",
            "should_recommend": False,
            "agent_tool_events": [{"tool_name": "record_user_feedback", "phase": "post_recommendation", "status": "ok"}],
            "agent_tool_summary": {"event_count": 1, "executed_count": 1, "skipped_count": 0, "error_count": 0},
        },
    )

    supervision = record["tool_supervision"]
    assert record["selected_item_ids"] == ["a"]
    assert supervision["expected_tool_calls"] == ["record_user_feedback"]
    assert supervision["tool_call_summary"]["executed_count"] == 1


def test_terminal_accept_supervision_does_not_fabricate_tool_success() -> None:
    record = _terminal_turn_record(
        2,
        RoleAction.accept("a", "I will take this."),
        {"items": [{"parent_asin": "a", "title": "Shown item"}]},
        "用户接受了当前推荐。",
        diagnostics={},
    )

    supervision = record["tool_supervision"]
    assert supervision["expected_tool_calls"] == []
    assert supervision["agent_tool_events"] == []
    assert supervision["tool_call_summary"]["executed_count"] == 0


def test_role_action_from_payload_requires_accept_item_id_when_display_has_items() -> None:
    with pytest.raises(ValueError, match="accept action requires item_id"):
        _role_action_from_payload(
            {"action_type": "accept", "comment": "Looks good."},
            {"items": [{"parent_asin": "a", "title": "Shown item"}]},
        )


def test_judge_sft_samples_safe_project_path_rejects_absolute_and_escape(tmp_path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()

    assert _safe_project_path("outputs/judge.jsonl", root=project_root) == (project_root / "outputs/judge.jsonl").resolve()
    with pytest.raises(ValueError, match="absolute paths are not allowed"):
        _safe_project_path(str(tmp_path / "outside.jsonl"), root=project_root)
    with pytest.raises(ValueError, match="path escapes project root"):
        _safe_project_path("../outside.jsonl", root=project_root)


def test_multi_turn_sft_dry_run_override_prevents_writes(tmp_path) -> None:
    output_path = tmp_path / "samples.jsonl"
    flat_path = tmp_path / "flat.jsonl"
    manifest_path = tmp_path / "manifest.json"
    rejects_path = tmp_path / "rejects.jsonl"
    config_path = tmp_path / "config.yaml"
    output_value = output_path.as_posix()
    flat_value = flat_path.as_posix()
    manifest_value = manifest_path.as_posix()
    rejects_value = rejects_path.as_posix()
    config_path.write_text(
        f"""
generation:
  enabled: true
  dry_run: false
  target_samples: 1
  seed: 20260621
  service_config: configs/demo/hybrid_demo/hybrid_demo_electronics_10000_lopo_semantic_title.yaml
  min_turns_per_scene: 2
  max_turns_per_scene: 2
  output_path: {output_value}
  flat_output_path: {flat_value}
  manifest_path: {manifest_value}
  rejects_path: {rejects_value}
model:
  api_base: https://cpa2api.sinrotic233.com
  api_key_env: RS_agent
  model: gpt-5.3-codex-spark
""".strip(),
        encoding="utf-8",
    )

    result = run_multi_turn_sft_generation(config_path, limit=1, dry_run_override=True)

    assert result["dry_run"] is True
    assert not output_path.exists()
    assert not flat_path.exists()
    assert not manifest_path.exists()
    assert not rejects_path.exists()


def test_simulated_user_prompt_uses_private_context_without_hidden_catalog() -> None:
    from rs_core.simulation.schema import RoleState, SimulatedCustomerRole

    customer = SimulatedCustomerRole(
        role_id="u1",
        persona="Private cautious shopper",
        shopping_goal="Hidden goal",
        initial_request="Prefer categories: Audio. I need something for commuting.",
        private_context={"persona": {"persona": "Private cautious shopper"}, "past_interactions_summary": {"recent_categories": ["Audio"]}},
    )
    messages = _simulated_user_messages(
        customer,
        RoleState(),
        history=[{"turn_index": 1, "user_message": "I need something useful", "assistant_message": "Here are options."}],
        last_display={"assistant_message": "Here are options.", "items": [{"parent_asin": "shown_1", "title": "Shown item"}]},
        phase="next_action",
    )

    prompt = json.dumps(messages, ensure_ascii=False)
    assert "private_context" in prompt
    assert "visible_dialogue_history" in prompt
    assert "hidden catalog" in messages[0]["content"]
    assert "shown_1" in prompt
    assert "candidate_pool" not in prompt
    assert "score" not in messages[1]["content"]
    assert "label" not in messages[1]["content"]


def test_recommendation_composer_api_payload_is_minimized() -> None:
    captured: dict[str, Any] = {}

    class CapturingAdapter:
        def complete_with_metadata(self, messages: list[dict[str, str]]) -> tuple[str, dict[str, Any]]:
            captured["messages"] = messages
            return json.dumps({"assistant_message": "Only shown item a is visible."}), {"usage": {"total_tokens": 1}}

    composer = RecommendationAgentComposer(CapturingAdapter())  # type: ignore[arg-type]
    message, metadata = composer.compose(
        persona={
            "persona": "Public summary",
            "shopping_goal": "private goal should not leave process",
            "past_interactions_summary": {"recent_item_summaries": ["private history"]},
            "memory": ["private memory"],
            "budget_sensitivity": "medium",
            "decision_style": "careful",
            "feedback_style": "direct",
        },
        user_message="show me audio",
        display={"assistant_message": "Here is a.", "items": [{"parent_asin": "a", "title": "A", "source_scores": {"hidden": 1}}]},
        history=[
            {
                "turn_index": 1,
                "user_message": "hello",
                "assistant_message": "hi",
                "display_item_ids": ["a"],
                "tool_supervision": {"expected_tool_calls": ["query_rag"]},
                "target_action": {"allowed_item_ids": ["a"]},
            }
        ],
    )

    payload = json.loads(captured["messages"][1]["content"])
    payload_text = json.dumps(payload, ensure_ascii=False)
    assert message == "Only shown item a is visible."
    assert metadata["api_called"] is True
    assert set(payload) == {"public_persona_summary", "latest_user_message", "service_assistant_message", "display_items", "visible_dialogue"}
    assert "shopping_goal" not in payload_text
    assert "past_interactions_summary" not in payload_text
    assert "private history" not in payload_text
    assert "tool_supervision" not in payload_text
    assert "target_action" not in payload_text
    assert "source_scores" not in payload_text


def test_recommendation_composer_empty_display_passthrough_without_adapter_call() -> None:
    class FailingAdapter:
        def complete_with_metadata(self, _messages: list[dict[str, str]]) -> tuple[str, dict[str, Any]]:
            raise AssertionError("adapter should not be called")

    composer = RecommendationAgentComposer(FailingAdapter())  # type: ignore[arg-type]

    message, metadata = composer.compose(
        persona={},
        user_message="为什么推荐？",
        display={"assistant_message": "请先告诉我你想找哪类商品。", "items": []},
        history=[],
    )

    assert message == "请先告诉我你想找哪类商品。"
    assert metadata == {"mode": "composer_skipped_no_grounding", "api_called": False}


def test_compose_grounded_response_skips_stale_display_when_no_recommend() -> None:
    class FailingComposer:
        def compose(self, **_kwargs: Any) -> tuple[str, dict[str, Any]]:
            raise AssertionError("composer should not be called")

    display = {
        "assistant_message": "我先确认一下你的具体需求。",
        "items": [{"parent_asin": "B001", "title": "Stale displayed item"}],
    }

    message, metadata = _compose_grounded_response(
        FailingComposer(),  # type: ignore[arg-type]
        persona={},
        user_message="随便聊聊",
        display=display,
        history=[],
        diagnostics={"should_recommend": False},
    )

    assert message == "我先确认一下你的具体需求。"
    assert metadata == {"mode": "dialogue_only_passthrough", "api_called": False, "composer_skipped_no_grounding": True}


def test_tool_supervision_can_include_call_rag_agent_without_low_level_rag_tools() -> None:
    record = _turn_record(
        1,
        RoleAction.chat("I need home office gear"),
        {"assistant_message": "Here are display-grounded options.", "items": [{"parent_asin": "a", "title": "A"}]},
        "Here are display-grounded options.",
        diagnostics={
            "should_recommend": True,
            "conversation_intent": "recommend_request",
            "agent_action": "recommend_items",
            "agent_tool_events": [
                {"tool_name": "get_user_context", "phase": "pre_recommendation", "status": "ok", "arguments": {"hidden": True}},
                {"tool_name": "call_rag_agent", "phase": "pre_recommendation", "status": "ok", "output": {"rag_agent_support": "hidden"}},
                {"tool_name": "retrieve_candidates", "phase": "pre_recommendation", "status": "ok"},
                {"tool_name": "rank_candidates", "phase": "post_recommendation", "status": "ok"},
            ],
            "agent_tool_summary": {"event_count": 4, "executed_count": 4, "skipped_count": 0, "error_count": 0},
        },
    )

    supervision = record["tool_supervision"]
    assert "call_rag_agent" in supervision["expected_tool_calls"]
    assert "query_rag" not in str(supervision)
    assert "get_item_evidence" not in str(supervision)
    assert "rag_agent_support" not in str(supervision)


def test_turn_record_display_grounded_selects_public_display_items() -> None:
    record = _turn_record(
        1,
        RoleAction.feedback("dislike", "old_item", "not this one"),
        {"assistant_message": "Here are alternatives.", "items": [{"parent_asin": "new_a"}, {"parent_asin": "new_b"}]},
        "Here are alternatives.",
        diagnostics={"should_recommend": True, "agent_action": "recommend_items"},
    )

    assert record["selected_item_ids"] == ["new_a", "new_b"]
    assert record["target_action"]["selected_item_ids"] == ["new_a", "new_b"]
    assert "old_item" not in str(record["target_action"])


def test_turn_record_dialogue_only_does_not_select_feedback_item() -> None:
    record = _turn_record(
        1,
        RoleAction.why("a"),
        {"assistant_message": "I need a recommendation first.", "items": [{"parent_asin": "a"}]},
        "I need a recommendation first.",
        diagnostics={"should_recommend": False, "agent_action": "explain_recommendation"},
    )

    assert record["selected_item_ids"] == []
    assert record["target_action"]["selected_item_ids"] == []
    assert record["target_action"]["must_select_from_candidates"] is False


def test_turn_record_dialogue_only_target_action_without_grounding() -> None:
    record = _turn_record(
        1,
        RoleAction.chat("随便聊聊"),
        {"assistant_message": "可以，我先不推荐商品。", "items": []},
        "可以，我先不推荐商品。",
        diagnostics={"should_recommend": False, "agent_action": "ask_clarifying_question"},
    )

    assert record["display_item_ids"] == []
    assert record["target_action"]["strategy_name"] == "clarification_response"
    assert record["target_action"]["allowed_item_ids"] == []
    assert record["target_action"]["must_select_from_candidates"] is False


def test_validate_multi_turn_sft_rejects_empty_display_must_select() -> None:
    sample = {
        "schema_version": "rs_agent_multi_turn_sft_sample_v1",
        "sample_id": "sample-empty-must-select",
        "dialogue": [
            {
                "turn_index": 1,
                "user_message": "hello",
                "assistant_message": "我需要更多信息。",
                "display_item_ids": [],
                "selected_item_ids": [],
                "target_action": {"strategy_name": "dialogue_only_response", "allowed_item_ids": [], "selected_item_ids": [], "must_select_from_candidates": True},
            },
            {
                "turn_index": 2,
                "user_message": "thanks",
                "assistant_message": "好的。",
                "display_item_ids": [],
                "selected_item_ids": [],
                "target_action": {"strategy_name": "dialogue_only_response", "allowed_item_ids": [], "selected_item_ids": [], "must_select_from_candidates": False},
            },
        ],
        "grounding": {"forbidden_eval_fields_present": False},
    }

    with pytest.raises(ValueError, match="must_select_from_candidates requires non-empty display_item_ids"):
        validate_multi_turn_sft_sample(sample)


def test_validate_multi_turn_sft_rejects_no_grounding_product_list() -> None:
    sample = {
        "schema_version": "rs_agent_multi_turn_sft_sample_v1",
        "sample_id": "sample-no-grounding-list",
        "dialogue": [
            {
                "turn_index": 1,
                "user_message": "hello",
                "assistant_message": "1. 推荐商品 A\n2. 推荐商品 B",
                "display_item_ids": [],
                "selected_item_ids": [],
                "target_action": {"strategy_name": "dialogue_only_response", "allowed_item_ids": [], "selected_item_ids": [], "must_select_from_candidates": False},
                "tool_supervision": {"should_recommend": False},
            },
            {
                "turn_index": 2,
                "user_message": "thanks",
                "assistant_message": "好的。",
                "display_item_ids": [],
                "selected_item_ids": [],
                "target_action": {"strategy_name": "dialogue_only_response", "allowed_item_ids": [], "selected_item_ids": [], "must_select_from_candidates": False},
            },
        ],
        "grounding": {"forbidden_eval_fields_present": False},
    }

    with pytest.raises(ValueError, match="obvious recommendation list"):
        validate_multi_turn_sft_sample(sample)


def test_validate_multi_turn_sft_rejects_no_recommend_grounded_strategy() -> None:
    sample = {
        "schema_version": "rs_agent_multi_turn_sft_sample_v1",
        "sample_id": "sample-no-recommend-grounded",
        "dialogue": [
            {
                "turn_index": 1,
                "user_message": "hello",
                "assistant_message": "我需要更多信息。",
                "display_item_ids": ["a"],
                "selected_item_ids": [],
                "target_action": {"strategy_name": "public_display_grounded_response", "allowed_item_ids": ["a"], "selected_item_ids": [], "must_select_from_candidates": True},
                "tool_supervision": {"should_recommend": False},
            },
            {
                "turn_index": 2,
                "user_message": "thanks",
                "assistant_message": "好的。",
                "display_item_ids": [],
                "selected_item_ids": [],
                "target_action": {"strategy_name": "dialogue_only_response", "allowed_item_ids": [], "selected_item_ids": [], "must_select_from_candidates": False},
            },
        ],
        "grounding": {"forbidden_eval_fields_present": False},
    }

    with pytest.raises(ValueError, match="no-recommend turn cannot use public_display_grounded_response"):
        validate_multi_turn_sft_sample(sample)


def test_validate_multi_turn_sft_rejects_nested_selected_outside_display() -> None:
    sample = _valid_two_turn_sample()
    sample["dialogue"][0]["selected_item_ids"] = ["missing"]
    sample["dialogue"][0]["target_action"]["selected_item_ids"] = ["missing"]

    with pytest.raises(ValueError, match="selected_item_ids must be a subset of display_item_ids"):
        validate_multi_turn_sft_sample(sample)


def test_validate_multi_turn_sft_rejects_nested_selected_mismatch() -> None:
    sample = _valid_two_turn_sample()
    sample["dialogue"][0]["selected_item_ids"] = ["a"]
    sample["dialogue"][0]["target_action"]["selected_item_ids"] = ["b"]
    sample["dialogue"][0]["target_action"]["allowed_item_ids"] = ["a", "b"]
    sample["dialogue"][0]["display_item_ids"] = ["a", "b"]

    with pytest.raises(ValueError, match="selected_item_ids must match target_action.selected_item_ids"):
        validate_multi_turn_sft_sample(sample)


def test_role_action_from_payload_rejects_accept_without_display_items() -> None:
    with pytest.raises(ValueError, match="accept action requires a displayed item"):
        _role_action_from_payload({"action_type": "accept", "comment": "Looks good."}, {"items": []})


def test_validate_multi_turn_sft_rejects_allowed_ids_outside_display() -> None:
    sample = _valid_two_turn_sample()
    sample["dialogue"][0]["target_action"]["allowed_item_ids"] = ["a", "missing"]

    with pytest.raises(ValueError, match="allowed_item_ids must be a subset of display_item_ids"):
        validate_multi_turn_sft_sample(sample)


def test_flatten_skips_stale_display_no_recommend_turn() -> None:
    sample = _valid_two_turn_sample()
    sample["dialogue"][1]["display_item_ids"] = ["a"]
    sample["dialogue"][1]["selected_item_ids"] = []
    sample["dialogue"][1]["target_action"] = {"strategy_name": "dialogue_only_response", "allowed_item_ids": [], "selected_item_ids": [], "must_select_from_candidates": False}
    sample["dialogue"][1]["tool_supervision"] = {"should_recommend": False}

    flat = _flatten_turn_samples(sample)

    assert len(flat) == 1
    assert flat[0]["metadata"]["turn_index"] == 1


def test_flatten_manifest_counts_dropped_no_display_turns(tmp_path) -> None:
    sample = _valid_two_turn_sample()
    sample["dialogue"][1]["display_item_ids"] = []
    sample["dialogue"][1]["selected_item_ids"] = []
    sample["dialogue"][1]["target_action"] = {"strategy_name": "dialogue_only_response", "allowed_item_ids": [], "selected_item_ids": [], "must_select_from_candidates": False}

    assert len(_flatten_turn_samples(sample)) == 1
    manifest = _manifest(
        config_path="config.yaml",
        output_path=tmp_path / "samples.jsonl",
        flat_output_path=tmp_path / "flat.jsonl",
        rejects_path=tmp_path / "rejects.jsonl",
        target_samples=1,
        samples=[sample],
        rejects=[],
        model_config={"model": "m", "api_base": "https://example.test", "api_key_env": "KEY"},
        dry_run=True,
        execute=False,
    )

    assert manifest["schema_version"] == MULTI_TURN_RUN_SCHEMA_VERSION
    assert manifest["quality_summary"]["flat_artifact_contract"] == "display_only"
    assert manifest["quality_summary"]["dialogue_turn_samples_total"] == 2
    assert manifest["quality_summary"]["flattened_turn_samples"] == 1
    assert manifest["quality_summary"]["dropped_no_display_turn_samples"] == 1


def test_dialogue_only_assistant_sanitizer_removes_item_recommendation_and_rating() -> None:
    sanitized = _sanitize_dialogue_only_assistant_message("推荐 A（B012345678），主要因为它属于 Office Products；展示评分为5.0。")

    assert "展示评分" not in sanitized
    assert "B012345678" not in sanitized
    assert "暂不提供具体选项" in sanitized


def test_deterministic_composer_writes_item_specific_reasons() -> None:
    composer = RecommendationAgentComposer()

    message, metadata = composer.compose(
        persona={"shopping_goal": "workspace"},
        user_message="show me workspace items",
        display={
            "assistant_message": "I will use your request and recent context to build recommendations.",
            "items": [
                {"parent_asin": "B000000001", "title": "Compact Desk Hub", "category": "Office Products", "summary": "Keeps a small desk organized."},
                {"parent_asin": "B000000002", "title": "Cable Clip Set", "category": "Office Products", "features": ["adhesive", "desk cable routing"]},
            ],
        },
        history=[],
    )

    assert metadata["api_called"] is False
    assert "I will use your request" not in message
    assert "Compact Desk Hub" in message
    assert "B000000001" not in message
    assert "当前可展示" not in message
    assert "召回" not in message
    assert "organized" in message or "实用" in message or "解决" in message


def test_simulated_user_asks_why_when_recommendation_has_no_reasons() -> None:
    role = SimulatedCustomerRole(
        role_id="r1",
        persona="office shopper",
        shopping_goal="organize workspace",
        category_preferences=("Office",),
        keyword_preferences=("desk",),
    )
    action = RolePolicy().next_action(
        role,
        RoleState(),
        {"assistant_message": "I will use your request and recent context to build recommendations.", "items": [{"parent_asin": "B000000001", "title": "Desk Organizer", "category": "Office Products"}]},
    )

    assert action.type.value == "why"
    assert action.item_id == "B000000001"


def test_sft_judge_accepts_valid_multi_turn_sample() -> None:
    sample = _valid_two_turn_sample()

    report = judge_sft_sample(sample)

    assert report["schema_version"] == SFT_JUDGE_SCHEMA_VERSION
    assert report["hard_fail"] is False
    assert report["decision"] == "accept"
    assert report["satisfactory"] is True
    assert report["total_score"] >= 85



def test_sft_judge_rejects_candidate_pool_violation() -> None:
    sample = _valid_two_turn_sample()
    sample["dialogue"][0]["selected_item_ids"] = ["missing"]
    sample["dialogue"][0]["target_action"]["selected_item_ids"] = ["missing"]

    report = judge_sft_sample(sample)

    assert report["hard_fail"] is True
    assert report["decision"] == "reject"
    assert "candidate_pool_violation" in report["hard_fail_reasons"]
    assert report["satisfactory"] is False


def test_sft_judge_rejects_assistant_item_id_outside_candidate_pool() -> None:
    sample = _valid_two_turn_sample()
    sample["dialogue"][0]["assistant_message"] = "I recommend item_id: missing because it looks relevant."

    report = judge_sft_sample(sample)

    assert report["hard_fail"] is True
    assert "candidate_pool_reference_violation" in report["hard_fail_reasons"]


def test_sft_judge_rejects_unsupported_product_attribute_claims() -> None:
    sample = _valid_two_turn_sample()
    sample["dialogue"][0]["assistant_message"] = "Item a is in stock, top rated, and has a strong discount."

    report = judge_sft_sample(sample)

    assert report["hard_fail"] is True
    assert "unsupported_product_attribute_claim" in report["hard_fail_reasons"]


def test_sft_judge_rejects_chinese_and_snake_case_leakage() -> None:
    sample = _valid_two_turn_sample()
    sample["dialogue"][0]["assistant_message"] = "internal_score 显示这是真实标签里的正样本。"

    report = judge_sft_sample(sample)

    assert report["hard_fail"] is True
    assert "label_or_oracle_leakage" in report["hard_fail_reasons"]


def test_sft_judge_rejects_flat_tool_supervision_low_level_tool_leak() -> None:
    sample = _valid_two_turn_sample()
    flat = _flatten_turn_samples(sample)[0]
    flat["metadata"]["tool_supervision"] = {"expected_tool_calls": ["query_rag", "get_item_evidence"]}

    report = judge_sft_sample(flat)

    assert report["hard_fail"] is True
    assert "unsafe_tool_supervision" in report["hard_fail_reasons"]


def test_sft_judge_summary_requires_all_samples_satisfactory() -> None:
    good = _valid_two_turn_sample()
    bad = _valid_two_turn_sample()
    bad["sample_id"] = "bad"
    bad["dialogue"][0]["target_action"] = {"strategy_name": "public_display_grounded_response", "allowed_item_ids": ["a"], "selected_item_ids": ["missing"], "must_select_from_candidates": True}
    bad["dialogue"][0]["selected_item_ids"] = ["missing"]

    reports, summary = judge_sft_samples([good, bad])

    assert len(reports) == 2
    assert summary["sample_count"] == 2
    assert summary["decision_counts"]["accept"] == 1
    assert summary["decision_counts"]["reject"] == 1
    assert summary["judge_satisfied"] is False


def test_run_one_scene_terminal_accept_uses_accept_feedback_diagnostics() -> None:
    class AcceptingUser:
        def initial_action(self, *_args: Any) -> RoleAction:
            return RoleAction.chat("show me audio")

        def next_action(self, *_args: Any) -> RoleAction:
            return RoleAction.accept("a", "I will take A.")

    class FakeService:
        def __init__(self) -> None:
            self.turns: list[Any] = []
            self.feedback_calls: list[tuple[str, str | None, str | None]] = []
            self.env = SimpleNamespace(config_path="fake-config.yaml")
            self.feedback_session_facade = SimpleNamespace(export_session=lambda _session_id: {"turn_count": len(self.turns)})

        def start_session(self, *, user_id: str) -> str:
            return f"session-{user_id}"

        def chat(self, _session_id: str, _message: str) -> Any:
            self.turns.append(SimpleNamespace(diagnostics={"should_recommend": True, "agent_action": "recommend_items"}))
            return SimpleNamespace(display={"assistant_message": "Here is A.", "items": [{"parent_asin": "a", "title": "A"}]})

        def feedback(self, _session_id: str, action_type: str, item_id: str | None, comment: str | None) -> Any:
            self.feedback_calls.append((action_type, item_id, comment))
            self.turns.append(SimpleNamespace(diagnostics={
                "should_recommend": False,
                "conversation_intent": "preference_feedback",
                "agent_action": "record_acceptance",
                "agent_tool_events": [{"tool_name": "record_user_feedback", "phase": "post_recommendation", "status": "ok"}],
                "agent_tool_summary": {"event_count": 1, "executed_count": 1, "skipped_count": 0, "error_count": 0},
            }))
            return SimpleNamespace(display={"assistant_message": "用户接受了当前推荐。", "items": []})

        def get_agent_session(self, _session_id: str) -> Any:
            return SimpleNamespace(turns=self.turns)

    service = FakeService()
    sample = _run_one_scene(
        service=service,  # type: ignore[arg-type]
        user_id="u1",
        role=SimpleNamespace(private_context={}),  # type: ignore[arg-type]
        persona={"segment": "warm"},
        sample_index=1,
        min_turns=2,
        max_turns=2,
        simulated_user=AcceptingUser(),  # type: ignore[arg-type]
        recommendation_composer=RecommendationAgentComposer(),
        model_name="deterministic",
        execute=False,
    )

    assert service.feedback_calls == [("accept", "a", "I will take A.")]
    terminal = sample["dialogue"][-1]
    assert terminal["selected_item_ids"] == ["a"]
    assert terminal["tool_supervision"]["agent_action"] == "record_acceptance"
    assert terminal["tool_supervision"]["expected_tool_calls"] == ["record_user_feedback"]


def _valid_two_turn_sample() -> dict[str, Any]:
    return {
        "schema_version": "rs_agent_multi_turn_sft_sample_v1",
        "sample_id": "sample-valid",
        "dialogue": [
            {
                "turn_index": 1,
                "user_message": "show me audio",
                "assistant_message": "我推荐 Audio Desk Speaker（a），因为它属于 Audio 类目，并且当前展示信息和你的音频需求匹配，可以作为优先比较的选项。",
                "display_item_ids": ["a"],
                "selected_item_ids": ["a"],
                "target_action": {"strategy_name": "public_display_grounded_response", "allowed_item_ids": ["a"], "selected_item_ids": ["a"], "must_select_from_candidates": True},
                "tool_supervision": {"should_recommend": True},
            },
            {
                "turn_index": 2,
                "user_message": "why?",
                "assistant_message": "最近一次推荐列表里推荐 Audio Desk Speaker（a），主要因为它属于 Audio 类目，和你当前想找音频设备的需求更接近。",
                "display_item_ids": [],
                "selected_item_ids": [],
                "target_action": {"strategy_name": "dialogue_only_response", "allowed_item_ids": [], "selected_item_ids": [], "must_select_from_candidates": False},
                "tool_supervision": {"should_recommend": False},
                "action_type": "why",
            },
        ],
        "grounding": {"forbidden_eval_fields_present": False},
    }


def test_recommendation_composer_uses_openai_compatible_adapter(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_transport(_url: str, _headers: dict[str, str], payload: dict[str, Any], _timeout_seconds: float) -> dict[str, Any]:
        assert payload["model"] == "gpt-5.3-codex-spark"
        return {
            "id": "chatcmpl-test",
            "model": payload["model"],
            "choices": [
                {
                    "message": {"role": "assistant", "content": json.dumps({"assistant_message": "这几件都来自当前展示商品。"}, ensure_ascii=False)},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"total_tokens": 9},
        }

    monkeypatch.setenv("RS_agent", "secret-test-key")
    adapter = OpenAICompletionAdapter(
        client=OpenAICompatibleClient(base_url="https://cpa2api.sinrotic233.com", api_key_env="RS_agent", transport=fake_transport),
        model="gpt-5.3-codex-spark",
        response_format={"type": "json_object"},
    )
    composer = RecommendationAgentComposer(adapter)

    message, metadata = composer.compose(
        persona={"shopping_goal": "audio"},
        user_message="show me audio",
        display={"assistant_message": "Here are items.", "items": [{"parent_asin": "a", "title": "A"}]},
        history=[],
    )

    assert message == "这几件都来自当前展示商品。"
    assert metadata["api_called"] is True
    assert metadata["response"]["usage"] == {"total_tokens": 9}
    assert "secret-test-key" not in str(metadata)
