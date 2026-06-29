from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit

import json
from pathlib import Path

from rs_core.common.io import read_jsonl, write_jsonl
from rs_core.agent.rag import RAG_PARENT_PROFILE_FIELD
from rs_core.common.recsys_types import AgentDecision
from rs_core.agent import cli
from rs_core.agent.cli import run_cli_session
from rs_core.agent.rollout import turn_to_rollout_record
from rs_core.agent.contracts.schema import AgentSession, AgentTurn, FeedbackConstraints


def test_cli_simulated_two_turn_writes_rollout_schema(tmp_path: Path):
    config = _write_agent_fixture(tmp_path)
    result = run_cli_session(
        str(config),
        user_id="u1",
        limit_users=1,
        output_dir="agent_cli_test_schema",
        simulate_two_turn=True,
        feedback="I dislike charger_1 and Accessories, prefer Audio and itemcf_weak and bluetooth",
    )

    rollouts = read_jsonl(result["rollout_path"])
    assert len(rollouts) == 2
    assert rollouts[0]["schema_version"] == "rs_agent_rollout_v1"
    assert rollouts[0]["training_status"] == "deferred_environment_reward_only"
    assert rollouts[0]["metadata"]["training_deferred"] is True
    assert "prompt_context" in rollouts[0]
    assert "reward_evidence" in rollouts[0]
    assert "training_samples" in rollouts[0]
    assert "display_response" in rollouts[0]
    assert set(rollouts[0]["training_samples"]) == {"sft_sample", "reward_sample"}
    display_response = rollouts[1]["display_response"]
    assert display_response["schema_version"] == "rs_agent_display_v1"
    assert display_response["session_id"] == rollouts[1]["session_id"]
    assert display_response["user_id"] == rollouts[1]["user_id"]
    assert display_response["turn_index"] == rollouts[1]["turn_index"]
    assert display_response["items"][0]["parent_asin"] == rollouts[1]["agent_decision"]["final_items"][0]["parent_asin"]
    assert "missing_image" in display_response["items"][0]["badges"]
    blocked_display_keys = {"score", "base_score", "agent_boost", "coarse_score", "fine_score", "rerank_score", "final_score", "score_trace", "rank_movement", "diagnostics", "reward_evidence", "training_samples"}
    assert not blocked_display_keys & set(display_response)
    assert not blocked_display_keys & set(display_response["items"][0])
    assert "constraint_filter_events" not in json.dumps(display_response)
    sft_sample = rollouts[1]["training_samples"]["sft_sample"]
    reward_sample = rollouts[1]["training_samples"]["reward_sample"]
    assert sft_sample["user_input"] == "I dislike charger_1 and Accessories, prefer Audio and itemcf_weak and bluetooth"
    assert sft_sample["feedback_constraints"] == rollouts[1]["prompt_context"]["feedback_constraints"]
    assert sft_sample["target_action"]["must_select_from_candidates"] is True
    assert sft_sample["target_action"]["selected_item_ids"] == [item["parent_asin"] for item in rollouts[1]["agent_decision"]["final_items"]]
    assert set(sft_sample["target_action"]["selected_item_ids"]) <= set(sft_sample["target_action"]["allowed_item_ids"])
    assert sft_sample["candidate_summary"][0]["item_id"] == "speaker_1"
    assert "sources" not in sft_sample["candidate_summary"][0]
    assert sft_sample["candidate_summary"][0]["evidence_available"] is True
    assert sft_sample["target_explanation"] == rollouts[1]["agent_decision"]["agent_explanation"]
    assert reward_sample["reward"] == rollouts[1]["reward"]
    assert reward_sample["reward_evidence"] == rollouts[1]["reward_evidence"]
    assert reward_sample["feedback_effect_observed"] is True
    assert reward_sample["policy_type"] == rollouts[1]["policy_type"]
    assert reward_sample["risk_flags"] == rollouts[1]["agent_decision"]["risk_flags"]
    assert "diagnostics" in rollouts[1]
    assert "boost_events" not in rollouts[1]["diagnostics"]
    assert rollouts[1]["diagnostics"]["preferred_keywords"] == {"bluetooth": 1.0}
    assert rollouts[1]["diagnostics"]["disliked_keywords"] == {}
    assert rollouts[1]["prompt_context"]["feedback_constraints"]["preferred_keywords"] == {"bluetooth": 1.0}
    first_items = [item["parent_asin"] for item in rollouts[0]["ranking"]]
    second_items = [item["parent_asin"] for item in rollouts[1]["ranking"]]
    assert "charger_1" in first_items
    assert "charger_1" not in second_items
    assert second_items[0] == "speaker_1"
    assert first_items != second_items
    assert rollouts[1]["reward_evidence"]["feedback_constraints_satisfied"]["feedback_effect_observed"] is True
    for item in rollouts[1]["ranking"]:
        assert {"score", "base_score", "agent_boost", "final_score", "sources"}.isdisjoint(item)
    for item in rollouts[1]["agent_decision"]["final_items"]:
        assert {"score", "base_score", "agent_boost", "final_score", "sources"}.isdisjoint(item)
    display_records = read_jsonl(result["display_responses_path"])
    assert len(display_records) == 2
    assert display_records[1] == rollouts[1]["display_response"]
    display_demo = json.loads(Path(result["display_demo_path"]).read_text(encoding="utf-8"))
    assert display_demo == display_records[-1]
    assert Path(result["report_path"]).exists()
    report = Path(result["report_path"]).read_text(encoding="utf-8")
    assert "Baseline Hybrid Output" in report
    assert "Interactive Agent Output After Feedback" in report
    assert "Feedback Response Summary" in report
    assert "changed_after_feedback: `true`" in report
    assert "feedback_effect_observed: `true`" in report


class FakeQwenLocalClient:
    instances = []

    def __init__(self, policy_config: dict) -> None:
        self.policy_config = policy_config
        self.loaded = False
        FakeQwenLocalClient.instances.append(self)

    def rerank(self, **kwargs):
        raise AssertionError("CLI construction should not load or call the model")


def test_rollout_metadata_summarizes_rag_context_without_raw_evidence() -> None:
    session = AgentSession(session_id="s1", user_id="u1")
    turn = AgentTurn(
        turn_index=1,
        user_input="speaker",
        feedback_constraints=FeedbackConstraints(),
        recommendation=AgentDecision(
            user_id="u1",
            strategy_name="test",
            trigger_reason="test",
            agent_explanation="test",
            risk_flags=[],
            limitations=[],
            final_items=[{"parent_asin": "i1"}],
        ),
        candidates=[{"item_id": "i1"}],
        ranking=[{"parent_asin": "i1"}],
        fallback_used=False,
        diagnostics={},
        rag_context={
            "candidate_item_ids": ["i1"],
            "evidence": [
                {"item_id": "i1", "field": "features", "text": "raw feature evidence", "source": "sqlite_bm25", "score": 1.0},
                {"item_id": "i1", "field": RAG_PARENT_PROFILE_FIELD, "text": "raw parent profile"},
            ],
            "metadata": {"evidence_mode": "explain", "retriever": "sqlite_bm25_small2big", "small2big": {"enabled": True}},
        },
    )
    session.turns.append(turn)

    record = turn_to_rollout_record(turn, session)

    metadata = record["metadata"]
    assert "rag_context" not in metadata
    assert metadata["rag_context_summary"] == {
        "present": True,
        "candidate_scoped": True,
        "public_payload_allowed": False,
        "raw_evidence_exported": False,
        "candidate_item_count": 1,
        "evidence_count": 2,
        "parent_profile_count": 1,
        "evidence_mode": "explain",
        "small2big_enabled": True,
    }
    payload = json.dumps(metadata, ensure_ascii=False)
    assert "raw feature evidence" not in payload
    assert "raw parent profile" not in payload
    for blocked in ("retriever", "bm25", "hybrid", "source", "score", "manifest"):
        assert blocked not in payload.lower()


def test_cli_builds_one_lazy_qwen_client_for_qwen_policy(monkeypatch, tmp_path: Path):
    config = _write_agent_fixture(tmp_path)
    captured = {}

    def fake_from_config(config_path, limit_users=None, inference_client=None, config_overrides=None):
        captured["config_path"] = config_path
        captured["limit_users"] = limit_users
        captured["inference_client"] = inference_client
        captured["config_overrides"] = config_overrides
        raise RuntimeError("stop before environment loads")

    FakeQwenLocalClient.instances = []
    monkeypatch.setattr(cli, "QwenLocalClient", FakeQwenLocalClient)
    monkeypatch.setattr(cli.HybridRecommendationEnvironment, "from_config", staticmethod(fake_from_config))

    try:
        run_cli_session(str(config), limit_users=1, inference_policy="qwen", qwen_model_id="local-qwen")
    except RuntimeError as exc:
        assert str(exc) == "stop before environment loads"
    else:
        raise AssertionError("test should stop before environment loads")

    assert len(FakeQwenLocalClient.instances) == 1
    assert captured["inference_client"] is FakeQwenLocalClient.instances[0]
    assert captured["inference_client"].loaded is False
    assert captured["inference_client"].policy_config["enabled"] is True
    assert captured["inference_client"].policy_config["provider"] == "local_transformers"
    assert captured["inference_client"].policy_config["model"]["model_id"] == "local-qwen"
    expected_overrides = cli._merge_nested(
        cli._cli_feedback_default_overrides(),
        {"inference_policy": {"enabled": True, "model": {"model_id": "local-qwen"}}},
    )
    assert captured["config_overrides"] == expected_overrides


def test_cli_does_not_build_qwen_client_when_policy_off(monkeypatch, tmp_path: Path):
    config = _write_agent_fixture(tmp_path)
    captured = {}

    def fake_from_config(config_path, limit_users=None, inference_client=None, config_overrides=None):
        captured["inference_client"] = inference_client
        captured["config_overrides"] = config_overrides
        raise RuntimeError("stop before environment loads")

    FakeQwenLocalClient.instances = []
    monkeypatch.setattr(cli, "QwenLocalClient", FakeQwenLocalClient)
    monkeypatch.setattr(cli.HybridRecommendationEnvironment, "from_config", staticmethod(fake_from_config))

    try:
        run_cli_session(str(config), limit_users=1, inference_policy="off")
    except RuntimeError as exc:
        assert str(exc) == "stop before environment loads"
    else:
        raise AssertionError("test should stop before environment loads")

    assert FakeQwenLocalClient.instances == []
    assert captured["inference_client"] is None
    assert captured["config_overrides"] == cli._merge_nested(
        cli._cli_feedback_default_overrides(),
        {"inference_policy": {"enabled": False}},
    )


def test_cli_config_policy_uses_resolved_enabled_qwen_local_config(monkeypatch, tmp_path: Path):
    config = _write_agent_fixture(tmp_path, inference_policy={"enabled": True, "model": {"model_id": "configured-qwen"}})
    captured = {}

    def fake_from_config(config_path, limit_users=None, inference_client=None, config_overrides=None):
        captured["inference_client"] = inference_client
        captured["config_overrides"] = config_overrides
        raise RuntimeError("stop before environment loads")

    FakeQwenLocalClient.instances = []
    monkeypatch.setattr(cli, "QwenLocalClient", FakeQwenLocalClient)
    monkeypatch.setattr(cli.HybridRecommendationEnvironment, "from_config", staticmethod(fake_from_config))

    try:
        run_cli_session(str(config), limit_users=1, inference_policy="config")
    except RuntimeError as exc:
        assert str(exc) == "stop before environment loads"
    else:
        raise AssertionError("test should stop before environment loads")

    assert len(FakeQwenLocalClient.instances) == 1
    assert captured["inference_client"] is FakeQwenLocalClient.instances[0]
    assert captured["inference_client"].policy_config["model"]["model_id"] == "configured-qwen"
    assert captured["config_overrides"] == cli._cli_feedback_default_overrides()


def _write_agent_fixture(root: Path, inference_policy: dict | None = None) -> Path:
    clean = root / "clean"
    views = root / "views"
    clean.mkdir()
    views.mkdir()
    write_jsonl(clean / "user_sequences.train.jsonl", [{
        "user_id": "u1",
        "recent_item_sequence": ["seed_audio"],
        "recent_positive_item_sequence": ["seed_audio"],
        "recent_strong_positive_item_sequence": [],
    }])
    write_jsonl(clean / "canonical_interactions.valid.jsonl", [{"user_id": "u1", "parent_asin": "speaker_1", "label_binary": 1}])
    write_jsonl(views / "popular_recall.jsonl", [{"parent_asin": "charger_1", "category": "Accessories", "pop_score": 5}])
    write_jsonl(views / "itemcf_recall_weak.jsonl", [{"src_item": "seed_audio", "dst_item": "speaker_1", "score": 2.0, "category": "Audio", "title_clean": "Bluetooth speaker"}])
    write_jsonl(views / "itemcf_recall_strong.jsonl", [])
    write_jsonl(views / "category_recall_items.jsonl", [
        {"parent_asin": "seed_audio", "main_category": "Audio"},
        {"parent_asin": "speaker_1", "main_category": "Audio"},
    ])
    write_jsonl(views / "category_top_items.jsonl", [{"bucket": "main::Audio", "top_items": [{"parent_asin": "earbuds_1", "score": 1.0}]}])
    config = root / "config.yaml"
    config_payload = {
        "clean_dir": str(clean),
        "views_dir": str(views),
        "output_dir": str(root / "out"),
        "report_path": str(root / "report.md"),
        "top_k": 3,
        "candidate_pool_size": 10,
        "popular_fallback_count": 3,
        "rank_weights": {
            "popular": 1.0,
            "itemcf_weak": 1.0,
            "category": 1.0,
            "feedback_category": 10.0,
            "feedback_source_itemcf_weak": 10.0,
        },
        "feedback_category_boost": 1.0,
        "feedback_source_boost": 1.0,
    }
    if inference_policy is not None:
        config_payload["inference_policy"] = inference_policy
    config.write_text(json.dumps(config_payload), encoding="utf-8")
    return config
