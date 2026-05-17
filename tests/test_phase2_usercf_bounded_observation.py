from __future__ import annotations

import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

from scripts.run_phase2_usercf_bounded_observation import run_phase2_usercf_bounded_observation


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


def make_fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    clean_dir = tmp_path / "amazon_2023_recall_clean_full"
    baseline_dir = tmp_path / "lightweight_representative_e2e"
    phase0_dir = tmp_path / "phase0_contract_precheck"
    phase1_dir = tmp_path / "itemcf_covisit_representative_merge_eval"

    write_jsonl(
        clean_dir / "user_sequences.train.jsonl",
        [
            {"user_id": "u1", "recent_positive_item_sequence": ["a", "b"], "recent_item_sequence": ["a", "b"]},
            {"user_id": "u2", "recent_positive_item_sequence": ["a", "cf_hit"], "recent_item_sequence": ["a", "cf_hit"]},
        ],
    )
    write_jsonl(clean_dir / "canonical_interactions.valid.jsonl", [{"user_id": "u1", "parent_asin": "cf_hit", "label_binary": 1}])
    write_jsonl(clean_dir / "canonical_interactions.test.jsonl", [{"user_id": "u2", "parent_asin": "base_hit", "label_binary": 1}])
    write_jsonl(clean_dir / "holdout.jsonl", [{"must_not_be_read": True}])

    baseline_rows = [
        {"user_id": "u1", "rank": 1, "item_id": "base_miss", "sources": ["popular"], "source_scores": {"popular": 1.0}},
        {"user_id": "u2", "rank": 1, "item_id": "base_hit", "sources": ["semantic"], "source_scores": {"semantic": 2.0}},
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

    write_json(phase0_dir / "manifest.json", {"status": "PASS"})
    write_json(
        phase0_dir / "resolved_inputs.json",
        {
            "full_clean_dir": {"path": str(clean_dir)},
            "lightweight_representative_baseline": {"path": str(baseline_dir)},
        },
    )
    return phase0_dir, phase1_dir, tmp_path / "usercf_bounded_observation"


def test_usercf_bounded_observation_writes_contract_artifacts(tmp_path: Path) -> None:
    phase0_dir, phase1_dir, output_dir = make_fixture(tmp_path)

    manifest = run_phase2_usercf_bounded_observation(
        phase0_dir=phase0_dir,
        phase1_dir=phase1_dir,
        output_dir=output_dir,
        min_free_bytes=0,
        enforce_venv=False,
        max_users=2,
        max_items_per_user=3,
        max_item_users=2,
        similar_users=1,
        usercf_per_user=3,
    )

    source_audit = read_json(output_dir / "source_audit.json")
    metrics = read_json(output_dir / "metrics.json")
    ablation = read_json(output_dir / "ablation_vs_lightweight_baseline.json")
    overlap = read_json(output_dir / "source_overlap_with_itemcf.json")
    assert manifest["status"] in {"promotion_candidate", "rejected", "blocked", "deferred"}
    assert manifest["no_dense_user_user_matrix"] is True
    assert manifest["required_artifacts"].keys() == {
        "manifest",
        "source_audit",
        "metrics",
        "ablation_vs_lightweight_baseline",
        "source_overlap_with_itemcf",
        "candidates",
    }
    assert source_audit["train_only_candidate_generation"] is True
    assert source_audit["no_dense_user_user_matrix"] is True
    assert source_audit["candidate_generation_uses_holdout"] is False
    assert source_audit["disabled_outputs"]["dense_user_user_matrix"] is True
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
    }
    assert overlap["schema_version"] == "phase2_usercf_bounded_observation_v1"
    assert "jaccard" in overlap


def test_usercf_bounded_observation_rejects_unbounded_user_cap(tmp_path: Path) -> None:
    phase0_dir, phase1_dir, output_dir = make_fixture(tmp_path)

    with pytest.raises(ValueError, match="max_users must be <= 1000"):
        run_phase2_usercf_bounded_observation(
            phase0_dir=phase0_dir,
            phase1_dir=phase1_dir,
            output_dir=output_dir,
            min_free_bytes=0,
            enforce_venv=False,
            max_users=1001,
        )


def test_usercf_bounded_observation_requires_phase1_evidence(tmp_path: Path) -> None:
    phase0_dir, phase1_dir, output_dir = make_fixture(tmp_path)
    write_json(phase1_dir / "manifest.json", {"status": "BLOCKED"})

    with pytest.raises(RuntimeError, match="Phase 1 evidence must be complete"):
        run_phase2_usercf_bounded_observation(
            phase0_dir=phase0_dir,
            phase1_dir=phase1_dir,
            output_dir=output_dir,
            min_free_bytes=0,
            enforce_venv=False,
        )
