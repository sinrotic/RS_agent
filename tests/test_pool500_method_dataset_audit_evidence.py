from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from rs_lab.experiments.recall.build_pool500_method_dataset import build_pool500_method_dataset
from rs_lab.experiments.recall.build_pool500_two_tower_method_dataset import build_pool500_two_tower_method_dataset
from rs_lab.experiments.recall.build_train_only_data_governance import DERIVED_DATASET_POLICIES, SCHEMA_VERSION as GOVERNANCE_SCHEMA_VERSION
from rs_lab.experiments.recall.validate_pool500_method_dataset_audit_evidence import validate_pool500_method_dataset_audit_evidence

pytestmark = pytest.mark.unit


def test_method_dataset_audit_is_diagnostic_only_and_does_not_require_candidates(tmp_path: Path) -> None:
    paths = _write_fixture(tmp_path)
    collab_dir = tmp_path / "collab_dataset"
    two_tower_dir = tmp_path / "two_tower_dataset"
    build_pool500_method_dataset(
        governance_manifest_path=paths["governance_manifest"],
        output_dir=collab_dir,
        source_method="itemcf_weak",
        overwrite=True,
        enforce_venv=False,
    )
    build_pool500_two_tower_method_dataset(
        clean_manifest_path=paths["clean_manifest"],
        governance_manifest_path=paths["governance_manifest"],
        output_dir=two_tower_dir,
        limit_users=2,
        max_samples=4,
        negative_ratio=1,
        overwrite=True,
        enforce_venv=False,
    )

    report = validate_pool500_method_dataset_audit_evidence(
        governance_manifest_path=paths["governance_manifest"],
        method_dataset_paths=[collab_dir, two_tower_dir / "method_dataset_manifest.json"],
        output_path=tmp_path / "audit_report.json",
        enforce_venv=False,
    )

    assert report["status"] == "PASS"
    assert report["diagnostic_only"] is True
    assert report["candidate_generation_allowed"] is False
    assert report["ranking_input_replacement_allowed"] is False
    assert report["promotion_allowed"] is False
    assert report["final_pool500_ready_claimed"] is False
    assert report["audited_manifest_count"] == 2
    two_tower_audit = next(audit for audit in report["audited_manifests"] if audit["method"] == "two_tower")
    phase1_contract = two_tower_audit["diagnostics"]["phase1_manifest_contract"]
    assert phase1_contract["universe_missing"] == []
    assert phase1_contract["stats_missing"] == []
    assert phase1_contract["boundary_missing"] == []
    assert phase1_contract["eval_target_universe_available"] is False
    assert phase1_contract["retrieval_item_universe_available"] is False
    assert not (collab_dir / "candidates.jsonl").exists()
    assert not (two_tower_dir / "source_index_manifest.json").exists()


def test_method_dataset_audit_uses_manifest_upstream_governance_path(tmp_path: Path) -> None:
    paths = _write_fixture(tmp_path)
    collab_dir = tmp_path / "itemcf_weak_dataset"
    build_pool500_method_dataset(
        governance_manifest_path=paths["governance_manifest"],
        output_dir=collab_dir,
        source_method="itemcf_weak",
        overwrite=True,
        enforce_venv=False,
    )

    report = validate_pool500_method_dataset_audit_evidence(
        governance_manifest_path=tmp_path / "train_only_v1" / "manifest.json",
        method_dataset_paths=[collab_dir],
        output_path=None,
        enforce_venv=False,
    )

    assert report["status"] == "PASS"
    assert "missing_governance_manifest" not in "\n".join(report["blockers"])
    assert "method_dataset_governance_manifest_path_mismatch" not in report["audited_manifests"][0]["blockers"]
    assert report["audited_manifests"][0]["diagnostics"]["upstream"]["governance_manifest_path"] == str(paths["governance_manifest"].resolve())


def test_itemcf_edge_feature_audit_remains_method_dataset_only(tmp_path: Path) -> None:
    paths = _write_fixture(tmp_path)
    weak_dir = tmp_path / "itemcf_weak_dataset"
    strong_dir = tmp_path / "itemcf_strong_dataset"
    build_pool500_method_dataset(
        governance_manifest_path=paths["governance_manifest"],
        output_dir=weak_dir,
        source_method="itemcf_weak",
        overwrite=True,
        enforce_venv=False,
    )
    build_pool500_method_dataset(
        governance_manifest_path=paths["governance_manifest"],
        output_dir=strong_dir,
        source_method="itemcf_strong",
        scale_tier="smoke",
        overwrite=True,
        enforce_venv=False,
    )

    report = validate_pool500_method_dataset_audit_evidence(
        governance_manifest_path=paths["governance_manifest"],
        method_dataset_paths=[weak_dir, strong_dir],
        output_path=None,
        enforce_venv=False,
    )

    assert report["status"] == "PASS"
    assert report["candidate_generation_allowed"] is False
    assert report["ranking_input_replacement_allowed"] is False
    assert report["promotion_allowed"] is False
    assert report["final_pool500_ready_claimed"] is False
    required_fields = set(report["audited_manifests"][0]["diagnostics"]["itemcf_edge_features"]["required_fields"])
    assert {"weighted_cooc", "supporting_user_count", "score_policy", "itemcf_score_formula", "active_user_penalty_policy"} <= required_fields
    assert _read_jsonl(weak_dir / "method_dataset_rows.jsonl")
    for output_dir in (weak_dir, strong_dir):
        manifest = _read_json(output_dir / "method_dataset_manifest.json")
        rows = _read_jsonl(output_dir / "method_dataset_rows.jsonl")
        serialized_manifest = json.dumps(manifest, ensure_ascii=False)
        assert manifest["layer"] == "method_dataset"
        assert manifest["outputs"]["dataset_schema"] == "itemcf_edge_features_v1"
        assert manifest["outputs"]["feature_schema"] == "itemcf_edge_features_v1"
        assert manifest["feature_summary"]["schema_name"] == "itemcf_edge_features_v1"
        assert manifest["feature_summary"]["layer"] == "method_dataset"
        assert manifest["feature_summary"]["score_policy"] == "weighted_cooc_cosine_normalized_v1"
        assert manifest["feature_summary"]["score_formula"] == "round(weighted_cooc / sqrt(src_user_count * dst_user_count), 6)"
        assert manifest["feature_summary"]["active_user_penalty_policy"] == "round(1 / log1p(filtered_sequence_len), 6)"
        assert manifest["is_source_artifact"] is False
        assert manifest["is_candidate"] is False
        assert manifest["is_ranking"] is False
        assert manifest["is_promotion"] is False
        assert manifest["candidate_generation_allowed"] is False
        assert manifest["ranking_input_replacement_allowed"] is False
        assert manifest["promotion_allowed"] is False
        assert manifest["final_pool500_ready_claimed"] is False
        assert "source_index_manifest_path" not in serialized_manifest
        assert "artifact_manifest_path" not in serialized_manifest
        assert "candidates_path" not in serialized_manifest
        assert all("dropped_reason" not in row for row in rows)
        assert all(row["dataset_role"] == "method_dataset_itemcf_edge_feature" for row in rows)
        assert all("weighted_cooc" in row for row in rows)
        assert all(row["supporting_user_count"] == row["pair_support"] for row in rows)
        assert all(row["score_policy"] == "weighted_cooc_cosine_normalized_v1" for row in rows)
        assert all(row["itemcf_score_formula"] == "round(weighted_cooc / sqrt(src_user_count * dst_user_count), 6)" for row in rows)
        assert all(row["active_user_penalty_policy"] == "round(1 / log1p(filtered_sequence_len), 6)" for row in rows)
        assert all("candidate_score" not in row and "ranking_score" not in row and "promotion_score" not in row for row in rows)


def test_method_dataset_audit_blocks_legacy_capped_schema_as_p2_main(tmp_path: Path) -> None:
    paths = _write_fixture(tmp_path)
    capped_dir = tmp_path / "legacy_capped_dataset"
    capped_dir.mkdir()
    _write_json(
        capped_dir / "method_dataset_manifest.json",
        {
            "schema_version": "pool500_capped_unified_train_behavior_dataset_v1",
            "method": "capped_unified_train_behavior_dataset",
            "status": "PASS",
            "train_only": True,
            "upstream_governance_manifest_path": str(paths["governance_manifest"]),
            "candidate_generation_allowed": False,
            "ranking_input_replacement_allowed": False,
            "promotion_allowed": False,
            "final_pool500_ready_claimed": False,
            "outputs": {},
        },
    )

    report = validate_pool500_method_dataset_audit_evidence(
        governance_manifest_path=paths["governance_manifest"],
        method_dataset_paths=[capped_dir],
        output_path=None,
        enforce_venv=False,
    )

    assert report["status"] == "BLOCKED"
    blockers = report["audited_manifests"][0]["blockers"]
    assert "legacy_capped_method_dataset_schema_not_allowed_as_p2_main:pool500_capped_unified_train_behavior_dataset_v1" in blockers


def test_method_dataset_audit_blocks_ready_promotion_and_source_artifact_semantics(tmp_path: Path) -> None:
    paths = _write_fixture(tmp_path)
    collab_dir = tmp_path / "collab_dataset"
    build_pool500_method_dataset(
        governance_manifest_path=paths["governance_manifest"],
        output_dir=collab_dir,
        source_method="itemcf_weak",
        overwrite=True,
        enforce_venv=False,
    )
    manifest_path = collab_dir / "method_dataset_manifest.json"
    manifest = _read_json(manifest_path)
    manifest["final_pool500_ready_claimed"] = True
    manifest["promotion_allowed"] = True
    manifest["promotion_manifest_path"] = str(collab_dir / "promotion_manifest.json")
    manifest["outputs"]["source_index_manifest_path"] = str(collab_dir / "source_index_manifest.json")
    _write_json(manifest_path, manifest)

    report = validate_pool500_method_dataset_audit_evidence(
        governance_manifest_path=paths["governance_manifest"],
        method_dataset_paths=[manifest_path],
        output_path=None,
        enforce_venv=False,
    )

    assert report["status"] == "BLOCKED"
    blockers = "\n".join(report["audited_manifests"][0]["blockers"])
    assert "promotion_allowed_not_false" in blockers
    assert "final_pool500_ready_claimed_not_false" in blockers
    assert "forbidden_ready_or_artifact_semantics" in blockers
    assert report["audited_manifests"][0]["migration_punchlist"]


def test_method_dataset_audit_blocks_missing_v2_bucket_dependency(tmp_path: Path) -> None:
    paths = _write_fixture(tmp_path)
    user_rows = _read_jsonl(paths["user_quality_profile"])
    user_rows[0].pop("quality_bucket_v2")
    _write_jsonl(paths["user_quality_profile"], user_rows)

    report = validate_pool500_method_dataset_audit_evidence(
        governance_manifest_path=paths["governance_manifest"],
        method_dataset_paths=[],
        output_path=None,
        enforce_venv=False,
    )

    assert report["status"] == "BLOCKED"
    assert "p1_user_quality_profile_missing_quality_bucket_v2" in report["blockers"]
    assert report["diagnostics"]["p1_governance"]["artifacts"]["user_quality_profile"]["missing_quality_bucket_v2_rows"] == 1


def test_two_tower_audit_blocks_negative_universe_without_p1_provenance(tmp_path: Path) -> None:
    paths = _write_fixture(tmp_path)
    two_tower_dir = tmp_path / "two_tower_dataset"
    build_pool500_two_tower_method_dataset(
        clean_manifest_path=paths["clean_manifest"],
        governance_manifest_path=paths["governance_manifest"],
        output_dir=two_tower_dir,
        limit_users=2,
        max_samples=4,
        negative_ratio=1,
        overwrite=True,
        enforce_venv=False,
    )
    universe = _read_jsonl(two_tower_dir / "negative_item_universe.jsonl")
    universe.append({"parent_asin": "not_from_p1", "quality_bucket_v2": "embedding_ready", "source_layer": "manual"})
    _write_jsonl(two_tower_dir / "negative_item_universe.jsonl", universe)

    report = validate_pool500_method_dataset_audit_evidence(
        governance_manifest_path=paths["governance_manifest"],
        method_dataset_paths=[two_tower_dir],
        output_path=None,
        enforce_venv=False,
    )

    assert report["status"] == "BLOCKED"
    blockers = report["audited_manifests"][0]["blockers"]
    assert "two_tower_negative_universe_not_provenanced_from_p1_item_quality_and_frequency" in blockers
    assert report["audited_manifests"][0]["diagnostics"]["negative_universe_provenance"]["bad_row_count"] == 1


def test_two_tower_audit_blocks_wrong_phase1_manifest_contract_values(tmp_path: Path) -> None:
    paths = _write_fixture(tmp_path)
    two_tower_dir = tmp_path / "two_tower_dataset"
    build_pool500_two_tower_method_dataset(
        clean_manifest_path=paths["clean_manifest"],
        governance_manifest_path=paths["governance_manifest"],
        output_dir=two_tower_dir,
        limit_users=2,
        max_samples=4,
        negative_ratio=1,
        overwrite=True,
        enforce_venv=False,
    )
    manifest_path = two_tower_dir / "method_dataset_manifest.json"
    manifest = _read_json(manifest_path)
    manifest["eval_target_universe_available"] = True
    manifest["retrieval_item_universe_available"] = True
    manifest["stats"]["eval_target_universe_available"] = True
    manifest["stats"]["eval_target_universe_coverage_status"] = "ready"
    manifest["stats"]["retrieval_item_universe_available"] = True
    manifest["stats"]["retrieval_item_universe_coverage_status"] = "ready"
    manifest["data_usage_boundary"]["candidate_generation_allowed"] = True
    manifest["data_usage_boundary"]["ranking_input_replacement_allowed"] = True
    manifest["data_usage_boundary"]["promotion_allowed"] = True
    manifest["data_usage_boundary"]["final_pool500_ready_claimed"] = True
    manifest["data_usage_boundary"]["label_artifacts"]["forbidden_uses"] = ["training"]
    manifest["data_usage_boundary"]["oracle_artifacts"]["allowed_uses"] = ["diagnostic_eval_only", "training"]
    manifest["data_usage_boundary"]["diagnostic_oracle_artifacts"]["forbidden_uses"] = []
    _write_json(manifest_path, manifest)

    report = validate_pool500_method_dataset_audit_evidence(
        governance_manifest_path=paths["governance_manifest"],
        method_dataset_paths=[two_tower_dir],
        output_path=None,
        enforce_venv=False,
    )

    assert report["status"] == "BLOCKED"
    blockers = "\n".join(report["audited_manifests"][0]["blockers"])
    assert "two_tower_phase1_eval_target_universe_must_be_unavailable" in blockers
    assert "two_tower_phase1_retrieval_item_universe_must_be_unavailable" in blockers
    assert "two_tower_phase1_eval_target_coverage_must_be_phase1_not_built" in blockers
    assert "two_tower_phase1_retrieval_coverage_must_be_phase1_not_built" in blockers
    assert "two_tower_phase1_data_usage_boundary_candidate_generation_allowed_not_false" in blockers
    assert "two_tower_phase1_data_usage_boundary_ranking_input_replacement_allowed_not_false" in blockers
    assert "two_tower_phase1_data_usage_boundary_promotion_allowed_not_false" in blockers
    assert "two_tower_phase1_data_usage_boundary_final_pool500_ready_claimed_not_false" in blockers
    assert "two_tower_phase1_data_usage_boundary_missing_forbidden_uses:label_artifacts" in blockers
    assert "two_tower_phase1_data_usage_boundary_allows_forbidden_scope:oracle_artifacts" in blockers
    assert "two_tower_phase1_data_usage_boundary_missing_forbidden_uses:diagnostic_oracle_artifacts" in blockers


def test_two_tower_audit_blocks_missing_phase1_manifest_contract(tmp_path: Path) -> None:
    paths = _write_fixture(tmp_path)
    two_tower_dir = tmp_path / "two_tower_dataset"
    build_pool500_two_tower_method_dataset(
        clean_manifest_path=paths["clean_manifest"],
        governance_manifest_path=paths["governance_manifest"],
        output_dir=two_tower_dir,
        limit_users=2,
        max_samples=4,
        negative_ratio=1,
        overwrite=True,
        enforce_venv=False,
    )
    manifest_path = two_tower_dir / "method_dataset_manifest.json"
    manifest = _read_json(manifest_path)
    manifest.pop("universe_definitions")
    manifest["stats"].pop("raw_target_occurrence_count")
    manifest["data_usage_boundary"].pop("oracle_artifacts")
    _write_json(manifest_path, manifest)

    report = validate_pool500_method_dataset_audit_evidence(
        governance_manifest_path=paths["governance_manifest"],
        method_dataset_paths=[two_tower_dir],
        output_path=None,
        enforce_venv=False,
    )

    assert report["status"] == "BLOCKED"
    blockers = "\n".join(report["audited_manifests"][0]["blockers"])
    assert "two_tower_phase1_missing_universe_definitions" in blockers
    assert "two_tower_phase1_missing_denominator_stats" in blockers
    assert "two_tower_phase1_missing_data_usage_boundary" in blockers



def test_two_tower_audit_blocks_low_distinct_negative_usage(tmp_path: Path) -> None:
    paths = _write_fixture(tmp_path)
    two_tower_dir = tmp_path / "two_tower_dataset"
    _build_two_tower_fixture_dataset(paths, two_tower_dir, negative_ratio=1)
    samples_path = two_tower_dir / "two_tower_train_samples.jsonl"
    samples = _read_jsonl(samples_path)
    for sample in samples:
        sample["negative_item_ids"] = ["neg_b"]
    _write_jsonl(samples_path, samples)
    manifest_path = two_tower_dir / "method_dataset_manifest.json"
    manifest = _read_json(manifest_path)
    manifest["stats"].update(
        {
            "used_negative_distinct_item_count": 1,
            "used_negative_item_occurrence_count": len(samples),
            "used_negative_item_coverage_ratio": 0.5,
            "negative_item_usage_top1_count": len(samples),
            "negative_item_usage_top10_share": 1.0,
            "negative_item_count_mean": 1.0,
            "negative_item_count_under_requested_count": 0,
        }
    )
    _write_json(manifest_path, manifest)

    report = validate_pool500_method_dataset_audit_evidence(
        governance_manifest_path=paths["governance_manifest"],
        method_dataset_paths=[two_tower_dir],
        output_path=None,
        enforce_venv=False,
    )

    assert report["status"] == "BLOCKED"
    assert "two_tower_used_negative_diversity_below_threshold" in report["audited_manifests"][0]["blockers"]


def test_two_tower_audit_blocks_negative_leakage(tmp_path: Path) -> None:
    paths = _write_fixture(tmp_path)
    two_tower_dir = tmp_path / "two_tower_dataset"
    _build_two_tower_fixture_dataset(paths, two_tower_dir, negative_ratio=1)
    samples_path = two_tower_dir / "two_tower_train_samples.jsonl"
    samples = _read_jsonl(samples_path)
    samples[0]["negative_item_ids"] = [samples[0]["target_item"]]
    _write_jsonl(samples_path, samples)

    report = validate_pool500_method_dataset_audit_evidence(
        governance_manifest_path=paths["governance_manifest"],
        method_dataset_paths=[two_tower_dir],
        output_path=None,
        enforce_venv=False,
    )

    assert report["status"] == "BLOCKED"
    assert "two_tower_train_sample_negative_leakage" in report["audited_manifests"][0]["blockers"]


def test_two_tower_audit_blocks_empty_train_samples(tmp_path: Path) -> None:
    paths = _write_fixture(tmp_path)
    two_tower_dir = tmp_path / "two_tower_dataset"
    _build_two_tower_fixture_dataset(paths, two_tower_dir, negative_ratio=1)
    _write_jsonl(two_tower_dir / "two_tower_train_samples.jsonl", [])
    manifest_path = two_tower_dir / "method_dataset_manifest.json"
    manifest = _read_json(manifest_path)
    manifest["stats"]["train_sample_count"] = 0
    _write_json(manifest_path, manifest)

    report = validate_pool500_method_dataset_audit_evidence(
        governance_manifest_path=paths["governance_manifest"],
        method_dataset_paths=[two_tower_dir],
        output_path=None,
        enforce_venv=False,
    )

    assert report["status"] == "BLOCKED"
    assert "two_tower_empty_train_samples" in report["audited_manifests"][0]["blockers"]


def test_two_tower_audit_blocks_empty_targets(tmp_path: Path) -> None:
    paths = _write_fixture(tmp_path)
    two_tower_dir = tmp_path / "two_tower_dataset"
    _build_two_tower_fixture_dataset(paths, two_tower_dir, negative_ratio=1)
    samples_path = two_tower_dir / "two_tower_train_samples.jsonl"
    samples = _read_jsonl(samples_path)
    for sample in samples:
        sample["target_item"] = ""
        sample["positive_item_id"] = ""
    _write_jsonl(samples_path, samples)
    manifest_path = two_tower_dir / "method_dataset_manifest.json"
    manifest = _read_json(manifest_path)
    manifest["stats"]["sample_target_item_count"] = 0
    _write_json(manifest_path, manifest)

    report = validate_pool500_method_dataset_audit_evidence(
        governance_manifest_path=paths["governance_manifest"],
        method_dataset_paths=[two_tower_dir],
        output_path=None,
        enforce_venv=False,
    )

    assert report["status"] == "BLOCKED"
    assert "two_tower_empty_train_samples" in report["audited_manifests"][0]["blockers"]


def test_two_tower_audit_blocks_empty_negatives(tmp_path: Path) -> None:
    paths = _write_fixture(tmp_path)
    two_tower_dir = tmp_path / "two_tower_dataset"
    _build_two_tower_fixture_dataset(paths, two_tower_dir, negative_ratio=1)
    samples_path = two_tower_dir / "two_tower_train_samples.jsonl"
    samples = _read_jsonl(samples_path)
    samples[0]["negative_item_ids"] = []
    _write_jsonl(samples_path, samples)

    report = validate_pool500_method_dataset_audit_evidence(
        governance_manifest_path=paths["governance_manifest"],
        method_dataset_paths=[two_tower_dir],
        output_path=None,
        enforce_venv=False,
    )

    assert report["status"] == "BLOCKED"
    assert "two_tower_empty_train_sample_negatives" in report["audited_manifests"][0]["blockers"]


def test_two_tower_audit_blocks_target_p1_quality_or_frequency_missing(tmp_path: Path) -> None:
    paths = _write_fixture(tmp_path)
    two_tower_dir = tmp_path / "two_tower_dataset"
    _build_two_tower_fixture_dataset(paths, two_tower_dir, negative_ratio=1)
    manifest_path = two_tower_dir / "method_dataset_manifest.json"
    manifest = _read_json(manifest_path)
    manifest["stats"]["training_item_universe_target_items_missing_p1_quality"] = 1
    manifest["stats"]["training_item_universe_target_items_missing_frequency"] = 1
    _write_json(manifest_path, manifest)

    report = validate_pool500_method_dataset_audit_evidence(
        governance_manifest_path=paths["governance_manifest"],
        method_dataset_paths=[two_tower_dir],
        output_path=None,
        enforce_venv=False,
    )

    assert report["status"] == "BLOCKED"
    assert "two_tower_positive_target_p1_quality_or_frequency_missing" in report["audited_manifests"][0]["blockers"]


def test_two_tower_audit_blocks_target_metadata_incomplete(tmp_path: Path) -> None:
    paths = _write_fixture(tmp_path)
    two_tower_dir = tmp_path / "two_tower_dataset"
    _build_two_tower_fixture_dataset(paths, two_tower_dir, negative_ratio=1)
    training_universe_path = two_tower_dir / "training_item_universe.jsonl"
    rows = _read_jsonl(training_universe_path)
    target_row = next(row for row in rows if "positive_target" in row["item_roles"])
    target_row["item_text"] = ""
    _write_jsonl(training_universe_path, rows)

    report = validate_pool500_method_dataset_audit_evidence(
        governance_manifest_path=paths["governance_manifest"],
        method_dataset_paths=[two_tower_dir],
        output_path=None,
        enforce_venv=False,
    )

    assert report["status"] == "BLOCKED"
    assert "two_tower_positive_target_metadata_incomplete" in report["audited_manifests"][0]["blockers"]


def test_method_dataset_audit_does_not_use_shadow_ranking_gate() -> None:
    source_path = Path("D:/sinrotic_code/python_project/summer/RS_agent/rs_lab/experiments/recall/validate_pool500_method_dataset_audit_evidence.py")
    source = source_path.read_text(encoding="utf-8")

    assert "validate_pool500_shadow_ranking_evidence" not in source
    assert "run_pool500_shadow_ranking" not in source
    assert "DEFAULT_SOURCE_MANIFESTS" not in source


def _build_two_tower_fixture_dataset(paths: dict[str, Path], output_dir: Path, *, negative_ratio: int) -> None:
    build_pool500_two_tower_method_dataset(
        clean_manifest_path=paths["clean_manifest"],
        governance_manifest_path=paths["governance_manifest"],
        output_dir=output_dir,
        limit_users=2,
        max_samples=4,
        negative_ratio=negative_ratio,
        overwrite=True,
        enforce_venv=False,
    )


def _write_fixture(tmp_path: Path) -> dict[str, Path]:
    clean_dir = tmp_path / "clean"
    governance_dir = tmp_path / "governance"
    clean_dir.mkdir()
    governance_dir.mkdir()

    train_sequences = clean_dir / "user_sequences.train.jsonl"
    _write_jsonl(
        train_sequences,
        [
            {"user_id": "u_heavy", "recent_item_sequence": ["pos_a", "neg_a"], "recent_positive_item_sequence": ["cf_mid", "pos_a"]},
            {"user_id": "u_medium", "recent_item_sequence": ["pos_b"], "recent_positive_item_sequence": ["cf_mid", "pos_b"]},
            {"user_id": "u_fallback", "recent_item_sequence": ["pos_c"], "recent_positive_item_sequence": ["cf_mid"]},
        ],
    )
    canonical_items = clean_dir / "canonical_items.jsonl"
    _write_jsonl(
        canonical_items,
        [
            {"parent_asin": item_id, "title_clean": f"Title {item_id}", "main_category": "Office", "category": "Office Supplies"}
            for item_id in ["cf_mid", "pos_a", "pos_b", "pos_c", "neg_a", "neg_b", "neg_c"]
        ],
    )
    clean_manifest = clean_dir / "manifest.json"
    _write_json(clean_manifest, {"train_user_sequences_path": str(train_sequences), "canonical_items_path": str(canonical_items)})

    user_quality_profile = governance_dir / "user_quality_profile.jsonl"
    _write_jsonl(
        user_quality_profile,
        [
            _user("u_heavy", "heavy_cf_eligible"),
            _user("u_medium", "medium_behavior"),
            _user("u_fallback", "fallback_only"),
        ],
    )
    item_quality_profile = governance_dir / "item_quality_profile.jsonl"
    _write_jsonl(
        item_quality_profile,
        [
            _item("cf_mid", cf_ready=True, hotness_bucket="mid", quality_bucket_v2="cf_ready", frequency=2, rank=1),
            _item("pos_a", cf_ready=True, hotness_bucket="mid", quality_bucket_v2="cf_ready", frequency=1, rank=2),
            _item("pos_b", cf_ready=True, hotness_bucket="mid", quality_bucket_v2="cf_ready", frequency=1, rank=3),
            _item("neg_a", cf_ready=True, hotness_bucket="hot", quality_bucket_v2="embedding_ready", frequency=9, rank=4),
            _item("neg_b", cf_ready=True, hotness_bucket="hot", quality_bucket_v2="embedding_ready", frequency=8, rank=5),
            _item("neg_c", cf_ready=True, hotness_bucket="hot", quality_bucket_v2="embedding_ready", frequency=7, rank=6),
        ],
    )
    item_frequency_train = governance_dir / "item_frequency_train.jsonl"
    _write_jsonl(
        item_frequency_train,
        [
            {"parent_asin": "cf_mid", "frequency": 2, "user_count": 2},
            {"parent_asin": "pos_a", "frequency": 1, "user_count": 1},
            {"parent_asin": "pos_b", "frequency": 1, "user_count": 1},
            {"parent_asin": "neg_a", "frequency": 9, "user_count": 3},
            {"parent_asin": "neg_b", "frequency": 8, "user_count": 3},
            {"parent_asin": "neg_c", "frequency": 7, "user_count": 2},
        ],
    )
    governance_manifest = governance_dir / "manifest.json"
    policies = {name: dict(policy) for name, policy in DERIVED_DATASET_POLICIES.items()}
    policies["two_tower"]["train_only_inputs"] = ["user_quality_profile.jsonl", "item_quality_profile.jsonl", "item_frequency_train.jsonl", "user_sequences.train.jsonl"]
    _write_json(
        governance_manifest,
        {
            "schema_version": GOVERNANCE_SCHEMA_VERSION,
            "status": "PASS",
            "train_only": True,
            "artifacts": {
                "user_quality_profile": str(user_quality_profile),
                "item_quality_profile": str(item_quality_profile),
                "item_frequency_train": str(item_frequency_train),
            },
            "lineage": {"input_files": {"user_sequences_train": str(train_sequences)}},
            "derived_dataset_policies": policies,
        },
    )
    return {
        "clean_manifest": clean_manifest,
        "governance_manifest": governance_manifest,
        "user_quality_profile": user_quality_profile,
        "item_quality_profile": item_quality_profile,
        "item_frequency_train": item_frequency_train,
    }


def _user(user_id: str, bucket: str) -> dict[str, object]:
    return {"user_id": user_id, "quality_bucket": bucket, "quality_bucket_v2": _bucket_v2(bucket), "eligible_for_two_tower": bucket != "fallback_only"}


def _bucket_v2(bucket: str) -> str:
    return {
        "cold_start": "cold_start",
        "fallback_only": "fallback_only",
        "medium_behavior": "medium_behavior",
        "two_tower_train_eligible": "sequence_sufficient",
        "heavy_cf_eligible": "collaborative_rich",
    }[bucket]


def _item(parent_asin: str, *, cf_ready: bool, hotness_bucket: str, quality_bucket_v2: str, frequency: int, rank: int) -> dict[str, object]:
    return {
        "parent_asin": parent_asin,
        "cf_ready": cf_ready,
        "hotness_bucket": hotness_bucket,
        "quality_bucket_v2": quality_bucket_v2,
        "positive_event_count": frequency,
        "unique_positive_user_count": max(1, frequency // 3),
        "global_pop_rank": rank,
        "train_only": True,
    }


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
