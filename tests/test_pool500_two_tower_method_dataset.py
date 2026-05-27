from __future__ import annotations

import ast
import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from rs_lab.experiments.recall.build_pool500_two_tower_method_dataset import build_pool500_two_tower_method_dataset

pytestmark = pytest.mark.unit

PYTHON = Path("D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe")
OUTPUT_WHITELIST = {
    "two_tower_train_samples.jsonl",
    "negative_item_universe.jsonl",
    "training_item_universe.jsonl",
    "method_dataset_manifest.json",
    "leakage_audit.json",
}
FORMAL_DATASET_DIR = Path("D:/sinrotic_code/python_project/summer/RS_agent/outputs/recall/pool500_method_datasets/two_tower/train_only_v1")
DIAGNOSTIC_LOOP_DIR = Path("D:/sinrotic_code/python_project/summer/RS_agent/outputs/recall/pool500_two_tower_diagnostic_loop")
FORBIDDEN_FIELDS = {
    "source_index_manifest_path",
    "artifact_manifest_path",
    "embedding_path",
    "index_path",
    "candidates",
    "candidate_path",
}
FORBIDDEN_PATH_TOKENS = {"oracle", "label", "valid", "validation", "test", "holdout", "eval"}


def test_two_tower_method_dataset_writes_schema_outputs_and_samples(tmp_path: Path) -> None:
    paths = _write_fixture(tmp_path)

    manifest = build_pool500_two_tower_method_dataset(
        clean_manifest_path=paths["clean_manifest"],
        governance_manifest_path=paths["governance_manifest"],
        output_dir=tmp_path / "method_dataset",
        limit_users=2,
        limit_interactions=0,
        max_samples=10,
        negative_ratio=2,
        max_items_per_user=3,
        overwrite=True,
        enforce_venv=False,
    )

    output_dir = tmp_path / "method_dataset"
    assert {path.name for path in output_dir.iterdir()} == OUTPUT_WHITELIST
    persisted_manifest = json.loads((output_dir / "method_dataset_manifest.json").read_text(encoding="utf-8"))
    assert persisted_manifest == manifest
    assert manifest["schema_version"] == "pool500_two_tower_method_dataset_v1"
    assert manifest["dataset_role"] == "train_only_two_tower_method_dataset"
    assert manifest["train_only"] is True
    assert manifest["candidate_generation_allowed"] is False
    assert manifest["ranking_input_replacement_allowed"] is False
    assert manifest["pool1000_allowed"] is False
    assert manifest["promotion_allowed"] is False
    assert manifest["final_pool500_ready_claimed"] is False
    policy = manifest["resource_scale_policy"]
    assert policy["input_scope"] == "governance_train_only"
    assert policy["scale_tier"] == "local_formal"
    assert policy["default_tier"] == "local_formal"
    assert set(policy["scale_tiers"]) == {"smoke", "diagnostic", "local_formal"}
    assert policy["scale_tiers"]["smoke"] == {"limit_users": 500, "max_samples": 20_000, "negative_ratio": 3, "max_items_per_user": 30}
    assert policy["scale_tiers"]["local_formal"] == {"limit_users": 150_000, "max_samples": 2_000_000, "negative_ratio": 5, "max_items_per_user": 80}
    assert policy["selection_strategy"]["policy_name"] == "two_tower_sequence_v1"
    assert policy["selection_strategy"]["sampling_unit"] == "user_sequence"
    assert policy["selection_strategy"]["preserve_order"] is True
    assert policy["sample_strategy"] == "sequence_to_target_transition_contract"
    assert policy["eligible_user_buckets"] == manifest["eligible_user_buckets"]
    assert policy["eligible_item_quality_bucket_v2"] == manifest["eligible_item_quality_bucket_v2"]
    assert policy["negative_universe_policy"] == manifest["negative_universe_policy"]
    assert policy["target_item_policy"] == manifest["target_item_policy"]
    assert policy["training_item_universe_policy"] == manifest["training_item_universe_policy"]
    assert policy["per_user_negative_universe_policy"] == manifest["per_user_negative_universe_policy"]
    assert policy["per_example_negative_universe_policy"] == manifest["per_example_negative_universe_policy"]
    assert policy["eval_target_universe_policy"] == "phase1_not_built"
    assert policy["eligible_target_universe_policy"] == manifest["eligible_target_universe_policy"]
    assert policy["p2_contract_scope"] == "method_dataset_only"
    assert manifest["eval_target_universe_available"] is False
    assert manifest["retrieval_item_universe_available"] is False
    universes = manifest["universe_definitions"]
    assert universes["training_item_universe"]["available"] is True
    assert universes["retrieval_item_universe"] == {"available": False, "reason": "phase1_not_built", "candidate_generation_allowed": False}
    assert universes["global_negative_universe"]["artifact"] == "negative_item_universe.jsonl"
    assert universes["eval_target_universe"]["available"] is False
    assert universes["eligible_target_universe"]["policy"] == "sampled_train_sequence_targets_only"
    boundary = manifest["data_usage_boundary"]
    assert boundary["diagnostic_only"] is True
    assert boundary["candidate_generation_allowed"] is False
    assert boundary["ranking_input_replacement_allowed"] is False
    assert boundary["promotion_allowed"] is False
    assert boundary["final_pool500_ready_claimed"] is False
    for artifact_key in ("label_artifacts", "oracle_artifacts", "diagnostic_oracle_artifacts"):
        assert boundary[artifact_key]["allowed_uses"] == ["diagnostic_eval_only"]
        assert set(boundary[artifact_key]["forbidden_uses"]) == {"training", "negative_sampling", "index_build", "official_candidate_generation"}
    assert set(manifest["outputs"]) == {"two_tower_train_samples", "negative_item_universe", "training_item_universe", "method_dataset_manifest", "leakage_audit"}
    assert not _contains_key(manifest, FORBIDDEN_FIELDS)

    universe = _read_jsonl(output_dir / "negative_item_universe.jsonl")
    assert [row["parent_asin"] for row in universe] == ["neg_a", "neg_b", "neg_c"]
    assert {row["quality_bucket_v2"] for row in universe} == {"embedding_ready"}
    assert {row["source_layer"] for row in universe} == {"p1_governance_train_only"}
    training_universe = {row["parent_asin"]: row for row in _read_jsonl(output_dir / "training_item_universe.jsonl")}
    assert set(training_universe) == {"neg_a", "neg_b", "neg_c", "seen_neg"}
    assert training_universe["neg_a"]["item_roles"] == ["negative_candidate", "positive_target"]
    assert training_universe["seen_neg"]["item_roles"] == ["positive_target"]
    assert training_universe["seen_neg"]["quality_bucket_v2"] == "low_frequency"
    assert training_universe["seen_neg"]["item_id"] == "seen_neg"
    assert training_universe["seen_neg"]["title_clean"] == "Title seen_neg"
    assert training_universe["seen_neg"]["main_category"] == "Office"

    samples = _read_jsonl(output_dir / "two_tower_train_samples.jsonl")
    assert samples
    assert len(samples) <= 10
    assert {row["user_id"] for row in samples} <= {"u_tt", "u_heavy"}
    universe_items = {row["parent_asin"] for row in universe}
    assert all({"history_items", "target_item"} <= set(row) for row in samples)
    assert samples[0]["history_items"] == ["pos_a"]
    assert samples[0]["target_item"] == "neg_a"
    assert samples[0]["positive_item_id"] == samples[0]["target_item"]
    assert all(row["target_item_source"] == "train_only_user_sequence" for row in samples)
    assert all(set(row["negative_item_ids"]) <= universe_items for row in samples)
    assert any(row["target_item"] not in universe_items for row in samples)
    assert all(len(row["negative_item_ids"]) <= 2 for row in samples)
    assert all(row["target_item"] not in row["negative_item_ids"] for row in samples)
    assert all(not (set(row["history_items"]) & set(row["negative_item_ids"])) for row in samples)
    assert all(row["target_item"] in training_universe for row in samples)
    assert manifest["stats"]["target_items_skipped_not_in_negative_universe"] == 0
    assert manifest["stats"]["target_items_outside_negative_universe"] == 1
    assert manifest["stats"]["sample_target_item_count"] == 2
    assert manifest["stats"]["raw_target_occurrence_count"] == 2
    assert manifest["stats"]["eligible_target_occurrence_count"] == 2
    assert manifest["stats"]["excluded_target_occurrence_count"] == 0
    assert manifest["stats"]["sample_target_items_in_training_universe_count"] == 2
    assert manifest["stats"]["sample_target_items_missing_training_universe_count"] == 0
    assert manifest["stats"]["sample_target_items_in_negative_universe_count"] == 1
    assert manifest["stats"]["sample_target_items_outside_negative_universe_count"] == 1
    assert manifest["stats"]["retrieval_item_universe_available"] is False
    assert manifest["stats"]["retrieval_item_universe_coverage_status"] == "phase1_not_built"
    assert manifest["stats"]["eval_target_universe_available"] is False
    assert manifest["stats"]["eval_target_universe_coverage_status"] == "phase1_not_built"
    assert manifest["stats"]["training_item_universe_item_count"] == 4
    assert manifest["stats"]["training_item_universe_positive_target_count"] == 2
    assert manifest["stats"]["training_item_universe_metadata_item_count"] == 4
    assert manifest["stats"]["training_item_universe_target_items_missing_p1_quality"] == 0

    leakage = json.loads((output_dir / "leakage_audit.json").read_text(encoding="utf-8"))
    assert leakage["valid_used"] is False
    assert leakage["test_used"] is False
    assert leakage["holdout_used"] is False
    assert leakage["oracle_used"] is False
    assert leakage["embedding_or_index_used"] is False
    assert leakage["negative_universe_sources"] == [str(paths["item_quality_profile"]), str(paths["item_frequency_train"])]


def test_two_tower_method_dataset_builds_identical_samples_for_same_input(tmp_path: Path) -> None:
    paths = _write_fixture(tmp_path)

    for output_name in ("deterministic_a", "deterministic_b"):
        build_pool500_two_tower_method_dataset(
            clean_manifest_path=paths["clean_manifest"],
            governance_manifest_path=paths["governance_manifest"],
            output_dir=tmp_path / output_name,
            limit_users=2,
            max_samples=10,
            negative_ratio=2,
            max_items_per_user=3,
            overwrite=True,
            enforce_venv=False,
        )

    first_samples = _read_jsonl(tmp_path / "deterministic_a" / "two_tower_train_samples.jsonl")
    second_samples = _read_jsonl(tmp_path / "deterministic_b" / "two_tower_train_samples.jsonl")
    assert first_samples == second_samples


def test_two_tower_method_dataset_uses_multiple_negative_items(tmp_path: Path) -> None:
    paths = _write_fixture(tmp_path)

    manifest = build_pool500_two_tower_method_dataset(
        clean_manifest_path=paths["clean_manifest"],
        governance_manifest_path=paths["governance_manifest"],
        output_dir=tmp_path / "diverse_negatives",
        limit_users=2,
        max_samples=10,
        negative_ratio=2,
        max_items_per_user=3,
        overwrite=True,
        enforce_venv=False,
    )

    samples = _read_jsonl(tmp_path / "diverse_negatives" / "two_tower_train_samples.jsonl")
    used_negatives = {item for sample in samples for item in sample["negative_item_ids"]}
    assert used_negatives == {"neg_a", "neg_b", "neg_c"}
    assert manifest["stats"]["used_negative_distinct_item_count"] == 3
    assert manifest["stats"]["used_negative_item_occurrence_count"] == 4
    assert manifest["stats"]["negative_item_usage_top1_count"] == 2
    assert manifest["stats"]["negative_item_count_under_requested_count"] == 0


def test_two_tower_phase1_universe_definitions_freeze_negative_semantics(tmp_path: Path) -> None:
    paths = _write_fixture(tmp_path)

    manifest = build_pool500_two_tower_method_dataset(
        clean_manifest_path=paths["clean_manifest"],
        governance_manifest_path=paths["governance_manifest"],
        output_dir=tmp_path / "phase1_universe",
        limit_users=2,
        max_samples=10,
        negative_ratio=2,
        max_items_per_user=3,
        overwrite=True,
        enforce_venv=False,
    )

    universes = manifest["universe_definitions"]
    assert set(universes) == {
        "schema_version",
        "phase",
        "training_item_universe",
        "retrieval_item_universe",
        "global_negative_universe",
        "per_user_negative_universe_policy",
        "per_example_negative_universe_policy",
        "eval_target_universe",
        "eligible_target_universe",
    }
    assert universes["schema_version"] == "pool500_two_tower_phase1_universe_definitions_v1"
    assert universes["phase"] == "phase1_manifest_only"
    assert universes["training_item_universe"] == {
        "available": True,
        "artifact": "training_item_universe.jsonl",
        "policy": "negative_universe_plus_sampled_train_sequence_targets",
    }
    assert universes["global_negative_universe"] == {
        "available": True,
        "artifact": "negative_item_universe.jsonl",
        "policy": "p1_item_quality_profile_v2_embedding_ready_joined_with_item_frequency_train",
    }
    assert universes["per_user_negative_universe_policy"] == {
        "available": True,
        "policy": "global_negative_universe_minus_user_known_history_and_current_target",
    }
    assert universes["per_example_negative_universe_policy"] == {
        "available": True,
        "policy": "deterministic_diversified_rotated_negatives_after_per_user_exclusions",
    }
    assert universes["retrieval_item_universe"] == {
        "available": False,
        "reason": "phase1_not_built",
        "candidate_generation_allowed": False,
    }
    assert universes["eval_target_universe"] == {
        "available": False,
        "policy": "phase1_not_built",
        "reason": "phase1_not_built",
    }
    assert universes["eligible_target_universe"] == {
        "available": True,
        "policy": "sampled_train_sequence_targets_only",
    }

    samples = _read_jsonl(tmp_path / "phase1_universe" / "two_tower_train_samples.jsonl")
    assert samples
    for sample in samples:
        excluded_items = set(sample["history_items"]) | {sample["target_item"]}
        assert excluded_items.isdisjoint(sample["negative_item_ids"])


def test_two_tower_phase1_denominator_and_target_coverage_stats_are_explicit(tmp_path: Path) -> None:
    paths = _write_fixture(tmp_path)

    manifest = build_pool500_two_tower_method_dataset(
        clean_manifest_path=paths["clean_manifest"],
        governance_manifest_path=paths["governance_manifest"],
        output_dir=tmp_path / "phase1_stats",
        limit_users=2,
        max_samples=10,
        negative_ratio=2,
        overwrite=True,
        enforce_venv=False,
    )

    stats = manifest["stats"]
    assert stats["raw_target_occurrence_count"] == 2
    assert stats["eligible_target_occurrence_count"] == 2
    assert stats["excluded_target_occurrence_count"] == 0
    assert stats["raw_target_occurrence_count"] == stats["eligible_target_occurrence_count"] + stats["excluded_target_occurrence_count"]
    assert stats["sample_target_items_in_training_universe_count"] == 2
    assert stats["sample_target_items_missing_training_universe_count"] == 0
    assert stats["sample_target_items_in_negative_universe_count"] == 1
    assert stats["sample_target_items_outside_negative_universe_count"] == 1
    assert stats["sample_target_occurrences_in_negative_universe_count"] == 1
    assert stats["sample_target_occurrences_outside_negative_universe_count"] == 1
    assert stats["retrieval_item_universe_available"] is False
    assert stats["retrieval_item_universe_coverage_status"] == "phase1_not_built"
    assert stats["eval_target_universe_available"] is False
    assert stats["eval_target_universe_coverage_status"] == "phase1_not_built"


def test_two_tower_phase1_manifest_makes_no_candidate_ranking_promotion_ready_claims(tmp_path: Path) -> None:
    paths = _write_fixture(tmp_path)

    manifest = build_pool500_two_tower_method_dataset(
        clean_manifest_path=paths["clean_manifest"],
        governance_manifest_path=paths["governance_manifest"],
        output_dir=tmp_path / "phase1_guardrails",
        limit_users=2,
        max_samples=4,
        negative_ratio=1,
        overwrite=True,
        enforce_venv=False,
    )

    assert manifest["candidate_generation_allowed"] is False
    assert manifest["ranking_input_replacement_allowed"] is False
    assert manifest["pool1000_allowed"] is False
    assert manifest["promotion_allowed"] is False
    assert manifest["final_pool500_ready_claimed"] is False
    assert manifest["retrieval_item_universe_available"] is False
    assert manifest["eval_target_universe_available"] is False
    assert set(manifest["outputs"]) == {"two_tower_train_samples", "negative_item_universe", "training_item_universe", "method_dataset_manifest", "leakage_audit"}
    assert not _contains_key(manifest, FORBIDDEN_FIELDS)


def test_two_tower_method_dataset_smoke_tier_applies_smoke_limits(tmp_path: Path) -> None:
    paths = _write_fixture(tmp_path)

    manifest = build_pool500_two_tower_method_dataset(
        clean_manifest_path=paths["clean_manifest"],
        governance_manifest_path=paths["governance_manifest"],
        output_dir=tmp_path / "smoke",
        scale_tier="smoke",
        overwrite=True,
        enforce_venv=False,
    )

    assert manifest["resource_scale_policy"]["scale_tier"] == "smoke"
    assert manifest["limits"] == {
        "limit_users": 500,
        "limit_interactions": 0,
        "max_samples": 20_000,
        "negative_ratio": 3,
        "max_items_per_user": 30,
        "min_free_bytes": 0,
    }
    assert manifest["limits"]["max_samples"] != manifest["resource_scale_policy"]["scale_tiers"]["local_formal"]["max_samples"]


def test_two_tower_method_dataset_smoke_tier_preserves_explicit_overrides(tmp_path: Path) -> None:
    paths = _write_fixture(tmp_path)

    manifest = build_pool500_two_tower_method_dataset(
        clean_manifest_path=paths["clean_manifest"],
        governance_manifest_path=paths["governance_manifest"],
        output_dir=tmp_path / "smoke_overrides",
        scale_tier="smoke",
        limit_users=2,
        max_samples=7,
        negative_ratio=1,
        max_items_per_user=2,
        overwrite=True,
        enforce_venv=False,
    )

    assert manifest["limits"]["limit_users"] == 2
    assert manifest["limits"]["max_samples"] == 7
    assert manifest["limits"]["negative_ratio"] == 1
    assert manifest["limits"]["max_items_per_user"] == 2
    assert manifest["resource_scale_policy"]["scale_tier"] == "smoke"


def test_two_tower_method_dataset_resource_caps_apply(tmp_path: Path) -> None:
    paths = _write_fixture(tmp_path)

    manifest = build_pool500_two_tower_method_dataset(
        clean_manifest_path=paths["clean_manifest"],
        governance_manifest_path=paths["governance_manifest"],
        output_dir=tmp_path / "capped",
        limit_users=1,
        limit_interactions=1,
        max_samples=1,
        negative_ratio=1,
        max_items_per_user=2,
        overwrite=True,
        enforce_venv=False,
    )

    samples = _read_jsonl(tmp_path / "capped" / "two_tower_train_samples.jsonl")
    assert len(samples) == 1
    assert len(samples[0]["negative_item_ids"]) == 1
    expected_limits = {
        "limit_users": 1,
        "limit_interactions": 1,
        "max_samples": 1,
        "negative_ratio": 1,
        "max_items_per_user": 2,
        "min_free_bytes": 0,
    }
    assert manifest["limits"] == expected_limits
    assert manifest["resource_scale_policy"]["limits"] == expected_limits
    assert manifest["resource_scale_policy"]["scale_tiers"]["local_formal"] != expected_limits
    assert "min_free_bytes" not in manifest["resource_scale_policy"]["scale_tiers"]["local_formal"]
    assert manifest["resource_scale_policy"]["p2_contract_scope"] == "method_dataset_only"
    assert manifest["stats"]["eligible_user_count"] == 1
    assert manifest["stats"]["positive_interactions_seen"] == 1
    assert manifest["stats"]["target_items_skipped_not_in_negative_universe"] == 0
    assert manifest["stats"]["train_sample_count"] == 1


def test_two_tower_method_dataset_blocks_missing_v2_item_bucket(tmp_path: Path) -> None:
    paths = _write_fixture(tmp_path)
    rows = _read_jsonl(paths["item_quality_profile"])
    rows[0].pop("quality_bucket_v2")
    _write_jsonl(paths["item_quality_profile"], rows)

    with pytest.raises(ValueError, match="quality_bucket_v2"):
        build_pool500_two_tower_method_dataset(
            clean_manifest_path=paths["clean_manifest"],
            governance_manifest_path=paths["governance_manifest"],
            output_dir=tmp_path / "missing_v2",
            limit_users=2,
            overwrite=True,
            enforce_venv=False,
        )


def test_two_tower_method_dataset_blocks_missing_p1_profiles(tmp_path: Path) -> None:
    paths = _write_fixture(tmp_path)
    paths["item_quality_profile"].unlink()

    with pytest.raises(FileNotFoundError):
        build_pool500_two_tower_method_dataset(
            clean_manifest_path=paths["clean_manifest"],
            governance_manifest_path=paths["governance_manifest"],
            output_dir=tmp_path / "missing_profile",
            limit_users=2,
            overwrite=True,
            enforce_venv=False,
        )


def test_two_tower_method_dataset_has_no_forbidden_imports_or_fields() -> None:
    source_path = Path("D:/sinrotic_code/python_project/summer/RS_agent/rs_lab/experiments/recall/build_pool500_two_tower_method_dataset.py")
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    forbidden_import_fragments = (
        "pool500.methods.two_tower.builder",
        "VectorIndex",
        "vector_index",
        "faiss",
        "source_index_manifest",
        "build_two_tower_source_index",
    )
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            imported = [node.module or "", *(alias.name for alias in node.names)]
        else:
            continue
        payload = " ".join(imported)
        assert not any(fragment in payload for fragment in forbidden_import_fragments)

    source_text = source_path.read_text(encoding="utf-8")
    assert "build_two_tower_method_source" not in source_text
    assert "load_two_tower_index" not in source_text


def test_formal_train_only_v1_artifacts_record_guarded_dataset_intent() -> None:
    manifest_path = FORMAL_DATASET_DIR / "method_dataset_manifest.json"
    if not manifest_path.is_file():
        pytest.skip("formal train_only_v1 method dataset artifact is not present")

    manifest = _read_json(manifest_path)
    assert manifest["schema_version"] == "pool500_two_tower_method_dataset_v1"
    assert manifest["status"] == "PASS"
    assert manifest["method"] == "two_tower"
    assert manifest["dataset_role"] == "train_only_two_tower_method_dataset"
    assert manifest["train_only"] is True
    assert manifest["resource_scale_policy"]["scale_tier"] == "local_formal"
    assert manifest["resource_scale_policy"]["selection_strategy"]["sequence_contract"] == "future_history_items_to_target_item"
    assert set(manifest["outputs"]) == {"two_tower_train_samples", "negative_item_universe", "training_item_universe", "method_dataset_manifest", "leakage_audit"}
    assert {path.name for path in FORMAL_DATASET_DIR.iterdir()} == OUTPUT_WHITELIST
    assert manifest["candidate_generation_allowed"] is False
    assert manifest["ranking_input_replacement_allowed"] is False
    assert manifest["pool1000_allowed"] is False
    assert manifest["promotion_allowed"] is False
    assert manifest["final_pool500_ready_claimed"] is False
    boundary = manifest["data_usage_boundary"]
    assert boundary["diagnostic_only"] is True
    assert boundary["candidate_generation_allowed"] is False
    assert boundary["ranking_input_replacement_allowed"] is False
    assert boundary["promotion_allowed"] is False
    assert boundary["final_pool500_ready_claimed"] is False
    assert not _contains_key(manifest, FORBIDDEN_FIELDS)
    assert "READY" not in json.dumps(manifest, ensure_ascii=False)
    _assert_no_forbidden_artifact_paths(manifest)


def test_formal_train_only_v1_artifacts_audit_two_tower_sample_contracts() -> None:
    manifest_path = FORMAL_DATASET_DIR / "method_dataset_manifest.json"
    if not manifest_path.is_file():
        pytest.skip("formal train_only_v1 method dataset artifact is not present")

    manifest = _read_json(manifest_path)
    stats = manifest["stats"]
    assert stats["train_sample_count"] == 751574
    assert stats["negative_universe_item_count"] == 866802
    assert stats["training_item_universe_item_count"] == 889431
    assert stats["negative_item_count_min"] == stats["negative_item_count_max"] == stats["negative_ratio_requested"] == 5
    assert stats["negative_item_count_under_requested_count"] == 0
    assert stats["used_negative_distinct_item_count"] > 800000
    assert stats["used_negative_item_coverage_ratio"] > 0.2
    assert stats["negative_item_usage_top10_share"] < 0.001
    assert stats["sample_target_items_missing_training_universe_count"] == 0
    assert stats["training_item_universe_positive_target_metadata_incomplete_count"] == 0
    assert stats["training_item_universe_metadata_item_count"] == stats["training_item_universe_item_count"]
    assert stats["training_item_universe_target_items_missing_p1_quality"] == 0
    assert stats["training_item_universe_target_items_missing_frequency"] == 0

    sample_rows = _read_first_jsonl(Path(manifest["outputs"]["two_tower_train_samples"]), limit=1000)
    assert sample_rows
    for row in sample_rows:
        assert row["history_items"]
        assert row["target_item"] == row["positive_item_id"]
        assert row["target_item_source"] == "train_only_user_sequence"
        assert row["target_item"] not in row["history_items"]
        assert row["target_item"] not in row["negative_item_ids"]
        assert len(row["negative_item_ids"]) == 5
        assert set(row["negative_item_ids"]).isdisjoint(row["history_items"])


def test_diagnostic_loop_and_formal_dataset_keep_separate_intents_and_vocab_bounds() -> None:
    formal_manifest_path = FORMAL_DATASET_DIR / "method_dataset_manifest.json"
    diagnostic_manifest_path = DIAGNOSTIC_LOOP_DIR / "diagnostic_manifest.json"
    if not formal_manifest_path.is_file() or not diagnostic_manifest_path.is_file():
        pytest.skip("formal dataset or diagnostic loop artifact is not present")

    formal_manifest = _read_json(formal_manifest_path)
    diagnostic_manifest = _read_json(diagnostic_manifest_path)
    assert formal_manifest["dataset_role"] == "train_only_two_tower_method_dataset"
    assert formal_manifest["resource_scale_policy"]["scale_tier"] == "local_formal"
    assert diagnostic_manifest["schema_version"] == "pool500_two_tower_diagnostic_loop_v1"
    assert diagnostic_manifest["diagnostic_only"] is True
    assert diagnostic_manifest["split_scope"] == "train_only"
    assert diagnostic_manifest["method_dataset_manifest_path"] == str(formal_manifest_path.resolve())
    assert diagnostic_manifest["training"]["limit_users"] == 200
    assert diagnostic_manifest["diagnostic_topk_row_count"] == 10000
    assert diagnostic_manifest["source_index_row_count"] <= diagnostic_manifest["training"]["limit_users"] * 6
    assert diagnostic_manifest["retrieval_metrics"]["all_target_recall_at_20"] == 0.294359
    assert diagnostic_manifest["retrieval_metrics"]["all_target_recall_at_50"] == 0.434872
    assert diagnostic_manifest["candidate_generation_allowed"] is False
    assert diagnostic_manifest["ranking_input_replacement_allowed"] is False
    assert diagnostic_manifest["promotion_allowed"] is False
    assert diagnostic_manifest["final_pool500_ready_claimed"] is False
    _assert_no_forbidden_artifact_paths(formal_manifest)


def test_two_tower_method_dataset_cli(tmp_path: Path) -> None:
    paths = _write_fixture(tmp_path)
    output_dir = tmp_path / "cli_output"

    result = subprocess.run(
        [
            str(PYTHON),
            "-m",
            "rs_lab.experiments.recall.build_pool500_two_tower_method_dataset",
            "--clean-manifest",
            str(paths["clean_manifest"]),
            "--governance-manifest",
            str(paths["governance_manifest"]),
            "--output-dir",
            str(output_dir),
            "--limit-users",
            "2",
            "--limit-interactions",
            "2",
            "--max-samples",
            "2",
            "--negative-ratio",
            "1",
            "--max-items-per-user",
            "2",
            "--overwrite",
            "--skip-venv-check",
        ],
        check=True,
        capture_output=True,
        text=True,
        cwd="D:/sinrotic_code/python_project/summer/RS_agent",
    )

    payload = json.loads(result.stdout)
    assert payload["status"] == "PASS"
    assert Path(payload["method_dataset_manifest"]).is_file()
    assert payload["train_sample_count"] <= 2
    assert payload["negative_universe_item_count"] == 3
    assert payload["training_item_universe_item_count"] >= payload["negative_universe_item_count"]


def _write_fixture(tmp_path: Path) -> dict[str, Path]:
    clean_dir = tmp_path / "clean"
    governance_dir = tmp_path / "governance"
    clean_dir.mkdir()
    governance_dir.mkdir()

    train_sequences = clean_dir / "user_sequences.train.jsonl"
    _write_jsonl(
        train_sequences,
        [
            {"user_id": "u_tt", "recent_item_sequence": ["pos_a", "neg_a"], "recent_positive_item_sequence": ["pos_a", "neg_a"]},
            {"user_id": "u_heavy", "recent_item_sequence": ["pos_c", "seen_neg"], "recent_positive_item_sequence": ["pos_c", "seen_neg"]},
            {"user_id": "u_fallback", "recent_item_sequence": ["pos_d"], "recent_positive_item_sequence": ["pos_d"]},
        ],
    )
    canonical_items = clean_dir / "canonical_items.jsonl"
    _write_jsonl(
        canonical_items,
        [
            {"parent_asin": item_id, "title_clean": f"Title {item_id}", "main_category": "Office", "category": "Office Supplies"}
            for item_id in ["pos_a", "neg_a", "pos_c", "seen_neg", "pos_d", "neg_b", "neg_c"]
        ],
    )
    clean_manifest = clean_dir / "manifest.json"
    clean_manifest.write_text(json.dumps({"train_user_sequences_path": str(train_sequences), "canonical_items_path": str(canonical_items)}, ensure_ascii=False), encoding="utf-8")

    user_quality_profile = governance_dir / "user_quality_profile.jsonl"
    _write_jsonl(
        user_quality_profile,
        [
            {"user_id": "u_tt", "quality_bucket": "two_tower_train_eligible", "quality_bucket_v2": "sequence_sufficient", "eligible_for_two_tower": True},
            {"user_id": "u_heavy", "quality_bucket": "heavy_cf_eligible", "quality_bucket_v2": "collaborative_rich", "eligible_for_two_tower": True},
            {"user_id": "u_fallback", "quality_bucket": "fallback_only", "quality_bucket_v2": "fallback_only", "eligible_for_two_tower": False},
        ],
    )
    item_quality_profile = governance_dir / "item_quality_profile.jsonl"
    _write_jsonl(
        item_quality_profile,
        [
            {"parent_asin": "neg_a", "quality_bucket_v2": "embedding_ready", "positive_event_count": 9, "unique_positive_user_count": 3, "global_pop_rank": 1},
            {"parent_asin": "neg_b", "quality_bucket_v2": "embedding_ready", "positive_event_count": 8, "unique_positive_user_count": 3, "global_pop_rank": 2},
            {"parent_asin": "neg_c", "quality_bucket_v2": "embedding_ready", "positive_event_count": 7, "unique_positive_user_count": 2, "global_pop_rank": 3},
            {"parent_asin": "seen_neg", "quality_bucket_v2": "low_frequency", "positive_event_count": 1, "unique_positive_user_count": 1, "global_pop_rank": 4},
        ],
    )
    item_frequency_train = governance_dir / "item_frequency_train.jsonl"
    _write_jsonl(
        item_frequency_train,
        [
            {"parent_asin": "neg_a", "frequency": 9, "user_count": 3},
            {"parent_asin": "neg_b", "frequency": 8, "user_count": 3},
            {"parent_asin": "neg_c", "frequency": 7, "user_count": 2},
            {"parent_asin": "seen_neg", "frequency": 1, "user_count": 1},
        ],
    )
    governance_manifest = governance_dir / "manifest.json"
    governance_manifest.write_text(
        json.dumps(
            {
                "schema_version": "train_only_data_governance_v1",
                "status": "PASS",
                "train_only": True,
                "artifacts": {
                    "user_quality_profile": str(user_quality_profile),
                    "item_quality_profile": str(item_quality_profile),
                    "item_frequency_train": str(item_frequency_train),
                },
                "derived_dataset_policies": {
                    "two_tower": {
                        "train_only_inputs": ["user_quality_profile.jsonl", "item_quality_profile.jsonl", "item_frequency_train.jsonl", "user_sequences.train.jsonl"],
                    }
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return {
        "clean_manifest": clean_manifest,
        "governance_manifest": governance_manifest,
        "user_quality_profile": user_quality_profile,
        "item_quality_profile": item_quality_profile,
        "item_frequency_train": item_frequency_train,
    }


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _read_first_jsonl(path: Path, *, limit: int) -> list[dict[str, Any]]:
    rows = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
            if len(rows) >= limit:
                break
    return rows


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")


def _contains_key(value: Any, keys: set[str]) -> bool:
    if isinstance(value, dict):
        return any(key in keys or _contains_key(nested, keys) for key, nested in value.items())
    if isinstance(value, list):
        return any(_contains_key(nested, keys) for nested in value)
    return False


def _assert_no_forbidden_artifact_paths(value: Any) -> None:
    for text in _walk_strings(value):
        normalized = text.replace("\\", "/").lower()
        if "/" not in normalized and not normalized.endswith((".json", ".jsonl")):
            continue
        parts = set(Path(normalized).parts)
        assert parts.isdisjoint(FORBIDDEN_PATH_TOKENS), text


def _walk_strings(value: Any):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from _walk_strings(str(key))
            yield from _walk_strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_strings(item)
