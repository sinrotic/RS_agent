from __future__ import annotations

import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

from rs_lab.experiments.recall.run_phase1_itemcf_covisit_representative_merge_eval import run_phase1_itemcf_covisit_representative_merge_eval


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


def make_fixture(tmp_path: Path) -> tuple[Path, Path]:
    clean_dir = tmp_path / "amazon_2023_recall_clean_full"
    baseline_dir = tmp_path / "lightweight_representative_e2e"
    sidecar_dir = tmp_path / "bounded_itemcf_covisit_sidecar_representative"
    phase0_dir = tmp_path / "phase0_contract_precheck"

    write_jsonl(
        clean_dir / "user_sequences.train.jsonl",
        [
            {"user_id": "u1", "recent_positive_item_sequence": ["seed1"], "recent_item_sequence": ["seed1"]},
            {"user_id": "u2", "recent_positive_item_sequence": ["seed2"], "recent_item_sequence": ["seed2"]},
        ],
    )
    write_jsonl(clean_dir / "canonical_interactions.valid.jsonl", [{"user_id": "u1", "parent_asin": "cf_hit", "label_binary": 1}])
    write_jsonl(clean_dir / "canonical_interactions.test.jsonl", [{"user_id": "u2", "parent_asin": "base_hit", "label_binary": 1}])
    write_jsonl(clean_dir / "holdout.jsonl", [{"must_not_be_read": True}])

    write_jsonl(
        baseline_dir / "candidates.jsonl",
        [
            {"user_id": "u1", "rank": 1, "item_id": "base_miss", "sources": ["popular"], "source_scores": {"popular": 1.0}},
            {"user_id": "u2", "rank": 1, "item_id": "base_hit", "sources": ["semantic"], "source_scores": {"semantic": 2.0}},
        ],
    )
    write_json(baseline_dir / "manifest.json", {"enabled_sources": ["popular", "category", "semantic"]})
    write_json(baseline_dir / "source_audit.json", {"train_only": True})

    write_jsonl(sidecar_dir / "neighbors_shard_00000.jsonl", [{"src_item": "seed1", "neighbors": [{"item_id": "cf_hit", "score": 3.0, "cooc_cnt": 1}]}])
    write_json(sidecar_dir / "manifest.json", {"schema_version": "bounded_itemcf_covisit_sidecar_v1"})
    write_json(sidecar_dir / "source_audit.json", {"train_only": True})

    write_json(phase0_dir / "manifest.json", {"status": "PASS"})
    write_json(
        phase0_dir / "resolved_inputs.json",
        {
            "full_clean_dir": {"path": str(clean_dir)},
            "lightweight_representative_baseline": {"path": str(baseline_dir)},
            "bounded_itemcf_covisit_sidecar": {"path": str(sidecar_dir)},
        },
    )
    return phase0_dir, tmp_path / "itemcf_covisit_representative_merge_eval"


def test_phase1_itemcf_covisit_writes_required_contract_artifacts(tmp_path: Path) -> None:
    phase0_dir, output_dir = make_fixture(tmp_path)

    manifest = run_phase1_itemcf_covisit_representative_merge_eval(
        phase0_dir=phase0_dir,
        output_dir=output_dir,
        min_free_bytes=0,
        enforce_venv=False,
        candidate_pool_size=10,
        itemcf_per_user=5,
    )

    source_audit = read_json(output_dir / "source_audit.json")
    metrics = read_json(output_dir / "metrics.json")
    ablation = read_json(output_dir / "ablation_vs_lightweight_baseline.json")
    assert manifest["status"] == "EXECUTED_PASS_OBSERVATION_ONLY"
    assert manifest["phase0_status"] == "PASS"
    assert set(manifest["required_artifacts"]) == {
        "manifest",
        "source_audit",
        "metrics",
        "ablation_vs_lightweight_baseline",
        "candidates",
    }
    assert manifest["disabled_outputs"] == {"pool500": True, "pool1000": True, "ranking_default_input": True}
    assert not (output_dir / "pool500.jsonl").exists()
    assert not (output_dir / "pool1000.jsonl").exists()
    assert source_audit["train_only_candidate_generation"] is True
    assert source_audit["candidate_generation_uses_holdout"] is False
    candidate_read_names = [Path(path).name for path in source_audit["candidate_generation_read_files"]]
    assert "canonical_interactions.valid.jsonl" not in candidate_read_names
    assert "canonical_interactions.test.jsonl" not in candidate_read_names
    assert "holdout.jsonl" not in candidate_read_names
    assert {Path(path).name for path in source_audit["evaluation_only_read_files"]} == {
        "canonical_interactions.valid.jsonl",
        "canonical_interactions.test.jsonl",
    }
    assert metrics["evaluation_only"]["contract"] == "valid/test are read only after candidate generation for evaluation metrics"
    assert ablation["candidate_hit_users_delta"] == 1
    assert ablation["recall_at_pool_delta"] > 0
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


def test_phase1_requires_phase0_pass(tmp_path: Path) -> None:
    phase0_dir, output_dir = make_fixture(tmp_path)
    write_json(phase0_dir / "manifest.json", {"status": "INVALID_SCOPE_DRIFT"})

    with pytest.raises(RuntimeError, match="Phase 0 must PASS"):
        run_phase1_itemcf_covisit_representative_merge_eval(
            phase0_dir=phase0_dir,
            output_dir=output_dir,
            min_free_bytes=0,
            enforce_venv=False,
        )


def test_phase1_rejects_pool_output_dir(tmp_path: Path) -> None:
    phase0_dir, _ = make_fixture(tmp_path)

    with pytest.raises(ValueError, match="pool500/pool1000"):
        run_phase1_itemcf_covisit_representative_merge_eval(
            phase0_dir=phase0_dir,
            output_dir=tmp_path / "pool500",
            min_free_bytes=0,
            enforce_venv=False,
        )
