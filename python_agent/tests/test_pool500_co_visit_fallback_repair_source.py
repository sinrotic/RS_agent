from __future__ import annotations

import json
from pathlib import Path

import pytest

from rs_lab.experiments.recall.pool500.common.source_layout import REQUIRED_SOURCE_OUTPUTS
from rs_lab.experiments.recall.pool500.methods.co_visit_fallback_repair.builder import (
    _load_train_transition_index,
    _transition_candidates_for_user,
    _underfill_repair_candidates,
    build_co_visit_fallback_repair_source,
    build_co_visit_transition_graph_index,
)

pytestmark = pytest.mark.unit


def test_transition_index_applies_support_gate_and_popularity_norm(tmp_path: Path) -> None:
    train_interactions = tmp_path / "canonical_interactions.train.jsonl"
    _write_jsonl(
        train_interactions,
        [
            {"user_id": "u1", "parent_asin": "seed", "label_binary": 1},
            {"user_id": "u1", "parent_asin": "popular", "label_binary": 1},
            {"user_id": "u1", "parent_asin": "rare", "label_binary": 1},
            {"user_id": "u2", "parent_asin": "seed", "label_binary": 1},
            {"user_id": "u2", "parent_asin": "popular", "label_binary": 1},
            {"user_id": "u3", "parent_asin": "popular", "label_binary": 1},
            {"user_id": "u4", "parent_asin": "popular", "label_binary": 1},
        ],
    )

    index, audit = _load_train_transition_index(
        train_interactions,
        {"seed"},
        2,
        10,
        transition_decay="reciprocal",
        popularity_norm_alpha=1.0,
        min_pair_support=2,
        min_distinct_user_support=2,
    )

    assert audit["filtered_pair_support_count"] == 1
    assert audit["transition_popularity_norm_alpha"] == 1.0
    assert index["seed"][0]["item_id"] == "popular"
    assert index["seed"][0]["pair_support"] == 2
    assert index["seed"][0]["distinct_user_support"] == 2
    assert index["seed"][0]["candidate_popularity"] == 4
    assert index["seed"][0]["normalized_score"] < index["seed"][0]["raw_score"]


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")


def test_transition_candidates_emit_support_popularity_evidence_and_underfill_filters_seen() -> None:
    sequence = {"user_id": "u1", "recent_item_sequence": ["seed", "seen"], "recent_positive_item_sequence": ["seed"]}
    transition_index = {
        "seed": [
            {"item_id": "seen", "score": 100.0, "raw_score": 100.0, "pair_support": 9, "distinct_user_support": 9, "candidate_popularity": 1, "normalized_score": 100.0},
            {"item_id": "tail", "score": 3.0, "raw_score": 6.0, "pair_support": 2, "distinct_user_support": 2, "candidate_popularity": 3, "normalized_score": 3.0},
        ]
    }
    transition_candidates = _transition_candidates_for_user(sequence, transition_index, {}, 5, 5)

    assert [candidate.item_id for candidate in transition_candidates] == ["tail"]
    assert transition_candidates[0].metadata["sequence_transition_score"] == 6.0
    assert transition_candidates[0].metadata["sequence_transition_support"] == 2
    assert transition_candidates[0].metadata["sequence_transition_candidate_popularity"] == 3
    assert transition_candidates[0].metadata["sequence_transition_normalized_score"] == 3.0

    merged = _underfill_repair_candidates([], [], transition_candidates, {"seen"}, 2)

    assert [candidate.item_id for candidate in merged] == ["tail"]


def test_build_co_visit_transition_graph_writes_full_graph_manifest(tmp_path: Path) -> None:
    clean_dir = tmp_path / "clean"
    train_sequences = clean_dir / "user_sequences.train.jsonl"
    train_interactions = clean_dir / "canonical_interactions.train.jsonl"
    clean_manifest = clean_dir / "manifest.json"
    views_dir = tmp_path / "views"
    semantic = views_dir / "semantic_recall_inputs.jsonl"
    views_manifest = views_dir / "manifest.json"

    _write_jsonl(train_sequences, [{"user_id": "u1", "recent_item_sequence": ["seed"], "recent_positive_item_sequence": ["seed"]}])
    _write_jsonl(train_interactions, [
        {"user_id": "u1", "parent_asin": "seed", "label_binary": 1},
        {"user_id": "u1", "parent_asin": "next", "label_binary": 1},
        {"user_id": "u2", "parent_asin": "seed", "label_binary": 1},
        {"user_id": "u2", "parent_asin": "next", "label_binary": 1},
    ])
    _write_json(clean_manifest, {"train_user_sequences_path": str(train_sequences), "split_paths": {"train": str(train_interactions)}})
    _write_jsonl(semantic, [{"parent_asin": "seed", "title_clean": "wireless mouse", "main_category": "Electronics"}])
    _write_json(views_manifest, {"outputs": {"semantic_recall_inputs": str(semantic)}})

    manifest = build_co_visit_transition_graph_index(
        clean_manifest_path=clean_manifest,
        lightweight_views_manifest_path=views_manifest,
        output_root=tmp_path / "outputs",
        run_id="graph_unit",
        transition_window=2,
        transition_per_seed=5,
        shard_count=2,
        overwrite=True,
    )

    output_dir = tmp_path / "outputs" / "co_visit_fallback_repair" / "graph_unit"
    assert manifest["source_status"] == "UNDERFILL_REPAIR_INDEX_READY"
    assert manifest["index_scope"] == "FULL_DERIVED_INDEX"
    assert manifest["candidate_materialization"] == "none"
    assert manifest["underfill_repair_allowed"] is True
    assert manifest["candidate_generation_allowed"] is False
    assert manifest["serving_candidate_source_allowed"] is False
    assert manifest["ranking_input_replacement_allowed"] is False
    assert manifest["pool1000_allowed"] is False
    assert manifest["final_pool500_ready_claimed"] is False
    assert not (output_dir / "candidates.jsonl").exists()
    assert (output_dir / "source_index_manifest.json").is_file()
    assert (output_dir / "transition_graph_stats.json").is_file()
    edge_rows = []
    for shard in manifest["outputs"]["edges_shards"]:
        edge_rows.extend(json.loads(line) for line in (output_dir / shard).read_text(encoding="utf-8").splitlines())
    assert len(edge_rows) == 1
    assert edge_rows[0]["source"] == "co_visit_fallback_repair"
    assert edge_rows[0]["src_item"] == "seed"
    assert edge_rows[0]["dst_item"] == "next"
    assert edge_rows[0]["pair_support"] == 2



def test_co_visit_fallback_repair_fail_closed_on_forbidden_input(tmp_path: Path) -> None:
    clean_dir = tmp_path / "valid" / "clean"
    train_sequences = clean_dir / "user_sequences.train.jsonl"
    train_interactions = clean_dir / "canonical_interactions.train.jsonl"
    clean_manifest = clean_dir / "manifest.json"
    views_dir = tmp_path / "views"
    semantic = views_dir / "semantic_recall_inputs.jsonl"
    views_manifest = views_dir / "manifest.json"
    users = tmp_path / "eligible_user_manifest.json"

    _write_jsonl(train_sequences, [{"user_id": "u1", "recent_item_sequence": ["seed"], "recent_positive_item_sequence": ["seed"]}])
    _write_jsonl(train_interactions, [{"user_id": "u1", "parent_asin": "seed", "label_binary": 1}])
    _write_json(clean_manifest, {"train_user_sequences_path": str(train_sequences), "split_paths": {"train": str(train_interactions)}})
    _write_jsonl(semantic, [{"parent_asin": "seed", "title_clean": "wireless mouse", "main_category": "Electronics"}])
    _write_json(views_manifest, {"outputs": {"semantic_recall_inputs": str(semantic)}})
    _write_json(users, {"eligible_user_ids": ["u1"]})

    with pytest.raises(ValueError, match="forbidden input path detected"):
        build_co_visit_fallback_repair_source(
            clean_manifest_path=clean_manifest,
            lightweight_views_manifest_path=views_manifest,
            eligible_user_manifest_path=users,
            output_root=tmp_path / "outputs",
            run_id="blocked",
            target_user_limit=1,
            overwrite=True,
        )

    output_dir = tmp_path / "outputs" / "co_visit_fallback_repair" / "blocked"
    assert (output_dir / "no_holdout_audit.json").is_file()
    assert not (output_dir / "source_index_manifest.json").is_file()
    assert json.loads((output_dir / "no_holdout_audit.json").read_text(encoding="utf-8"))["status"] == "BLOCKED"


def test_build_co_visit_fallback_repair_source_writes_governed_artifacts(tmp_path: Path) -> None:
    clean_dir = tmp_path / "clean"
    train_sequences = clean_dir / "user_sequences.train.jsonl"
    _write_jsonl(
        train_sequences,
        [
            {"user_id": "u1", "recent_item_sequence": ["seed"], "recent_positive_item_sequence": ["seed"]},
            {"user_id": "u2", "recent_item_sequence": ["missing"], "recent_positive_item_sequence": ["missing"]},
        ],
    )
    train_interactions = clean_dir / "canonical_interactions.train.jsonl"
    _write_jsonl(
        train_interactions,
        [
            {"user_id": "u3", "parent_asin": "seed", "rating": 5.0, "label_binary": 1},
            {"user_id": "u3", "parent_asin": "transition_candidate", "rating": 5.0, "label_binary": 1},
            {"user_id": "u4", "parent_asin": "seed", "rating": 5.0, "label_binary": 1},
            {"user_id": "u4", "parent_asin": "transition_candidate", "rating": 5.0, "label_binary": 1},
        ],
    )
    clean_manifest = clean_dir / "manifest.json"
    _write_json(clean_manifest, {"train_user_sequences_path": str(train_sequences), "split_paths": {"train": str(train_interactions)}})

    views_dir = tmp_path / "views"
    semantic = views_dir / "semantic_recall_inputs.jsonl"
    _write_jsonl(
        semantic,
        [
            {"parent_asin": "seed", "title_clean": "wireless mouse", "main_category": "Electronics"},
            {"parent_asin": "candidate", "title_clean": "wireless keyboard", "main_category": "Electronics"},
            {"parent_asin": "transition_candidate", "title_clean": "wireless receiver", "main_category": "Electronics"},
        ],
    )
    views_manifest = views_dir / "manifest.json"
    _write_json(views_manifest, {"outputs": {"semantic_recall_inputs": str(semantic)}})

    users = tmp_path / "eligible_user_manifest.json"
    _write_json(users, {"eligible_user_ids": ["u1", "u2"]})

    manifest = build_co_visit_fallback_repair_source(
        clean_manifest_path=clean_manifest,
        lightweight_views_manifest_path=views_manifest,
        eligible_user_manifest_path=users,
        output_root=tmp_path / "outputs",
        run_id="unit",
        max_metadata_rows=10,
        candidate_per_user=5,
        candidate_per_seed=5,
        seed_window=5,
        checkpoint_every_users=1,
        target_user_offset=0,
        target_user_limit=2,
        shard_id=0,
        shard_count=1,
        overwrite=True,
    )

    output_dir = tmp_path / "outputs" / "co_visit_fallback_repair" / "unit"
    for name in REQUIRED_SOURCE_OUTPUTS:
        assert (output_dir / name).is_file()

    assert manifest["source"] == "co_visit_fallback_repair"
    assert manifest["canonical_source"] == "co_visit_fallback_repair"
    assert manifest["status"] == "TARGET_SLICE_DIAGNOSTIC"
    assert manifest["candidate_generation_allowed"] is False
    assert manifest["promotion_allowed"] is False
    assert manifest["ranking_input_replacement_allowed"] is False
    assert manifest["pool1000_allowed"] is False

    coverage = json.loads((output_dir / "coverage_audit.json").read_text(encoding="utf-8"))
    assert coverage["co_visit_seed_coverage"]["count"] == 1
    assert coverage["metadata_neighbor_coverage"]["count"] == 1
    assert coverage["sequence_transition_coverage"]["count"] == 1
    assert coverage["repair_candidate_count"] == 2

    rows = [json.loads(line) for line in (output_dir / "candidates.jsonl").read_text(encoding="utf-8").splitlines()]
    assert rows[0]["source"] == "co_visit_fallback_repair"
    assert rows[0]["sources"] == ["co_visit_fallback_repair"]
    assert rows[0]["metadata"]["source_status"] == "TARGET_SLICE_DIAGNOSTIC"

    resource = json.loads((output_dir / "resource_audit.json").read_text(encoding="utf-8"))
    assert resource["streaming_candidates_enabled"] is True
    assert resource["full_per_user_audit_included"] is True
    assert resource["shard_contract"]["checkpoint_every_users"] == 1
    assert resource["shard_contract"]["formal_shard_mode"] is True
    assert resource["target_user_limit"] == 2
    assert resource["shard_id"] == 0

    no_holdout = json.loads((output_dir / "no_holdout_audit.json").read_text(encoding="utf-8"))
    assert no_holdout["status"] == "PASS"
    assert no_holdout["candidate_generation_uses_holdout"] is False
