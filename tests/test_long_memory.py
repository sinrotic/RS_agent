from __future__ import annotations

import json
from pathlib import Path

import pytest

from rs_core.rsagent.long_memory import (
    InMemoryLongMemoryStore,
    JsonLongMemoryStore,
    LongMemoryConfig,
    build_long_memory_store,
    hydrate_session_from_long_memory,
    recall_relevant_long_memory,
    snapshot_session_long_memory,
    user_long_memory_from_dict,
)
from rs_core.rsagent.schema import AgentSession, FeedbackConstraints

pytestmark = pytest.mark.unit


def test_in_memory_long_memory_roundtrip_is_user_scoped_copy():
    store = InMemoryLongMemoryStore()
    session = AgentSession(session_id="s1", user_id="u1")
    session.active_constraints = FeedbackConstraints(
        liked_item_ids={"item_a"},
        disliked_item_ids={"item_b"},
        preferred_categories={"Audio": 1.0},
        preferred_keywords={"bluetooth": 1.0},
        unsupported_free_text=["do not persist by default"],
    )

    store.save_user_memory(snapshot_session_long_memory(session, LongMemoryConfig(enabled=True)))
    restored = store.load_user_memory("u1")
    missing = store.load_user_memory("u2")

    assert restored is not None
    assert restored.user_id == "u1"
    assert restored.active_constraints.liked_item_ids == {"item_a"}
    assert restored.active_constraints.disliked_item_ids == {"item_b"}
    assert restored.active_constraints.preferred_categories == {"Audio": 1.0}
    assert restored.active_constraints.preferred_keywords == {"bluetooth": 1.0}
    assert restored.active_constraints.unsupported_free_text == []
    assert {entry.entry_id for entry in restored.entries} == {
        "u1:disliked_item:item_b",
        "u1:liked_item:item_a",
        "u1:preferred_category:audio",
        "u1:preferred_keyword:bluetooth",
    }
    assert missing is None

    restored.active_constraints.liked_item_ids.add("mutated")
    restored.entries[0].value["key"] = "mutated"
    reloaded = store.load_user_memory("u1")
    assert reloaded is not None
    assert reloaded.active_constraints.liked_item_ids == {"item_a"}
    assert reloaded.entries[0].value["key"] != "mutated"


def test_json_long_memory_store_roundtrip(tmp_path: Path):
    path = tmp_path / "memory" / "long_memory.json"
    store = JsonLongMemoryStore(path)
    session = AgentSession(session_id="s1", user_id="u1")
    session.active_constraints = FeedbackConstraints(liked_item_ids={"item_a"}, preferred_sources={"itemcf_weak": 1.0})

    store.save_user_memory(snapshot_session_long_memory(session, LongMemoryConfig(enabled=True)))
    reloaded = JsonLongMemoryStore(path).load_user_memory("u1")

    assert reloaded is not None
    assert reloaded.active_constraints.liked_item_ids == {"item_a"}
    assert reloaded.active_constraints.preferred_sources == {"itemcf_weak": 1.0}
    assert [entry.entry_id for entry in reloaded.entries] == ["u1:liked_item:item_a", "u1:preferred_source:itemcf_weak"]
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "rsagent_long_memory_store_v1"
    assert sorted(payload["users"]) == ["u1"]
    assert payload["users"]["u1"]["entries"][0]["type"] == "liked_item"


def test_build_long_memory_store_respects_disabled_and_json_config(tmp_path: Path):
    assert build_long_memory_store(LongMemoryConfig(enabled=False)) is None
    assert build_long_memory_store(LongMemoryConfig(enabled=True, store_type="memory")) is not None
    assert build_long_memory_store(LongMemoryConfig(enabled=True, store_type="json", json_path=str(tmp_path / "m.json"))) is not None

    with pytest.raises(ValueError, match="json_path"):
        build_long_memory_store(LongMemoryConfig(enabled=True, store_type="json"))


def test_hydrate_and_snapshot_merge_memory_into_session():
    source = AgentSession(session_id="old", user_id="u1")
    source.active_constraints = FeedbackConstraints(
        liked_item_ids={"old_like"},
        disliked_categories={"old_category"},
        preferred_keywords={"portable": 1.0},
    )
    memory = snapshot_session_long_memory(source, LongMemoryConfig(enabled=True))
    session = AgentSession(session_id="new", user_id="u1")
    session.active_constraints = FeedbackConstraints(liked_item_ids={"new_like"}, preferred_keywords={"bluetooth": 1.0})

    assert hydrate_session_from_long_memory(session, memory) is True

    assert session.active_constraints.liked_item_ids == {"old_like", "new_like"}
    assert session.active_constraints.disliked_categories == {"old_category"}
    assert session.active_constraints.preferred_keywords == {"portable": 1.0, "bluetooth": 1.0}
    assert session.user_profile.liked_item_ids == ["new_like", "old_like"]

    wrong_user = AgentSession(session_id="wrong", user_id="u2")
    assert hydrate_session_from_long_memory(wrong_user, memory) is False
    assert wrong_user.active_constraints.liked_item_ids == set()


def test_long_memory_loads_legacy_payload_without_entries_and_skips_malformed_entries():
    memory = user_long_memory_from_dict(
        {
            "user_id": "u1",
            "active_constraints": {"liked_item_ids": ["item_a"]},
            "entries": [
                {"entry_id": "u1:preferred_keyword:bluetooth", "type": "preferred_keyword", "value": {"keyword": "bluetooth"}},
                {"entry_id": "broken", "type": "preferred_keyword"},
                "not a dict",
            ],
        }
    )
    legacy = user_long_memory_from_dict({"user_id": "u2", "active_constraints": {"liked_item_ids": ["item_b"]}})

    assert memory.active_constraints.liked_item_ids == {"item_a"}
    assert [entry.entry_id for entry in memory.entries] == ["u1:preferred_keyword:bluetooth"]
    assert legacy.active_constraints.liked_item_ids == {"item_b"}
    assert legacy.entries == []


def test_snapshot_extracts_typed_entries_with_budget_and_can_disable_entries():
    session = AgentSession(session_id="s1", user_id="u1")
    session.active_constraints = FeedbackConstraints(
        liked_item_ids={"item_a", "item_b"},
        disliked_item_ids={"item_c"},
        disliked_categories={"Toys"},
        preferred_categories={"Audio": 1.0},
        preferred_keywords={"bluetooth": 1.0},
        disliked_keywords={"wired": 1.0},
        preferred_sources={"itemcf_weak": 1.0},
        max_price=50.0,
        use_cases={"commute": 1.0},
        filter_prior_turn_items=True,
    )

    memory = snapshot_session_long_memory(session, LongMemoryConfig(enabled=True, max_liked_item_ids=1))
    disabled = snapshot_session_long_memory(session, LongMemoryConfig(enabled=True, enable_typed_entries=False))

    entry_types = {entry.type for entry in memory.entries}
    assert "liked_item" in entry_types
    assert len([entry for entry in memory.entries if entry.type == "liked_item"]) == 1
    assert entry_types >= {
        "disliked_item",
        "disliked_category",
        "preferred_category",
        "preferred_keyword",
        "disliked_keyword",
        "preferred_source",
        "max_price",
        "use_case",
        "freshness_preference",
    }
    assert disabled.entries == []


def test_zero_item_feedback_event_budget_persists_no_events():
    session = AgentSession(session_id="s1", user_id="u1")
    session.active_constraints = FeedbackConstraints(
        item_feedback_events=[{"item_id": "item_a", "action": "like"}],
    )

    memory = snapshot_session_long_memory(session, LongMemoryConfig(enabled=True, max_liked_item_ids=0))

    assert memory.active_constraints.item_feedback_events == []



def test_recall_relevant_long_memory_is_deterministic_and_budgeted():
    session = AgentSession(session_id="s1", user_id="u1")
    session.active_constraints = FeedbackConstraints(
        preferred_categories={"Audio": 1.0},
        preferred_keywords={"bluetooth": 1.0},
        disliked_keywords={"wired": 1.0},
        max_price=50.0,
        use_cases={"commute": 1.0},
    )
    memory = snapshot_session_long_memory(session, LongMemoryConfig(enabled=True))

    recalled = recall_relevant_long_memory(
        memory,
        query="Need bluetooth audio for commute",
        session=session,
        config=LongMemoryConfig(enabled=True, max_recalled_entries=3, recall_min_score=1.0),
    )
    disabled = recall_relevant_long_memory(
        memory,
        query="Need bluetooth audio for commute",
        config=LongMemoryConfig(enabled=True, enable_relevance_recall=False),
    )
    empty = recall_relevant_long_memory(None, query="bluetooth")

    assert recalled["recall_strategy"] == "deterministic_keyword_overlap_v1"
    assert recalled["available_entry_count"] == len(memory.entries)
    assert recalled["entry_count"] == 3
    assert [entry["entry_id"] for entry in recalled["entries"]][:2] == [
        "u1:use_case:commute",
        "u1:preferred_category:audio",
    ]
    assert disabled["entries"] == []
    assert disabled["available_entry_count"] == 0
    assert empty["entry_count"] == 0
