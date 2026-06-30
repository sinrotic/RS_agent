from __future__ import annotations

import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

from rs_lab.experiments.recall.run_phase3_swing_sequence_session_observation import run_phase3_swing_sequence_session_observation


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def make_fixture(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    clean_dir = tmp_path / "amazon_2023_recall_clean_full"
    baseline_dir = tmp_path / "lightweight_representative_e2e"
    phase0_dir = tmp_path / "phase0_contract_precheck"
    phase1_dir = tmp_path / "itemcf_covisit_representative_merge_eval"
    phase2_dir = tmp_path / "usercf_bounded_observation"

    write_jsonl(
        clean_dir / "user_sequences.train.jsonl",
        [
            {"user_id": "u1", "recent_positive_item_sequence": ["a", "b", "c"], "recent_item_sequence": ["a", "b", "c"]},
            {"user_id": "u2", "recent_positive_item_sequence": ["a", "b", "swing_hit"], "recent_item_sequence": ["a", "b", "swing_hit"]},
            {"user_id": "u3", "recent_positive_item_sequence": ["x", "y"], "recent_item_sequence": ["x", "session_hit", "y"]},
        ],
    )
    write_jsonl(clean_dir / "canonical_interactions.valid.jsonl", [{"user_id": "u1", "parent_asin": "swing_hit", "label_binary": 1}])
    write_jsonl(clean_dir / "canonical_interactions.test.jsonl", [{"user_id": "u3", "parent_asin": "base_hit", "label_binary": 1}])
    write_jsonl(clean_dir / "holdout.jsonl", [{"must_not_be_read": True}])

    baseline_rows = [
        {"user_id": "u1", "rank": 1, "item_id": "base_miss", "sources": ["popular"], "source_scores": {"popular": 1.0}},
        {"user_id": "u2", "rank": 1, "item_id": "base_other", "sources": ["semantic"], "source_scores": {"semantic": 2.0}},
        {"user_id": "u3", "rank": 1, "item_id": "base_hit", "sources": ["category"], "source_scores": {"category": 3.0}},
    ]
    write_jsonl(baseline_dir / "candidates.jsonl", baseline_rows)
    write_json(baseline_dir / "manifest.json", {"enabled_sources": ["popular", "category", "semantic"]})
    write_json(baseline_dir / "source_audit.json", {"train_only": True})

    phase1_rows = [
        *baseline_rows,
        {"user_id": "u1", "rank": 2, "item_id": "itemcf_only", "sources": ["bounded_itemcf_covisit"], "source_scores": {"bounded_itemcf_covisit": 1.0}},
    ]
    write_jsonl(phase1_dir / "candidates.jsonl", phase1_rows)
    write_json(phase1_dir / "manifest.json", {"status": "EXECUTED_PASS_OBSERVATION_ONLY"})

    phase2_rows = [
        *baseline_rows,
        {"user_id": "u2", "rank": 2, "item_id": "usercf_only", "sources": ["usercf_bounded"], "source_scores": {"usercf_bounded": 1.0}},
    ]
    write_jsonl(phase2_dir / "candidates.jsonl", phase2_rows)
    write_json(phase2_dir / "manifest.json", {"status": "rejected"})

    write_json(phase0_dir / "manifest.json", {"status": "PASS"})
    write_json(
        phase0_dir / "resolved_inputs.json",
        {
            "full_clean_dir": {"path": str(clean_dir)},
            "lightweight_representative_baseline": {"path": str(baseline_dir)},
        },
    )
    return phase0_dir, phase1_dir, phase2_dir, tmp_path / "swing_sequence_session_observation"


def test_phase3_swing_sequence_session_observation_writes_contract_artifacts(tmp_path: Path) -> None:
    phase0_dir, phase1_dir, phase2_dir, output_dir = make_fixture(tmp_path)

    manifest = run_phase3_swing_sequence_session_observation(
        phase0_dir=phase0_dir,
        phase1_dir=phase1_dir,
        phase2_dir=phase2_dir,
        output_dir=output_dir,
        min_free_bytes=0,
        enforce_venv=False,
        max_users=3,
        max_items_per_user=4,
        max_item_users=3,
        max_pairs=50,
        per_seed=3,
        per_user=3,
    )

    source_audit = read_json(output_dir / "source_audit.json")
    metrics = read_json(output_dir / "metrics.json")
    ablation = read_json(output_dir / "ablation_vs_lightweight_baseline.json")
    session_audit = read_json(output_dir / "session_definition_audit.json")
    sidecar = read_json(output_dir / "transition_sidecar_manifest.json")
    assert manifest["status"] in {"EXECUTED_PASS_OBSERVATION_ONLY", "blocked", "deferred"}
    assert manifest["observation_only"] is True
    assert manifest["required_artifacts"].keys() == {
        "manifest",
        "source_audit",
        "metrics",
        "ablation_vs_lightweight_baseline",
        "session_definition_audit",
        "transition_sidecar_manifest",
        "candidates",
    }
    assert source_audit["train_only_candidate_generation"] is True
    assert source_audit["candidate_generation_uses_holdout"] is False
    assert source_audit["disabled_outputs"] == {"pool500": True, "pool1000": True, "ranking_default_input": True}
    candidate_read_names = [Path(path).name for path in source_audit["candidate_generation_read_files"]]
    assert "canonical_interactions.valid.jsonl" not in candidate_read_names
    assert "canonical_interactions.test.jsonl" not in candidate_read_names
    assert "holdout.jsonl" not in candidate_read_names
    assert {Path(path).name for path in source_audit["evaluation_only_read_files"]} == {
        "canonical_interactions.valid.jsonl",
        "canonical_interactions.test.jsonl",
    }
    assert metrics["evaluation_only"]["contract"] == "valid/test are read only after candidate generation for evaluation metrics"
    assert set(ablation) == {
        "schema_version",
        "candidate_hit_users_delta",
        "recall_at_pool_delta",
        "empty_candidate_rate_delta",
        "fallback_rate_delta",
        "overlap_delta",
        "latency_p50_delta",
        "latency_p95_delta",
        "source_marginal_hit",
        "swing_marginal_hit",
        "session_transition_marginal_hit",
    }
    assert session_audit["transition_definition"] == "adjacent item pairs within each bounded train sequence"
    assert session_audit["candidate_generation_uses_holdout"] is False
    assert sidecar["no_unbounded_global_pair_counter"] is True
    assert sidecar["caps"]["max_pairs"] == 50


def test_phase3_swing_sequence_session_observation_rejects_unbounded_pair_cap(tmp_path: Path) -> None:
    phase0_dir, phase1_dir, phase2_dir, output_dir = make_fixture(tmp_path)

    with pytest.raises(ValueError, match="max_pairs must be <= 200000"):
        run_phase3_swing_sequence_session_observation(
            phase0_dir=phase0_dir,
            phase1_dir=phase1_dir,
            phase2_dir=phase2_dir,
            output_dir=output_dir,
            min_free_bytes=0,
            enforce_venv=False,
            max_pairs=200001,
        )


def test_phase3_swing_sequence_session_observation_requires_phase2_evidence(tmp_path: Path) -> None:
    phase0_dir, phase1_dir, phase2_dir, output_dir = make_fixture(tmp_path)
    write_json(phase2_dir / "manifest.json", {"status": "unexpected"})

    with pytest.raises(RuntimeError, match="Phase 2 evidence must be complete"):
        run_phase3_swing_sequence_session_observation(
            phase0_dir=phase0_dir,
            phase1_dir=phase1_dir,
            phase2_dir=phase2_dir,
            output_dir=output_dir,
            min_free_bytes=0,
            enforce_venv=False,
        )
