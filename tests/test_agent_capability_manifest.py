from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import pytest

from rs_core.common.io import write_jsonl
from rs_core.rsagent.tools import AGENT_CAPABILITY_MANIFEST, AgentCapability
from rs_core.serving.service import RecommendationService

pytestmark = pytest.mark.unit

EXPECTED_CAPABILITIES = {
    "parse_preferences",
    "apply_constraints",
    "retrieve_candidates",
    "rank_candidates",
    "build_rag_context",
    "explain_recommendation",
    "collect_feedback",
}
BLOCKED_PUBLIC_TERMS = {
    "agent_runtime_trace",
    "runtime_trace",
    "diagnostic",
    "reward",
    "training",
    "source",
}


def test_agent_capability_manifest_is_internal_and_non_public():
    assert AGENT_CAPABILITY_MANIFEST
    assert {capability.name for capability in AGENT_CAPABILITY_MANIFEST} == EXPECTED_CAPABILITIES

    for capability in AGENT_CAPABILITY_MANIFEST:
        assert isinstance(capability, AgentCapability)
        assert capability.stage
        assert isinstance(capability.read_only, bool)
        assert capability.hidden is True
        assert capability.public_payload_allowed is False
        assert capability.description


def test_capability_manifest_is_not_exposed_in_public_chat_feedback_or_export_payloads(tmp_path: Path):
    service = RecommendationService(str(_write_serving_fixture(tmp_path)), limit_users=1)
    session_id = service.start_session("u1")

    chat_payload = asdict(service.chat(session_id, "For commute, prefer bluetooth and Audio"))
    feedback_payload = asdict(service.feedback(session_id, "why", item_id="speaker_1"))
    export_payload = service.export_session(session_id)

    for payload in (chat_payload, feedback_payload, export_payload):
        serialized = json.dumps(payload, ensure_ascii=False).lower()
        for capability in AGENT_CAPABILITY_MANIFEST:
            assert capability.name.lower() not in serialized
            assert capability.description.lower() not in serialized
        for term in BLOCKED_PUBLIC_TERMS:
            assert term not in serialized


def _write_serving_fixture(root: Path) -> Path:
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
