from __future__ import annotations

import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

from rs_lab.experiments.recall.run_phase0_contract_precheck import run_phase0_contract_precheck


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def write_text(path: Path, text: str = "x\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def make_inputs(tmp_path: Path) -> dict[str, Path]:
    clean_dir = tmp_path / "amazon_2023_recall_clean_full"
    for name in [
        "user_sequences.train.jsonl",
        "canonical_interactions.train.jsonl",
        "canonical_items.jsonl",
    ]:
        write_text(clean_dir / name)
    write_json(clean_dir / "manifest.json", {"schema_version": "clean_v1"})
    write_json(clean_dir / "stats.json", {"rows": 1})
    for name in [
        "canonical_interactions.valid.jsonl",
        "canonical_interactions.test.jsonl",
        "user_sequences.valid.jsonl",
        "user_sequences.test.jsonl",
        "holdout.jsonl",
    ]:
        write_text(clean_dir / name)

    views_dir = tmp_path / "amazon_2023_recall_views_full_lightweight"
    for name in [
        "popular_recall.jsonl",
        "category_recall_items.jsonl",
        "category_top_items.jsonl",
        "semantic_recall_inputs.jsonl",
        "semantic_inverted_index.jsonl",
    ]:
        write_text(views_dir / name)
    write_json(views_dir / "manifest.json", {"mode": "lightweight_full_safe"})
    write_json(views_dir / "stats.json", {"rows": 1})

    baseline_dir = tmp_path / "lightweight_representative_e2e"
    write_json(baseline_dir / "manifest.json", {"enabled_sources": ["popular", "category", "semantic"]})
    write_json(baseline_dir / "source_audit.json", {"train_only": True})
    write_text(baseline_dir / "candidates.jsonl")

    sidecar_dir = tmp_path / "bounded_itemcf_covisit_sidecar_representative"
    write_json(sidecar_dir / "manifest.json", {"schema_version": "bounded_itemcf_covisit_sidecar_v1"})
    write_json(sidecar_dir / "source_audit.json", {"train_only": True})

    graph_config = tmp_path / "configs" / "graph.json"
    two_tower_config = tmp_path / "configs" / "two_tower.json"
    ranking_config = tmp_path / "configs" / "ranking_pool200.json"
    write_json(graph_config, {"clean_dir": str(clean_dir), "views_dir": str(views_dir)})
    write_json(two_tower_config, {"clean_dir": str(clean_dir), "views_dir": str(views_dir)})
    write_json(ranking_config, {"candidate_pool_size": 200})

    return {
        "clean_dir": clean_dir,
        "views_dir": views_dir,
        "baseline_dir": baseline_dir,
        "sidecar_dir": sidecar_dir,
        "graph_config": graph_config,
        "two_tower_config": two_tower_config,
        "ranking_config": ranking_config,
    }


def run_for_test(paths: dict[str, Path], output_dir: Path) -> dict:
    return run_phase0_contract_precheck(
        clean_dir=paths["clean_dir"],
        full_lightweight_views_dir=paths["views_dir"],
        lightweight_representative_baseline_dir=paths["baseline_dir"],
        bounded_itemcf_covisit_sidecar_dir=paths["sidecar_dir"],
        graph_config_file=paths["graph_config"],
        two_tower_config_file=paths["two_tower_config"],
        ranking_pool200_config_file=paths["ranking_config"],
        output_dir=output_dir,
        min_free_bytes=0,
        enforce_venv=False,
    )


def test_phase0_contract_precheck_writes_manifest_audit_and_resolved_inputs(tmp_path: Path) -> None:
    paths = make_inputs(tmp_path)

    manifest = run_for_test(paths, tmp_path / "out")

    persisted_manifest = read_json(tmp_path / "out" / "manifest.json")
    source_audit = read_json(tmp_path / "out" / "source_audit.json")
    resolved_inputs = read_json(tmp_path / "out" / "resolved_inputs.json")
    assert persisted_manifest == manifest
    assert manifest["status"] == "PASS"
    assert manifest["train_only"] is True
    assert manifest["recall_promotion_gate"]["does_not_promote_ranking_input"] is True
    assert manifest["ranking_frozen_pool200_gate"]["separate_from_recall_promotion_gate"] is True
    assert manifest["ranking_frozen_pool200_gate"]["pool500_pool1000_cannot_replace_pool200"] is True
    assert source_audit["train_only"] is True
    assert source_audit["no_10k_source"] is True
    assert source_audit["holdout_contract"]["candidate_generation_uses_holdout"] is False
    assert source_audit["holdout_contract"]["status"] == "PASS"
    assert set(source_audit["holdout_contract"]["forbidden_source_files"]) == {
        "canonical_interactions.valid.jsonl",
        "canonical_interactions.test.jsonl",
        "user_sequences.valid.jsonl",
        "user_sequences.test.jsonl",
        "holdout.jsonl",
    }
    assert all("valid" not in Path(path).name and "test" not in Path(path).name and "holdout" not in Path(path).name for path in source_audit["read_files"])
    assert resolved_inputs["schema_version"] == "phase0_contract_precheck_v1"
    assert resolved_inputs["status"] == "PASS"
    assert resolved_inputs["full_clean_dir"]["status"] == "READY"
    assert resolved_inputs["full_lightweight_views_dir"]["manifest_mode"] == "lightweight_full_safe"
    assert resolved_inputs["lightweight_representative_baseline"]["status"] == "READY"
    assert resolved_inputs["bounded_itemcf_covisit_sidecar"]["status"] == "READY"
    assert resolved_inputs["phase2_usercf_inputs"]["status"] == "READY"
    assert resolved_inputs["phase3_swing_inputs"]["status"] == "READY"
    assert resolved_inputs["phase3_sequence_inputs"]["status"] == "READY"
    assert resolved_inputs["phase4_graph_config_status"] == "READY"
    assert resolved_inputs["phase4_graph_config_hash"]
    assert resolved_inputs["phase5_two_tower_config_status"] == "READY"
    assert resolved_inputs["phase5_two_tower_config_hash"]
    assert resolved_inputs["phase5_pool_readiness_inputs"]["status"] == "READY"
    assert resolved_inputs["phase5_pool_readiness_inputs"]["pool500_status"] == "READINESS_ONLY_NOT_RANKING_INPUT"
    assert resolved_inputs["phase5_pool_readiness_inputs"]["pool1000_status"] == "READINESS_ONLY_NOT_RANKING_INPUT"


def test_phase0_contract_precheck_rejects_10k_primary_paths(tmp_path: Path) -> None:
    paths = make_inputs(tmp_path)
    paths["clean_dir"] = tmp_path / "amazon_2023_recall_clean_10000"
    paths["clean_dir"].mkdir()

    manifest = run_for_test(paths, tmp_path / "out")

    assert manifest["status"] == "INVALID_SCOPE_DRIFT"
    assert "forbidden 10k path" in manifest["failure_reason"]


def test_phase0_contract_precheck_marks_missing_inputs_blocked(tmp_path: Path) -> None:
    paths = make_inputs(tmp_path)
    (paths["clean_dir"] / "canonical_items.jsonl").unlink()

    manifest = run_for_test(paths, tmp_path / "out")
    resolved_inputs = read_json(tmp_path / "out" / "resolved_inputs.json")

    assert manifest["status"] == "BLOCKED_MISSING_ARTIFACT"
    assert resolved_inputs["full_clean_dir"]["files"]["canonical_items"]["status"] == "BLOCKED_MISSING_ARTIFACT"
    assert resolved_inputs["phase4_mf_inputs"]["status"] == "BLOCKED_MISSING_ARTIFACT"


def test_phase0_contract_precheck_marks_config_content_10k_scope_drift(tmp_path: Path) -> None:
    paths = make_inputs(tmp_path)
    write_json(
        paths["two_tower_config"],
        {
            "clean_dir": "data/processed/amazon_2023_recall_clean_10000",
            "views_dir": "data/processed/amazon_2023_recall_views_10000",
        },
    )

    manifest = run_for_test(paths, tmp_path / "out")
    resolved_inputs = read_json(tmp_path / "out" / "resolved_inputs.json")

    assert manifest["status"] == "INVALID_SCOPE_DRIFT"
    assert resolved_inputs["phase5_two_tower_config_status"] == "INVALID_SCOPE_DRIFT"
    assert "config references forbidden 10k paths" in manifest["failure_reason"]


def test_phase0_contract_precheck_rejects_config_directory(tmp_path: Path) -> None:
    paths = make_inputs(tmp_path)
    paths["graph_config"] = paths["graph_config"].parent

    manifest = run_for_test(paths, tmp_path / "out")
    resolved_inputs = read_json(tmp_path / "out" / "resolved_inputs.json")

    assert manifest["status"] == "INVALID_SCOPE_DRIFT"
    assert resolved_inputs["phase4_graph_config_status"] == "INVALID_SCOPE_DRIFT"
    assert "must be a concrete file" in manifest["failure_reason"]
