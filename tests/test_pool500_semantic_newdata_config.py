from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from rs_lab.experiments.recall.pool500.common.source_layout import REQUIRED_SOURCE_OUTPUTS
from scripts.experiments.recall.pool500 import run_pool500_method_source as runner

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[1]
CONFIG_ROOT = ROOT / "configs" / "recall" / "full_data_pool500"
RUNNER = ROOT / "scripts" / "experiments" / "recall" / "pool500" / "run_pool500_method_source.py"
OUTPUT_ROOT = "outputs/recall/pool500_method_sources_newdata"
RECENT2Y_INPUTS = {
    "clean_manifest": "data/processed/amazon_2023_recall_recent_2y_1m_3m/manifest.json",
    "lightweight_views_manifest": "data/processed/amazon_2023_recall_recent_2y_1m_3m/recall_views/manifest.json",
}
ELIGIBLE_MANIFESTS = {
    "recent2y_smoke": "outputs/recall/pool500_method_sources_newdata/eligible_users_semantic_recent2y_smoke_v1/eligible_user_manifest.json",
    "recent2y_formal": "outputs/recall/pool500_method_sources_newdata/eligible_users_semantic_recent2y_formal_v1/eligible_user_manifest.json",
}
OLD_DEFAULT_INPUTS = {
    "clean_manifest": "data/processed/amazon_2023_recall_clean_full/manifest.json",
    "lightweight_views_manifest": "data/processed/amazon_2023_recall_views_full_lightweight/manifest.json",
    "eligible_user_manifest": "outputs/recall/pool500_main_route_direct_recall_full_promoted/eligible_user_manifest.json",
}
FORBIDDEN_SCOPES = {"holdout", "valid", "test", "LOPO", "oracle", "eval_label", "clean_10000", "pool1000"}
SOURCES = ("semantic", "semantic_title_category_expansion")


def _load_source_config(source: str) -> dict:
    return yaml.safe_load((CONFIG_ROOT / source / "source_config.yaml").read_text(encoding="utf-8"))


def _load_dataset_policy(source: str) -> dict:
    return yaml.safe_load((CONFIG_ROOT / source / "dataset_policy.yaml").read_text(encoding="utf-8"))


def _load_required_manifest(source: str) -> dict:
    return json.loads((CONFIG_ROOT / f"{source}_required_artifacts_manifest.json").read_text(encoding="utf-8"))


def _load_eligible_manifest(tier: str) -> dict:
    return json.loads((ROOT / ELIGIBLE_MANIFESTS[tier]).read_text(encoding="utf-8"))


@pytest.mark.parametrize("source", SOURCES)
def test_semantic_required_artifact_manifest_declares_newdata_smoke_contract(source: str) -> None:
    manifest = _load_required_manifest(source)

    assert manifest["source"] == source
    assert manifest["canonical_source"] == source
    assert manifest["source_status"] == "TARGET_SLICE_DIAGNOSTIC"
    assert manifest["dataset_scope"] == "newdata_train_only_pool500_smoke"
    assert manifest["required_outputs"] == list(REQUIRED_SOURCE_OUTPUTS)
    assert set(manifest["input_contract"]["forbidden_scopes"]) >= {"holdout", "valid", "test", "clean_10000", "LOPO", "pool1000"}
    assert manifest["input_contract"]["train_only"] is True
    assert all(value is False for value in manifest["governance"].values())
    assert "target_slice_diagnostic_status_only" in manifest["acceptance_checks"]


@pytest.mark.parametrize("source", SOURCES)
@pytest.mark.parametrize("tier", ("recent2y_smoke", "recent2y_formal"))
def test_semantic_recent2y_tiers_use_newdata_paths_not_old_defaults(source: str, tier: str) -> None:
    config = _load_source_config(source)
    merged = runner._merge_runner_config(config, tier, {})

    assert merged["output_root"] == OUTPUT_ROOT
    assert merged["input_contract"]["train_only"] is True
    assert merged["input_contract"]["use_existing_recall_views_with_audit_first"] is True
    for key, expected_path in RECENT2Y_INPUTS.items():
        assert merged["input_contract"][key] == expected_path
        assert merged["input_contract"][key] != OLD_DEFAULT_INPUTS[key]
    assert merged["input_contract"]["eligible_user_manifest"] == ELIGIBLE_MANIFESTS[tier]
    assert merged["input_contract"]["eligible_user_manifest"] != OLD_DEFAULT_INPUTS["eligible_user_manifest"]


@pytest.mark.parametrize(
    ("source", "expected_selection_mode", "expected_formal_config"),
    [
        (
            "semantic",
            "bm25f_field_weighted",
            {
                "limit_users": 10000,
                "seed_window": 50,
                "per_user": 80,
                "per_seed": 40,
                "per_token_item_limit": 300,
                "max_candidate_items": 5000,
                "per_user_candidate_pool_limit": 300,
                "selection_mode": "bm25f_field_weighted",
                "candidate_metadata_policy": "lean_reference",
            },
        ),
        (
            "semantic_title_category_expansion",
            "semantic_title_category_channel",
            {
                "limit_users": 50000,
                "target_user_offset": 0,
                "target_user_limit": 50000,
                "shard_id": None,
                "shard_count": None,
                "checkpoint_every_users": 500,
                "seed_window": 50,
                "per_user": 120,
                "per_seed": 60,
                "per_token_item_limit": 2000,
                "max_candidate_items": 200000,
                "selection_mode": "semantic_title_category_channel",
                "channel_status": "folded_into_semantic_bm25f_title_category_channel",
                "independent_expansion_enabled": False,
            },
        ),
    ],
)
def test_semantic_recent2y_tiers_keep_source_selection_mode_and_limits(
    source: str,
    expected_selection_mode: str,
    expected_formal_config: dict,
) -> None:
    config = _load_source_config(source)
    smoke = runner._merge_runner_config(config, "recent2y_smoke", {})
    formal = runner._merge_runner_config(config, "recent2y_formal", {})

    expected_smoke_config = {
        "limit_users": 200,
        "seed_window": 20,
        "per_user": 80,
        "per_seed": 40,
        "per_token_item_limit": 1000,
        "max_candidate_items": 30000,
        "selection_mode": expected_selection_mode,
    }
    if source == "semantic_title_category_expansion":
        expected_smoke_config.update({
            "target_user_offset": 0,
            "target_user_limit": None,
            "shard_id": None,
            "shard_count": None,
            "checkpoint_every_users": 500,
            "channel_status": "folded_into_semantic_bm25f_title_category_channel",
            "independent_expansion_enabled": False,
        })
    if source == "semantic":
        bm25f_config = {
            "semantic_score_mode": "bm25f",
            "bm25_k1": 1.2,
            "bm25_b": 0.75,
            "semantic_max_df_ratio": 0.5,
            "generic_tokens": ["and", "the", "with", "for", "from", "item", "product"],
            "field_weights": {
                "title_clean": 3.0,
                "main_category": 2.5,
                "category": 2.0,
                "categories_flat": 1.5,
                "description_text": 0.5,
                "features_text": 0.5,
                "item_text": 0.25,
            },
        }
        expected_smoke_config.update(bm25f_config)
        expected_formal_config.update(bm25f_config)
        expected_smoke_config["candidate_metadata_policy"] = "lean_reference"
    assert smoke["method_config"] == expected_smoke_config
    assert smoke["resource_guard"]["batch_size"] == 50
    assert formal["method_config"] == expected_formal_config
    assert formal["resource_guard"]["batch_size"] == 500
    assert smoke["method_config"]["limit_users"] not in {20, 500}
    assert formal["method_config"]["limit_users"] not in {20, 500}


@pytest.mark.parametrize("tier", ("recent2y_smoke", "recent2y_formal"))
def test_semantic_recent2y_eligible_manifest_schema_and_forbidden_scopes(tier: str) -> None:
    manifest = _load_eligible_manifest(tier)

    assert manifest["dataset_id"] == f"semantic_{tier}_v1"
    assert manifest["source_profiled_user_count"] > 0
    assert set(manifest["source_eligible_bucket_counts"]) >= {"collaborative_rich", "sequence_sufficient", "fallback_only", "cold_start"}
    assert manifest["selection_policy"]["train_only"] is True
    assert manifest["eligible_user_count"] == len(manifest["eligible_user_ids"])
    assert manifest["input_contract"]["train_only"] is True
    assert manifest["input_contract"]["valid_used"] is False
    assert manifest["input_contract"]["test_used"] is False
    assert manifest["input_contract"]["holdout_used"] is False
    assert manifest["input_contract"]["oracle_used"] is False
    assert manifest["input_contract"]["eval_label_used"] is False
    assert manifest["governance"]["ranking_input_replacement_allowed"] is False
    assert manifest["governance"]["promotion_allowed"] is False
    assert manifest["governance"]["pool1000_allowed"] is False
    assert manifest["governance"]["full_pool500_ready_declared"] is False
    assert set(manifest["forbidden_scopes"]) >= FORBIDDEN_SCOPES


@pytest.mark.parametrize(
    ("tier", "expected_count", "expected_buckets"),
    [
        ("recent2y_smoke", 200, {"collaborative_rich": 40, "sequence_sufficient": 100, "fallback_only": 50, "cold_start": 10}),
        ("recent2y_formal", 50000, {"collaborative_rich": 10000, "sequence_sufficient": 30000, "fallback_only": 10000}),
    ],
)
def test_semantic_recent2y_manifest_quotas(tier: str, expected_count: int, expected_buckets: dict[str, int]) -> None:
    manifest = _load_eligible_manifest(tier)

    assert manifest["eligible_user_count"] == expected_count
    assert manifest["eligible_user_bucket_counts"] == expected_buckets
    if tier == "recent2y_formal":
        assert "cold_start" not in manifest["eligible_user_buckets"]
        assert manifest["audit_only_user_bucket_counts"] == {"medium_behavior": 90}


@pytest.mark.parametrize("source", SOURCES)
def test_semantic_recent2y_dataset_policy_uses_only_recent2y_train_only_inputs(source: str) -> None:
    policy = _load_dataset_policy(source)

    assert policy["train_only"] is True
    assert policy["use_existing_recall_views_with_audit_first"] is True
    assert set(policy["forbidden_data_sources"]) >= FORBIDDEN_SCOPES | {"label", "old_10k", "full_lightweight"}
    assert set(policy["required_coverage_audits"]) >= {
        "title_coverage",
        "category_coverage",
        "clean_title_token_coverage",
        "seed_item_metadata_coverage",
        "user_coverage_count",
        "candidate_row_count",
        "candidate_count_p50",
        "candidate_count_p90",
        "candidate_count_max",
    }
    for path in policy["allowed_inputs"]:
        assert "amazon_2023_recall_recent_2y_1m_3m" in path or path in ELIGIBLE_MANIFESTS.values()
        assert "clean_10000" not in path
        assert "pool1000" not in path
        assert "full_lightweight" not in path


@pytest.mark.parametrize("source", SOURCES)
@pytest.mark.parametrize("tier", ("recent2y_smoke", "recent2y_formal"))
def test_runner_dry_run_emits_recent2y_input_contract(source: str, tier: str, tmp_path: Path) -> None:
    command = [
        sys.executable,
        str(RUNNER),
        "--source",
        source,
        "--tier",
        tier,
        "--run-id",
        f"{tier}_unit",
        "--output-root",
        str(tmp_path / "dry_outputs"),
        "--dry-run",
    ]

    completed = subprocess.run(command, cwd=ROOT, check=True, capture_output=True, text=True)
    payload = json.loads(completed.stdout)

    assert payload["source"] == source
    assert payload["tier"] == tier
    assert payload["contract"]["input_contract"]["clean_manifest"] == RECENT2Y_INPUTS["clean_manifest"]
    assert payload["contract"]["input_contract"]["eligible_user_manifest"] == ELIGIBLE_MANIFESTS[tier]
