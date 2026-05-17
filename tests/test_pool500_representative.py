from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

pytestmark = pytest.mark.unit

from scripts.experiments.recall import run_pool500_representative_p0_p2 as p0_p2
from scripts.experiments.recall.run_pool500_representative_p3_p4_audit import run_pool500_representative_p3_p4_audit
from scripts.experiments.recall.run_pool500_representative_p5_method_observations import run_pool500_representative_p5_method_observations
from scripts.experiments.recall.run_pool500_representative_p6_promote_stop_gate import run_pool500_representative_p6_promote_stop_gate


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def make_clean_and_views(tmp_path: Path) -> tuple[Path, Path]:
    clean_dir = tmp_path / "clean_full"
    views_dir = tmp_path / "views_full_lightweight"
    write_jsonl(
        clean_dir / "user_sequences.train.jsonl",
        [
            {"user_id": "u1", "recent_item_sequence": ["seed1"]},
            {"user_id": "u2", "recent_item_sequence": ["seed2"]},
        ],
    )
    write_jsonl(
        clean_dir / "canonical_interactions.valid.jsonl",
        [
            {"user_id": "u1", "parent_asin": "hit_shared", "label_binary": 1},
            {"user_id": "u2", "parent_asin": "hit_pool500", "label_binary": 1},
        ],
    )
    write_jsonl(clean_dir / "canonical_interactions.test.jsonl", [])
    write_json(views_dir / "manifest.json", {"status": "PASS"})
    return clean_dir, views_dir


def candidate_rows(pool_size: int) -> list[dict[str, Any]]:
    if pool_size == 200:
        return [
            {"user_id": "u1", "item_id": "hit_shared", "rank": 1, "sources": ["popular"], "source_scores": {"popular": 1.0}},
            {"user_id": "u2", "item_id": "miss_pool200", "rank": 1, "sources": ["category"], "source_scores": {"category": 1.0}},
        ]
    return [
        {"user_id": "u1", "item_id": "hit_shared", "rank": 1, "sources": ["popular"], "source_scores": {"popular": 1.0}},
        {"user_id": "u2", "item_id": "miss_pool200", "rank": 1, "sources": ["category"], "source_scores": {"category": 1.0}},
        {"user_id": "u2", "item_id": "hit_pool500", "rank": 201, "sources": ["semantic"], "source_scores": {"semantic": 1.0}},
    ]


def fake_representative_e2e(*, output_dir: Path, candidate_pool_size: int, **_: Any) -> dict[str, Any]:
    write_jsonl(output_dir / "candidates.jsonl", candidate_rows(candidate_pool_size))
    write_json(
        output_dir / "source_audit.json",
        {
            "status": "PASS",
            "source_candidate_rows": {"popular": 1, "category": 1, "semantic": 1},
            "source_user_coverage": {"popular": 1, "category": 1, "semantic": 1},
            "source_item_coverage": {"popular": 1, "category": 1, "semantic": 1},
        },
    )
    return {
        "output_dir": str(output_dir),
        "config": {"candidate_pool_size": candidate_pool_size},
        "outputs": {"candidates": str(output_dir / "candidates.jsonl")},
    }


def run_p0_p2_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path, Path]:
    clean_dir, views_dir = make_clean_and_views(tmp_path)
    output_dir = tmp_path / "p0_p2"
    monkeypatch.setattr(p0_p2, "run_representative_e2e", fake_representative_e2e)

    manifest = p0_p2.run_pool500_representative_p0_p2(
        clean_dir=clean_dir,
        views_dir=views_dir,
        output_dir=output_dir,
        limit_users=2,
        min_free_bytes=0,
        enforce_venv=False,
    )

    assert manifest["representative_user_count"] == 2
    assert manifest["pool200_candidate_pool_size"] == 200
    assert manifest["pool500_candidate_pool_size"] == 500
    return clean_dir, views_dir, output_dir


def run_p3_p4_fixture(tmp_path: Path, p0_dir: Path, clean_dir: Path) -> Path:
    output_dir = tmp_path / "p3_p4"
    manifest = run_pool500_representative_p3_p4_audit(
        input_dir=p0_dir,
        output_dir=output_dir,
        clean_dir=clean_dir,
        min_free_bytes=0,
        enforce_venv=False,
    )
    assert manifest["status"] == "PASS"
    return output_dir


def make_prior_method_dir(tmp_path: Path) -> Path:
    prior_dir = tmp_path / "prior_methods"
    write_json(prior_dir / "graph_mf_contract_validation" / "manifest.json", {"status": "PASS", "no_model_training_executed": True})
    write_json(prior_dir / "two_tower_pool_readiness" / "manifest.json", {"status": "PASS", "no_two_tower_training_executed": True})
    return prior_dir


def run_p5_fixture(tmp_path: Path, p0_dir: Path, p3_dir: Path) -> Path:
    output_dir = tmp_path / "p5"
    manifest = run_pool500_representative_p5_method_observations(
        p0_p2_dir=p0_dir,
        p3_p4_dir=p3_dir,
        prior_method_dir=make_prior_method_dir(tmp_path),
        output_dir=output_dir,
        min_free_bytes=0,
        enforce_venv=False,
    )
    assert manifest["status"] == "PASS"
    return output_dir


def test_p0_p2_enforces_same_scope_sizes_and_disabled_outputs(tmp_path, monkeypatch):
    _, _, output_dir = run_p0_p2_fixture(tmp_path, monkeypatch)

    manifest = read_json(output_dir / "manifest.json")
    source_audit = read_json(output_dir / "source_audit.json")
    metrics = read_json(output_dir / "metrics.json")

    assert manifest["ranking_isolation"]["pool500_as_ranking_input"] is False
    assert manifest["ranking_isolation"]["frozen_pool200_ranking_baseline_replaced"] is False
    assert manifest["disabled_outputs"] == {
        "pool1000": True,
        "two_tower_training": True,
        "graph_training": True,
        "mf_training": True,
        "ranking": True,
    }
    assert metrics["train_only_candidate_generation"] is True
    assert source_audit["candidate_generation_uses_holdout"] is False
    candidate_generation_file_names = {Path(path).name for path in source_audit["candidate_generation_read_files"]}
    assert candidate_generation_file_names.isdisjoint(
        {
            "canonical_interactions.valid.jsonl",
            "canonical_interactions.test.jsonl",
            "user_sequences.valid.jsonl",
            "user_sequences.test.jsonl",
            "holdout.jsonl",
        }
    )

    with pytest.raises(ValueError, match="same-scope baseline must remain pool200"):
        p0_p2.run_pool500_representative_p0_p2(
            clean_dir=tmp_path / "unused_clean",
            views_dir=tmp_path / "unused_views",
            output_dir=tmp_path / "bad_pool200",
            pool200_size=201,
            min_free_bytes=0,
            enforce_venv=False,
        )
    with pytest.raises(ValueError, match="experiment must remain pool500"):
        p0_p2.run_pool500_representative_p0_p2(
            clean_dir=tmp_path / "unused_clean",
            views_dir=tmp_path / "unused_views",
            output_dir=tmp_path / "bad_pool500",
            pool500_size=1000,
            min_free_bytes=0,
            enforce_venv=False,
        )


def test_p3_p4_comparison_and_audits_pass_without_ranking_replacement(tmp_path, monkeypatch):
    clean_dir, _, p0_dir = run_p0_p2_fixture(tmp_path, monkeypatch)
    p3_dir = run_p3_p4_fixture(tmp_path, p0_dir, clean_dir)

    comparison = read_json(p3_dir / "pool500_vs_pool200_same_scope_comparison.json")
    leakage_audit = read_json(p3_dir / "leakage_audit.json")
    resource_audit = read_json(p3_dir / "resource_audit.json")
    ranking_audit = read_json(p3_dir / "ranking_isolation_audit.json")

    assert comparison["same_representative_sample"] is True
    assert comparison["exclusive_hit_users_201_500"] == 1
    assert comparison["exclusive_hit_user_ids_201_500"] == ["u2"]
    assert comparison["source_attribution_for_exclusive_hits"] == {"semantic": 1}
    assert leakage_audit["status"] == "PASS"
    assert leakage_audit["candidate_generation_uses_valid_test_holdout"] is False
    assert resource_audit["status"] == "PASS"
    assert ranking_audit["status"] == "PASS"
    assert ranking_audit["pool500_as_ranking_input"] is False


def test_p3_p4_leakage_audit_fails_on_valid_test_holdout_generation_inputs(tmp_path, monkeypatch):
    clean_dir, _, p0_dir = run_p0_p2_fixture(tmp_path, monkeypatch)
    source_audit = read_json(p0_dir / "source_audit.json")
    source_audit["candidate_generation_read_files"].append(str(clean_dir / "canonical_interactions.valid.jsonl"))
    write_json(p0_dir / "source_audit.json", source_audit)

    output_dir = tmp_path / "p3_p4_leaky"
    manifest = run_pool500_representative_p3_p4_audit(
        input_dir=p0_dir,
        output_dir=output_dir,
        clean_dir=clean_dir,
        min_free_bytes=0,
        enforce_venv=False,
    )

    leakage_audit = read_json(output_dir / "leakage_audit.json")
    assert manifest["status"] == "FAIL"
    assert leakage_audit["status"] == "FAIL"
    assert leakage_audit["candidate_generation_uses_valid_test_holdout"] is True


def test_p5_p6_gate_pass_preserves_stop_boundaries(tmp_path, monkeypatch):
    clean_dir, _, p0_dir = run_p0_p2_fixture(tmp_path, monkeypatch)
    p3_dir = run_p3_p4_fixture(tmp_path, p0_dir, clean_dir)
    p5_dir = run_p5_fixture(tmp_path, p0_dir, p3_dir)
    p6_dir = tmp_path / "p6"

    manifest = run_pool500_representative_p6_promote_stop_gate(
        p0_p2_dir=p0_dir,
        p3_p4_dir=p3_dir,
        p5_dir=p5_dir,
        output_dir=p6_dir,
        min_free_bytes=0,
        enforce_venv=False,
    )
    gate = read_json(p6_dir / "promote_stop_gate.json")
    p5_source_audit = read_json(p5_dir / "source_audit.json")

    assert manifest["status"] == "PASS"
    assert manifest["decision"] == "PASS"
    assert gate["p7_allowed"] is True
    assert gate["p6_execution_boundary"] == {
        "no_candidate_generation_executed": True,
        "no_full_pool500_executed": True,
        "no_ranking_executed": True,
        "no_model_training_executed": True,
        "read_only_inputs": gate["p6_execution_boundary"]["read_only_inputs"],
    }
    assert p5_source_audit["disabled_outputs"]["pool1000"] is True
    assert p5_source_audit["disabled_outputs"]["two_tower_training"] is True
    assert p5_source_audit["disabled_outputs"]["graph_training"] is True
    assert p5_source_audit["disabled_outputs"]["mf_training"] is True
    assert p5_source_audit["ranking_isolation"]["pool500_as_ranking_input"] is False


def test_p6_gate_stops_when_pool500_adds_no_exclusive_201_500_value(tmp_path, monkeypatch):
    clean_dir, _, p0_dir = run_p0_p2_fixture(tmp_path, monkeypatch)
    p3_dir = run_p3_p4_fixture(tmp_path, p0_dir, clean_dir)
    p5_dir = run_p5_fixture(tmp_path, p0_dir, p3_dir)
    comparison_path = p3_dir / "pool500_vs_pool200_same_scope_comparison.json"
    comparison = read_json(comparison_path)
    comparison["exclusive_hit_users_201_500"] = 0
    comparison["exclusive_hit_user_ids_201_500"] = []
    comparison["exclusive_hit_details_201_500"] = []
    comparison["source_attribution_for_exclusive_hits"] = {}
    comparison["pool500_adds_recall_side_value"] = False
    comparison["delta"] = {"candidate_hit_users": 0, "recall_at_pool": 0.0, "candidate_row_count": 1}
    write_json(comparison_path, comparison)
    method_contribution_path = p5_dir / "method_contribution_201_500.json"
    method_contribution = read_json(method_contribution_path)
    method_contribution["exclusive_hit_users_201_500"] = 0
    method_contribution["exclusive_hit_details_201_500"] = []
    method_contribution["source_attribution_for_exclusive_hits"] = {}
    write_json(method_contribution_path, method_contribution)

    manifest = run_pool500_representative_p6_promote_stop_gate(
        p0_p2_dir=p0_dir,
        p3_p4_dir=p3_dir,
        p5_dir=p5_dir,
        output_dir=tmp_path / "p6_stop",
        min_free_bytes=0,
        enforce_venv=False,
    )
    gate = read_json(tmp_path / "p6_stop" / "promote_stop_gate.json")

    assert manifest["status"] == "FAIL"
    assert manifest["decision"] == "STOP"
    assert gate["p7_allowed"] is False
    assert gate["rule_results"]["exclusive_hit_users_201_500_positive"]["pass"] is False
