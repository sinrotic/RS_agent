from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
pytestmark = pytest.mark.experiment

import torch

from rs_core.common.io import write_json, write_jsonl
from rs_core.recsys.candidate_merge import load_graph_walk_seed_recall, graph_walk_seed_candidates_for_user
from rs_core.workflow.graph_walk_training import build_item_graph, generate_random_walks, graph_walk_pair_rows, skipgram_pairs
from scripts.run_phase_1_19_graph_walk_seed_gate import _phase_1_19_gate


def test_graph_walk_training_helpers_are_deterministic_and_exclude_self_neighbors():
    sequences = [
        {"recent_positive_item_sequence": ["a", "b", "c"], "recent_strong_positive_item_sequence": ["a", "c"]},
        {"recent_positive_item_sequence": ["a", "b"], "recent_strong_positive_item_sequence": []},
    ]

    graph = build_item_graph(sequences)
    walks = generate_random_walks(graph, seed=7, walk_length=4, walks_per_node=2)
    repeated_walks = generate_random_walks(graph, seed=7, walk_length=4, walks_per_node=2)
    pairs = skipgram_pairs([["a", "b", "c"]], window_size=1)
    rows = graph_walk_pair_rows(["a", "b", "c"], torch.eye(3), neighbor_k=2, chunk_size=1)

    assert graph == {
        "a": {"b": 2.0, "c": 1.0},
        "b": {"a": 2.0, "c": 1.0},
        "c": {"a": 1.0, "b": 1.0},
    }
    assert walks == repeated_walks
    assert pairs == [("a", "b"), ("b", "a"), ("b", "c"), ("c", "b")]
    assert all(row["src_item"] != row["dst_item"] for row in rows)
    assert {row["source"] for row in rows} == {"graph_walk_seed"}
    assert {row["algorithm"] for row in rows} == {"deepwalk"}


def test_graph_walk_manifest_and_sidecar_fail_closed(tmp_path: Path):
    sidecar_path = tmp_path / "graph_walk_seed_neighbors.jsonl"
    manifest_path = tmp_path / "graph_walk_seed_manifest.json"
    write_jsonl(sidecar_path, [{"src_item": "seed", "dst_item": "target", "score": 0.9, "rank": 1, "source": "graph_walk_seed", "algorithm": "deepwalk"}])
    write_json(manifest_path, {
        "phase": "1.19",
        "source": "graph_walk_seed",
        "schema_version": "graph_walk_seed_pairs_v1",
        "algorithm": "deepwalk",
        "sidecar_hash": _sha256_file(sidecar_path),
    })

    loaded = load_graph_walk_seed_recall(sidecar_path, manifest_path=manifest_path)
    assert loaded["seed"][0].item_id == "target"
    assert loaded["seed"][0].source == "graph_walk_seed"

    write_json(manifest_path, {
        "phase": "1.19",
        "source": "item_graph",
        "schema_version": "graph_walk_seed_pairs_v1",
        "algorithm": "deepwalk",
        "sidecar_hash": _sha256_file(sidecar_path),
    })
    with pytest.raises(ValueError, match="source"):
        load_graph_walk_seed_recall(sidecar_path, manifest_path=manifest_path)

    write_jsonl(sidecar_path, [{"src_item": "seed", "dst_item": "target", "score": 0.9, "rank": 1, "source": "item_graph", "algorithm": "deepwalk"}])
    write_json(manifest_path, {
        "phase": "1.19",
        "source": "graph_walk_seed",
        "schema_version": "graph_walk_seed_pairs_v1",
        "algorithm": "deepwalk",
        "sidecar_hash": _sha256_file(sidecar_path),
    })
    with pytest.raises(ValueError, match="sidecar source"):
        load_graph_walk_seed_recall(sidecar_path, manifest_path=manifest_path)


def test_graph_walk_seed_candidates_are_default_off_and_filter_seen_items():
    sidecar = {
        "strong_seed": [
            _candidate("seen", 0.99),
            _candidate("target", 0.8),
        ],
        "positive_seed": [_candidate("other", 0.7)],
    }
    sequence = {
        "recent_strong_positive_item_sequence": ["strong_seed"],
        "recent_positive_item_sequence": ["positive_seed"],
        "recent_item_sequence": ["seen", "strong_seed", "positive_seed"],
    }

    assert graph_walk_seed_candidates_for_user(sequence, sidecar, {}) == []

    rows = graph_walk_seed_candidates_for_user(
        sequence,
        sidecar,
        {
            "graph_walk_seed_enabled": True,
            "graph_walk_seed_per_seed": 2,
            "graph_walk_seed_per_user": 5,
            "graph_walk_seed_recency_decay": 0.5,
            "graph_walk_seed_score_floor": 0.0,
        },
    )

    assert [row.item_id for row in rows] == ["target", "other"]
    assert rows[0].source == "graph_walk_seed"
    assert rows[0].metadata["graph_walk_seed_item"] == "strong_seed"
    assert rows[1].score == 0.35


def test_phase_1_19_gate_requires_diagnostics_and_lift():
    baseline = _metrics(candidate_hit_users=2, candidate_hit_rate_at_pool=0.2, recall_at_pool=0.1)
    disabled = _metrics(candidate_hit_users=2, candidate_hit_rate_at_pool=0.2, recall_at_pool=0.1)
    experiment = _metrics(candidate_hit_users=3, candidate_hit_rate_at_pool=0.3, recall_at_pool=0.2, graph_walk_hits=1)
    diagnostics = {
        "source_only": {"candidate_hit_users": 1},
        "without_graph_walk": {"candidate_hit_users": 2},
        "exclusive_hit_users": ["u3"],
        "displaced_baseline_hit_users": [],
        "source_overlap": {"graph_walk_seed_with_item_graph": 0},
        "candidate_share": {"share": 0.1},
        "score_distribution": {"count": 1},
        "budget": {"users_exceeding_cap": []},
    }
    config = {
        "phase_1_19_gate": {"thresholds": {"max_fallback_rate": 0.0, "max_candidate_generation_p95_seconds": 1.0, "max_graph_walk_seed_candidate_share": 0.15}},
        "ltr_model": {"enabled": False},
        "ranking_v2": {"enabled": False},
        "item_feature_rerank": {"enabled": False},
        "source_aware_fusion": {"enabled": False},
    }

    passed = _phase_1_19_gate(baseline, disabled, experiment, None, config, diagnostics)
    missing_diagnostic = _phase_1_19_gate(baseline, disabled, experiment, None, config, {"source_only": {}})

    assert passed["passed"] is True
    assert missing_diagnostic["passed"] is False
    assert missing_diagnostic["checks"]["required_diagnostics_present"] is False


def _candidate(item_id: str, score: float):
    from rs_core.recsys.types import RecallCandidate

    return RecallCandidate(item_id=item_id, source="graph_walk_seed", score=score, metadata={"rank": 1})


def _metrics(candidate_hit_users: int, candidate_hit_rate_at_pool: float, recall_at_pool: float, graph_walk_hits: int = 0) -> dict:
    coverage = {"graph_walk_seed": graph_walk_hits} if graph_walk_hits else {}
    return {
        "candidate_hit_users": candidate_hit_users,
        "candidate_hit_rate_at_pool": candidate_hit_rate_at_pool,
        "recall_at_pool": recall_at_pool,
        "fallback_rate": 0.0,
        "latency": {"candidate_generation_p95_seconds": 0.1},
        "candidate_hit_source_coverage": coverage,
    }


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        digest.update(handle.read())
    return digest.hexdigest()
