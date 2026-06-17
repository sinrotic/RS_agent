from __future__ import annotations

import json
from pathlib import Path

import pytest

from rs_core.recsys.candidate_merge import (
    co_visit_transition_candidates_for_user,
    load_co_visit_transition_graph_manifest,
)

pytestmark = pytest.mark.unit


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")


def _manifest(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": "pool500_co_visit_transition_graph_v1.source_index_manifest",
        "source": "co_visit_fallback_repair",
        "source_status": "UNDERFILL_REPAIR_INDEX_READY",
        "index_scope": "FULL_DERIVED_INDEX",
        "train_only": True,
        "candidate_materialization": "none",
        "underfill_repair_allowed": True,
        "candidate_generation_allowed": False,
        "serving_candidate_source_allowed": False,
        "ranking_input_replacement_allowed": False,
        "ranking_replacement_allowed": False,
        "promotion_allowed": False,
        "pool1000_allowed": False,
        "final_pool500_ready_claimed": False,
        "shard_key": "src_item_sha256_mod",
        "shard_count": 1,
        "outputs": {"edges_shards": ["edges_000.jsonl"]},
    }
    payload.update(overrides)
    return payload


def test_load_co_visit_transition_graph_manifest_and_on_demand_candidates(tmp_path: Path) -> None:
    manifest_path = tmp_path / "source_index_manifest.json"
    _write_json(manifest_path, _manifest())
    _write_jsonl(tmp_path / "edges_000.jsonl", [
        {"source": "co_visit_fallback_repair", "src_item": "seed", "dst_item": "seen", "score": 99.0},
        {"source": "co_visit_fallback_repair", "src_item": "seed", "dst_item": "next", "score": 7.0, "pair_support": 2},
    ])

    lookup = load_co_visit_transition_graph_manifest(manifest_path, allowed_src_items={"seed"})
    rows = co_visit_transition_candidates_for_user(
        {"recent_item_sequence": ["seed", "seen"], "recent_positive_item_sequence": ["seed"]},
        lookup,
        {"co_visit_per_seed": 5, "co_visit_per_user": 5, "co_visit_seed_window": 5},
    )

    assert [row.item_id for row in rows] == ["next"]
    assert rows[0].source == "co_visit_fallback_repair"
    assert rows[0].metadata["seed_item_id"] == "seed"
    assert rows[0].metadata["sequence_transition_index_mode"] == "train_only_full_item_transition_graph"


@pytest.mark.parametrize(
    "override,match",
    [
        ({"source_status": "TARGET_SLICE_DIAGNOSTIC"}, "source_status"),
        ({"index_scope": "TARGET_SLICE_DERIVED_INDEX"}, "index_scope"),
        ({"candidate_generation_allowed": True}, "candidate_generation_allowed"),
        ({"candidates_path": "candidates.jsonl"}, "candidates_path"),
    ],
)
def test_load_co_visit_transition_graph_manifest_rejects_unsafe_contracts(tmp_path: Path, override: dict[str, object], match: str) -> None:
    manifest_path = tmp_path / "source_index_manifest.json"
    _write_json(manifest_path, _manifest(**override))
    _write_jsonl(tmp_path / "edges_000.jsonl", [])

    with pytest.raises(ValueError, match=match):
        load_co_visit_transition_graph_manifest(manifest_path)
