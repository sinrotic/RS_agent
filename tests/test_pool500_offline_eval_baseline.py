from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from rs_core.common.io import read_json
from rs_core.workflow.full_data_pool500_route_gate import canonical_user_set_hash
from rs_lab.experiments.recall.run_itemcf_strong_augcf_route_gate_matrix import run_itemcf_strong_augcf_route_gate_matrix
from rs_lab.experiments.recall.run_pool500_offline_eval_baseline import (
    _evaluate_candidates,
    run_pool500_offline_eval_baseline,
    run_raw_two_tower_eval,
    run_two_tower_ablation,
)

pytestmark = pytest.mark.unit


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")


def _write_fixed_eval_artifact(tmp_path: Path) -> tuple[Path, Path]:
    output_dir = tmp_path / "eval_users"
    users = [
        {"user_id": "u_hot", "segment": "hot", "label_count": 2},
        {"user_id": "u_warm", "segment": "warm", "label_count": 1},
        {"user_id": "u_cold", "segment": "cold-ish", "label_count": 1},
    ]
    users_path = output_dir / "users.jsonl"
    labels_path = output_dir / "labels.valid.jsonl"
    _write_jsonl(users_path, users)
    _write_jsonl(
        labels_path,
        [
            {"user_id": "u_hot", "parent_asin": "i_hit_hot", "label_binary": 1},
            {"user_id": "u_hot", "parent_asin": "i_miss_hot", "label_binary": 1},
            {"user_id": "u_warm", "parent_asin": "i_hit_warm", "label_binary": 1},
            {"user_id": "u_cold", "parent_asin": "i_miss_cold", "label_binary": 1},
            {"user_id": "u_warm", "parent_asin": "i_negative", "label_binary": 0},
        ],
    )
    user_ids = [user["user_id"] for user in users]
    manifest = {
        "schema_version": "pool500_offline_eval_users_v1",
        "created_at": "2026-05-23T00:00:00+00:00",
        "status": "PASS",
        "total_user_count": len(users),
        "requested_total_user_count": len(users),
        "segment_counts": {"hot": 1, "warm": 1, "cold-ish": 1},
        "source_manifest_paths": {"clean_manifest_path": str(tmp_path / "clean_manifest.json")},
        "source_data_paths": {"label_paths": [str(labels_path)]},
        "user_set_hash": canonical_user_set_hash(user_ids),
        "split_contract": {"history_source": "train_user_sequences_only", "label_source": "valid_or_test_positive_rows_only"},
        "leakage_policy": {"no_label_in_candidate_generation": True, "no_oracle_candidate_injection": True},
        "users": users,
    }
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    return manifest_path, users_path


def test_offline_eval_baseline_writes_metrics_and_audits(tmp_path: Path) -> None:
    eval_manifest_path, users_path = _write_fixed_eval_artifact(tmp_path)
    output_dir = tmp_path / "baseline"

    def fake_candidate_runner(**kwargs: Any) -> dict[str, Any]:
        assert "recall_profile" not in kwargs
        target_manifest = read_json(kwargs["target_user_manifest_path"])
        assert target_manifest["target_user_ids"] == ["u_hot", "u_warm", "u_cold"]
        assert target_manifest["candidate_generation_allowed"] is False
        _write_jsonl(
            Path(kwargs["output_dir"]) / "pool500_candidates.jsonl",
            [
                {"user_id": "u_hot", "item_id": "i_hit_hot", "rank": 1, "score": 1.0, "source": "semantic_title_category_expansion", "sources": ["semantic_title_category_expansion", "category"]},
                {"user_id": "u_hot", "item_id": "i_other_hot", "rank": 2, "score": 0.5, "source": "popular", "sources": ["popular"]},
                {"user_id": "u_warm", "item_id": "i_other_warm", "rank": 1, "score": 0.4, "source": "category", "sources": ["category"]},
                {"user_id": "u_warm", "item_id": "i_hit_warm", "rank": 2, "score": 0.3, "source": "usercf_recall", "sources": ["usercf_recall"]},
                {"user_id": "u_cold", "item_id": "i_other_cold", "rank": 1, "score": 0.2, "source": "popular", "sources": ["popular", "category"]},
            ],
        )
        return {"schema_version": "fake_generation_v1", "mode": "diagnostic_limited", "status": "PASS", "decision": "PASS"}

    baseline_manifest = run_pool500_offline_eval_baseline(
        eval_manifest_path=eval_manifest_path,
        eval_users_path=users_path,
        output_dir=output_dir,
        overwrite=True,
        enforce_venv=False,
        candidate_runner=fake_candidate_runner,
    )

    metrics = read_json(output_dir / "metrics.json")
    segment_metrics = read_json(output_dir / "segment_metrics.json")
    source_audit = read_json(output_dir / "source_audit.json")
    persisted_manifest = read_json(output_dir / "baseline_manifest.json")
    expected_hash = canonical_user_set_hash(["u_hot", "u_warm", "u_cold"])

    assert baseline_manifest == persisted_manifest
    assert persisted_manifest["eval_user_set_hash"] == expected_hash
    assert persisted_manifest["eval_manifest_user_set_hash"] == expected_hash
    assert persisted_manifest["no_oracle_label_injection"] is True
    assert persisted_manifest["metric_ks"] == [20, 50, 100, 500]
    assert {"Recall@500", "HitRate@500", "Recall@100", "Recall@50", "Recall@20", "HitRate@20"} <= set(metrics)
    assert metrics["Recall@500"] == pytest.approx(0.5)
    assert metrics["HitRate@500"] == pytest.approx(0.666667)
    assert set(segment_metrics) == {"hot", "warm", "cold-ish"}
    assert segment_metrics["hot"]["user_count"] == 1
    assert source_audit["underfilled_user_count"] == 3
    assert source_audit["duplicate_user_item_count"] == 0
    assert source_audit["popular_category_contribution_ratio"] == pytest.approx(0.6)


def test_offline_eval_baseline_passes_generic_source_manifest_override(tmp_path: Path) -> None:
    eval_manifest_path, users_path = _write_fixed_eval_artifact(tmp_path)
    output_dir = tmp_path / "baseline_override"
    source_manifest_path = tmp_path / "itemcf_strong_source_index_manifest.json"
    source_manifest_path.write_text(json.dumps({"source": "itemcf_strong"}, ensure_ascii=False), encoding="utf-8")

    def fake_candidate_runner(**kwargs: Any) -> dict[str, Any]:
        assert kwargs["source_manifest_paths"] == {"itemcf_strong": source_manifest_path}
        _write_jsonl(
            Path(kwargs["output_dir"]) / "pool500_candidates.jsonl",
            [
                {"user_id": "u_hot", "item_id": "i_hit_hot", "rank": 1, "source": "itemcf_strong", "sources": ["itemcf_strong"]},
                {"user_id": "u_warm", "item_id": "i_hit_warm", "rank": 1, "source": "popular", "sources": ["popular"]},
                {"user_id": "u_cold", "item_id": "i_other_cold", "rank": 1, "source": "category", "sources": ["category"]},
            ],
        )
        return {"schema_version": "fake_generation_v1", "status": "PASS"}

    manifest = run_pool500_offline_eval_baseline(
        eval_manifest_path=eval_manifest_path,
        eval_users_path=users_path,
        output_dir=output_dir,
        overwrite=True,
        enforce_venv=False,
        source_manifest_paths={"itemcf_strong": source_manifest_path},
        candidate_runner=fake_candidate_runner,
    )

    assert manifest["source_manifest_overrides"] == {"itemcf_strong": str(source_manifest_path)}
    assert manifest["no_oracle"] is True
    assert manifest["no_oracle_semantics"]["source_manifest_overrides_do_not_authorize_oracle_candidates"] is True


def _write_two_tower_source_manifest(tmp_path: Path) -> Path:
    path = tmp_path / "source_index_manifest.json"
    path.write_text(json.dumps({"schema_version": "two_tower_source_index_v1", "source": "two_tower"}, ensure_ascii=False), encoding="utf-8")
    return path


def test_raw_two_tower_eval_writes_hit_at_20_and_unique_hits(tmp_path: Path) -> None:
    eval_manifest_path, users_path = _write_fixed_eval_artifact(tmp_path)
    source_manifest_path = _write_two_tower_source_manifest(tmp_path)
    output_manifest_path = tmp_path / "raw_eval" / "manifest.json"

    def fake_candidate_runner(**kwargs: Any) -> dict[str, Any]:
        assert kwargs["source_manifest_paths"] == {"two_tower": source_manifest_path}
        _write_jsonl(
            Path(kwargs["output_dir"]) / "pool500_candidates.jsonl",
            [
                {"user_id": "u_hot", "item_id": "i_hit_hot", "rank": 20, "source": "two_tower", "sources": ["two_tower"]},
                {"user_id": "u_warm", "item_id": "i_hit_warm", "rank": 21, "source": "two_tower", "sources": ["two_tower"]},
                {"user_id": "u_cold", "item_id": "i_other_cold", "rank": 1, "source": "popular", "sources": ["popular"]},
            ],
        )
        return {"schema_version": "fake_generation_v1", "status": "PASS"}

    manifest = run_raw_two_tower_eval(
        source_index_manifest_path=source_manifest_path,
        output_manifest_path=output_manifest_path,
        eval_manifest_path=eval_manifest_path,
        eval_users_path=users_path,
        output_dir=tmp_path / "raw_generation",
        overwrite=True,
        enforce_venv=False,
        metric_ks=[20, 50, 100, 500],
        candidate_runner=fake_candidate_runner,
    )

    persisted = read_json(output_manifest_path)
    assert manifest == persisted
    assert persisted["metrics"]["hit_at_20"] == pytest.approx(1 / 3)
    assert persisted["metrics"]["hit_at_50"] == pytest.approx(2 / 3)
    assert persisted["raw_two_tower_unique_positive_hits"] == 2
    assert persisted["eval_scope"] == "evaluation_only"
    assert persisted["no_oracle_label_injection"] is True


def test_two_tower_ablation_reports_marginal_and_overlap_hits(tmp_path: Path) -> None:
    eval_manifest_path, users_path = _write_fixed_eval_artifact(tmp_path)
    source_manifest_path = _write_two_tower_source_manifest(tmp_path)
    output_ablation_path = tmp_path / "ablation" / "manifest.json"

    def fake_candidate_runner(**kwargs: Any) -> dict[str, Any]:
        two_tower_enabled = kwargs["source_manifest_paths"]["two_tower"].is_file()
        if two_tower_enabled:
            rows = [
                {"user_id": "u_hot", "item_id": "i_hit_hot", "rank": 1, "source": "two_tower", "sources": ["two_tower"]},
                {"user_id": "u_warm", "item_id": "i_hit_warm", "rank": 2, "source": "two_tower", "sources": ["two_tower"]},
                {"user_id": "u_cold", "item_id": "i_other_cold", "rank": 1, "source": "popular", "sources": ["popular"]},
            ]
        else:
            rows = [
                {"user_id": "u_hot", "item_id": "i_hit_hot", "rank": 1, "source": "popular", "sources": ["popular"]},
                {"user_id": "u_warm", "item_id": "i_other_warm", "rank": 1, "source": "popular", "sources": ["popular"]},
                {"user_id": "u_cold", "item_id": "i_other_cold", "rank": 1, "source": "popular", "sources": ["popular"]},
            ]
        _write_jsonl(Path(kwargs["output_dir"]) / "pool500_candidates.jsonl", rows)
        return {"schema_version": "fake_generation_v1", "status": "PASS"}

    manifest = run_two_tower_ablation(
        with_two_tower_source_manifest_path=source_manifest_path,
        output_ablation_path=output_ablation_path,
        eval_manifest_path=eval_manifest_path,
        eval_users_path=users_path,
        output_dir=tmp_path / "ablation_generation",
        overwrite=True,
        enforce_venv=False,
        metric_ks=[20, 50, 100, 500],
        candidate_runner=fake_candidate_runner,
    )

    persisted = read_json(output_ablation_path)
    assert manifest == persisted
    assert persisted["with_two_tower"]["hit_at_20"] == pytest.approx(2 / 3)
    assert persisted["without_two_tower"]["hit_at_20"] == pytest.approx(1 / 3)
    assert persisted["raw_two_tower_unique_positive_hits"] == 2
    assert persisted["marginal_unique_positive_hits"] == 1
    assert persisted["overlap_positive_hits"] == 1
    assert persisted["pool_budget_decision"] == "include"


def test_itemcf_strong_augcf_route_gate_matrix_runs_variants_and_keeps_no_oracle(tmp_path: Path) -> None:
    eval_manifest_path, users_path = _write_fixed_eval_artifact(tmp_path)
    q20_source_manifest_path = tmp_path / "q20" / "source_index_manifest.json"
    q20_source_manifest_path.parent.mkdir(parents=True, exist_ok=True)
    q20_source_manifest_path.write_text(json.dumps({"source": "itemcf_strong", "variant": "q20"}, ensure_ascii=False), encoding="utf-8")
    seen_overrides: dict[str, Any] = {}

    def fake_candidate_runner(**kwargs: Any) -> dict[str, Any]:
        output_dir = Path(kwargs["output_dir"])
        variant_name = output_dir.name
        seen_overrides[variant_name] = kwargs["source_manifest_paths"]
        rows = [
            {"user_id": "u_hot", "item_id": "i_hit_hot", "rank": 1, "source": "popular", "sources": ["popular"]},
            {"user_id": "u_warm", "item_id": "i_other_warm", "rank": 1, "source": "category", "sources": ["category"]},
            {"user_id": "u_cold", "item_id": "i_other_cold", "rank": 1, "source": "category", "sources": ["category"]},
        ]
        if variant_name == "q20":
            rows[1] = {"user_id": "u_warm", "item_id": "i_hit_warm", "rank": 1, "source": "itemcf_strong", "sources": ["itemcf_strong"]}
        _write_jsonl(output_dir / "pool500_candidates.jsonl", rows)
        return {"schema_version": "fake_generation_v1", "status": "PASS", "diagnostic_hot_budget_audit": {"variant": variant_name}}

    manifest = run_itemcf_strong_augcf_route_gate_matrix(
        variants={"relaxed": "relaxed", "q20": q20_source_manifest_path},
        eval_manifest_path=eval_manifest_path,
        eval_users_path=users_path,
        output_dir=tmp_path / "route_gate_matrix",
        overwrite=True,
        enforce_venv=False,
        candidate_runner=fake_candidate_runner,
    )

    persisted = read_json(tmp_path / "route_gate_matrix" / "route_gate_evidence_manifest.json")
    assert manifest == persisted
    assert set(persisted["variants"]) == {"baseline", "relaxed", "q20"}
    assert seen_overrides["baseline"] is None
    assert seen_overrides["relaxed"] is None
    assert seen_overrides["q20"] == {"itemcf_strong": q20_source_manifest_path}
    assert persisted["no_oracle"] is True
    assert persisted["eval_only"] is True
    assert persisted["diagnostic_only"] is True
    assert persisted["label_backflow_allowed"] is False
    assert persisted["variants"]["q20"]["source_manifest_overrides"] == {"itemcf_strong": str(q20_source_manifest_path)}
    assert persisted["variants"]["q20"]["delta_vs_baseline"]["Recall@500"] == pytest.approx(0.333333, abs=1e-6)
    assert persisted["variants"]["q20"]["delta_vs_baseline"]["HitRate@500"] == pytest.approx(0.333334, abs=1e-6)
    assert persisted["variants"]["q20"]["positive_hit_pairs"]["exclusive_vs_baseline_count"] == 1
    assert persisted["variants"]["q20"]["positive_hit_pairs"]["exclusive_vs_baseline"] == [{"user_id": "u_warm", "item_id": "i_hit_warm"}]
    assert persisted["variants"]["q20"]["source_hit_attribution"]["primary_source_counts"] == {"itemcf_strong": 1, "popular": 1}
    assert persisted["variants"]["q20"]["diagnostic_decision"] in persisted["diagnostic_decisions_allowed"]
    assert "READY" not in json.dumps(persisted, ensure_ascii=False)
    assert "PROMOTE" not in json.dumps(persisted, ensure_ascii=False)


def test_itemcf_strong_augcf_route_gate_matrix_applies_base_source_overrides(tmp_path: Path) -> None:
    eval_manifest_path, users_path = _write_fixed_eval_artifact(tmp_path)
    disabled_swing_manifest_path = tmp_path / "disabled" / "swing_recall_source_index_manifest.json"
    disabled_swing_manifest_path.parent.mkdir(parents=True, exist_ok=True)
    disabled_swing_manifest_path.write_text(json.dumps({"source": "swing_recall", "source_status": "DISABLED_DIAGNOSTIC"}, ensure_ascii=False), encoding="utf-8")
    q20_source_manifest_path = tmp_path / "q20" / "source_index_manifest.json"
    q20_source_manifest_path.parent.mkdir(parents=True, exist_ok=True)
    q20_source_manifest_path.write_text(json.dumps({"source": "itemcf_strong", "variant": "q20"}, ensure_ascii=False), encoding="utf-8")
    seen_overrides: dict[str, Any] = {}

    def fake_candidate_runner(**kwargs: Any) -> dict[str, Any]:
        output_dir = Path(kwargs["output_dir"])
        variant_name = output_dir.name
        seen_overrides[variant_name] = kwargs["source_manifest_paths"]
        _write_jsonl(
            output_dir / "pool500_candidates.jsonl",
            [
                {"user_id": "u_hot", "item_id": "i_hit_hot", "rank": 1, "source": "popular", "sources": ["popular"]},
                {"user_id": "u_warm", "item_id": "i_other_warm", "rank": 1, "source": "category", "sources": ["category"]},
                {"user_id": "u_cold", "item_id": "i_other_cold", "rank": 1, "source": "category", "sources": ["category"]},
            ],
        )
        return {"schema_version": "fake_generation_v1", "status": "PASS"}

    run_itemcf_strong_augcf_route_gate_matrix(
        variants={"relaxed": "relaxed", "q20": q20_source_manifest_path},
        base_source_manifest_paths={"swing_recall": disabled_swing_manifest_path},
        eval_manifest_path=eval_manifest_path,
        eval_users_path=users_path,
        output_dir=tmp_path / "route_gate_matrix_base_overrides",
        overwrite=True,
        enforce_venv=False,
        candidate_runner=fake_candidate_runner,
    )

    assert seen_overrides["baseline"] == {"swing_recall": disabled_swing_manifest_path}
    assert seen_overrides["relaxed"] == {"swing_recall": disabled_swing_manifest_path}
    assert seen_overrides["q20"] == {"swing_recall": disabled_swing_manifest_path, "itemcf_strong": q20_source_manifest_path}


def test_evaluate_candidates_rejects_duplicate_user_item(tmp_path: Path) -> None:
    candidate_path = tmp_path / "pool500_candidates.jsonl"
    _write_jsonl(
        candidate_path,
        [
            {"user_id": "u1", "item_id": "i1", "rank": 1, "source": "popular"},
            {"user_id": "u1", "item_id": "i1", "rank": 2, "source": "popular"},
        ],
    )

    with pytest.raises(ValueError, match=r"duplicate user_id\+item_id"):
        _evaluate_candidates(candidate_path, ["u1"], {"u1": {"i1"}}, {"u1": "hot"})
