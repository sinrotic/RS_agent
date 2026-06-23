from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from rs_core.common.io import write_jsonl
from rs_core.display import validate_public_display_payload
from rs_core.rsagent.long_memory import InMemoryLongMemoryStore, LongMemoryConfig
from rs_core.serving.application.recommendation_service import RecommendationService

pytestmark = pytest.mark.serving


def test_service_long_memory_disabled_by_default_does_not_cross_sessions(tmp_path: Path):
    service = RecommendationService(str(_write_serving_fixture(tmp_path)), limit_users=1)
    first_session = service.start_session("u1")
    first = service.chat(first_session, "For commute, prefer bluetooth and Audio")
    service.feedback(first_session, "like", first.display["items"][0]["parent_asin"])

    second_session = service.start_session("u1")
    second = service.get_agent_session(second_session)

    assert service.long_memory_config.enabled is False
    assert service.long_memory_store is None
    assert second.active_constraints.liked_item_ids == set()


def test_service_long_memory_enabled_restores_same_user_across_sessions(tmp_path: Path):
    store = InMemoryLongMemoryStore()
    service = RecommendationService(
        str(_write_serving_fixture(tmp_path)),
        limit_users=1,
        long_memory_config=LongMemoryConfig(enabled=True),
        long_memory_store=store,
    )
    first_session = service.start_session("u1")
    first = service.chat(first_session, "For commute, prefer bluetooth and Audio")
    liked_item = first.display["items"][0]["parent_asin"]

    service.feedback(first_session, "like", liked_item)
    second_session = service.start_session("u1")
    second = service.get_agent_session(second_session)

    assert liked_item in second.active_constraints.liked_item_ids
    assert liked_item in second.user_profile.liked_item_ids
    memory = store.load_user_memory("u1")
    assert memory is not None
    assert any(entry.type == "liked_item" and entry.value["item_id"] == liked_item for entry in memory.entries)


def test_service_long_memory_keeps_anonymous_sessions_independent(tmp_path: Path):
    store = InMemoryLongMemoryStore()
    service = RecommendationService(
        str(_write_serving_fixture(tmp_path)),
        limit_users=1,
        long_memory_config=LongMemoryConfig(enabled=True),
        long_memory_store=store,
    )
    first_session = service.start_session()
    first = service.chat(first_session, "For commute, prefer bluetooth and Audio")
    liked_item = first.display["items"][0]["parent_asin"]

    service.feedback(first_session, "like", liked_item)
    second_session = service.start_session()
    second = service.get_agent_session(second_session)

    assert service.get_agent_session(first_session).user_id != second.user_id
    assert service.env.sequences_by_user[second.user_id] == {
        "user_id": second.user_id,
        "recent_item_sequence": [],
        "recent_positive_item_sequence": [],
        "recent_strong_positive_item_sequence": [],
    }
    assert second.active_constraints.liked_item_ids == set()
    assert second.user_profile.liked_item_ids == []
    assert store.load_user_memory(service.get_agent_session(first_session).user_id) is not None
    second_memory = store.load_user_memory(second.user_id)
    assert second_memory is None or second_memory.entries == []


def test_service_long_memory_does_not_leak_between_users(tmp_path: Path):
    store = InMemoryLongMemoryStore()
    service = RecommendationService(
        str(_write_serving_fixture(tmp_path)),
        long_memory_config=LongMemoryConfig(enabled=True),
        long_memory_store=store,
    )
    first_session = service.start_session("u1")
    first = service.chat(first_session, "For commute, prefer bluetooth and Audio")
    liked_item = first.display["items"][0]["parent_asin"]
    service.feedback(first_session, "like", liked_item)

    other_session = service.start_session("u2")
    other = service.get_agent_session(other_session)

    assert other.active_constraints.liked_item_ids == set()
    assert other.user_profile.liked_item_ids == []
    other_memory = store.load_user_memory("u2")
    assert other_memory is None or other_memory.entries == []


def test_service_memory_agent_shadow_does_not_change_long_memory_restore(tmp_path: Path):
    store = InMemoryLongMemoryStore()
    service = RecommendationService(
        str(_write_serving_fixture(tmp_path)),
        limit_users=1,
        long_memory_config=LongMemoryConfig(enabled=True),
        long_memory_store=store,
    )
    service.env.agent_orchestration_facade.runtime_config.metadata["memory_agent"] = {"enabled": True, "mode": "shadow"}
    first_session = service.start_session("u1")
    first = service.chat(first_session, "For commute, prefer bluetooth and Audio")
    liked_item = first.display["items"][0]["parent_asin"]

    service.feedback(first_session, "like", liked_item)
    second_session = service.start_session("u1")
    second = service.get_agent_session(second_session)
    second_display = service.chat(second_session, "Need bluetooth for commute").display
    exported = service.export_session(second_session)

    assert liked_item in second.active_constraints.liked_item_ids
    assert liked_item in second.user_profile.liked_item_ids
    assert "memory_agent_shadow" in service.get_agent_session(second_session).turns[-1].diagnostics
    public_text = json.dumps({"display": second_display, "exported": exported}, ensure_ascii=False).lower()
    assert "memory_agent" not in public_text
    assert "long_memory" not in public_text
    assert "typed_memory" not in public_text


def test_service_memory_agent_shadow_fail_open_on_adapter_error(tmp_path: Path):
    service = RecommendationService(str(_write_serving_fixture(tmp_path)), limit_users=1)
    service.env.agent_orchestration_facade.runtime_config.metadata["memory_agent"] = {"enabled": True, "mode": "shadow"}

    def explode(*_args, **_kwargs):
        raise RuntimeError("private memory path /tmp/memory.log")

    service.env.agent_orchestration_facade.memory_shadow_adapter.attach_shadow_report = explode  # type: ignore[method-assign]
    session_id = service.start_session("u1")

    result = service.chat(session_id, "For commute, prefer bluetooth and Audio")

    assert result.display["items"]
    turn = service.get_agent_session(session_id).turns[-1]
    assert turn.diagnostics["memory_agent_shadow"]["status"] == "error"
    assert "memory_agent" not in json.dumps(result.display, ensure_ascii=False).lower()


def test_service_long_memory_public_export_and_display_do_not_leak_internal_fields(tmp_path: Path):
    service = RecommendationService(
        str(_write_serving_fixture(tmp_path)),
        limit_users=1,
        long_memory_config=LongMemoryConfig(enabled=True),
        long_memory_store=InMemoryLongMemoryStore(),
    )
    session_id = service.start_session("u1")
    display = service.chat(session_id, "For commute, prefer bluetooth and Audio").display
    service.feedback(session_id, "like", display["items"][0]["parent_asin"])
    exported = service.export_session(session_id)

    display_text = json.dumps(display, ensure_ascii=False).lower()
    exported_text = json.dumps(exported, ensure_ascii=False).lower()
    assert "long_memory" not in display_text
    assert "long_memory" not in exported_text
    assert "memory entry" not in display_text
    assert "memory entry" not in exported_text
    _assert_no_key(exported, "active_constraints")
    _assert_no_key(exported, "user_profile")
    _assert_no_key(exported, "typed_memory_entries")

    unsafe = dict(display)
    unsafe["long_memory"] = {"liked_item_ids": ["speaker_1"]}
    with pytest.raises(ValueError):
        validate_public_display_payload(unsafe)

    unsafe = dict(display)
    unsafe["typed_memory_entries"] = [{"entry_id": "u1:liked_item:speaker_1"}]
    with pytest.raises(ValueError):
        validate_public_display_payload(unsafe)


def _assert_no_key(value: Any, key: str) -> None:
    if isinstance(value, dict):
        assert key not in value
        for child in value.values():
            _assert_no_key(child, key)
    elif isinstance(value, list):
        for child in value:
            _assert_no_key(child, key)


def _write_serving_fixture(root: Path) -> Path:
    clean = root / "clean"
    views = root / "views"
    clean.mkdir()
    views.mkdir()
    write_jsonl(clean / "user_sequences.train.jsonl", [
        {
            "user_id": "u1",
            "recent_item_sequence": ["seed_audio"],
            "recent_positive_item_sequence": ["seed_audio"],
            "recent_strong_positive_item_sequence": [],
        },
        {
            "user_id": "u2",
            "recent_item_sequence": ["seed_audio"],
            "recent_positive_item_sequence": ["seed_audio"],
            "recent_strong_positive_item_sequence": [],
        },
    ])
    write_jsonl(clean / "canonical_interactions.valid.jsonl", [{"user_id": "u1", "parent_asin": "speaker_1", "label_binary": 1}])
    write_jsonl(views / "popular_recall.jsonl", [
        {"parent_asin": "charger_1", "category": "Accessories", "pop_score": 5},
    ])
    write_jsonl(views / "itemcf_recall_weak.jsonl", [
        {"src_item": "seed_audio", "dst_item": "speaker_1", "score": 2.0, "category": "Audio", "title_clean": "Bluetooth speaker for commute"},
    ])
    write_jsonl(views / "itemcf_recall_strong.jsonl", [])
    write_jsonl(views / "category_recall_items.jsonl", [
        {"parent_asin": "seed_audio", "main_category": "Audio"},
        {"parent_asin": "speaker_1", "main_category": "Audio"},
    ])
    write_jsonl(views / "category_top_items.jsonl", [{"bucket": "main::Audio", "top_items": [
        {"parent_asin": "earbuds_1", "score": 1.0, "category": "Audio", "title_clean": "Wireless bluetooth earbuds"},
    ]}])
    config = root / "config.yaml"
    config.write_text(json.dumps({
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
            "feedback_keyword": 10.0,
        },
        "feedback_category_boost": 1.0,
        "feedback_keyword_boost": 1.0,
    }), encoding="utf-8")
    return config
