from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from rs_core.workflow.full_data_pool500_route_gate import CANONICAL_SOURCES

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = ROOT / "configs" / "recall" / "pool500_method_registry.json"
RECENT_2Y_ROOT = "data/processed/amazon_2023_recall_recent_2y_1m_3m"
RECENT_2Y_GOVERNANCE = f"{RECENT_2Y_ROOT}/train_only_governance/manifest.json"
FORBIDDEN_CURRENT_TOKENS = (
    "amazon_2023_recall_clean_full",
    "amazon_2023_recall_views_full_lightweight",
    "outputs/recall/data_governance/train_only_v1",
    "local_formal",
)


@pytest.fixture(scope="module")
def registry() -> dict[str, Any]:
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def sources(registry: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return registry["sources"]


def test_pool500_registry_sources_match_canonical_sources(sources: dict[str, dict[str, Any]]) -> None:
    assert set(sources) == CANONICAL_SOURCES


def test_pool500_registry_method_docs_exist(sources: dict[str, dict[str, Any]]) -> None:
    for source_name, source_config in sources.items():
        method_doc = source_config.get("method_doc")

        assert method_doc, source_name
        assert (ROOT / method_doc).is_file(), source_name


def test_pool500_registry_declares_recent_2y_smoke_formal_policy(registry: dict[str, Any]) -> None:
    policy = registry["current_method_dataset_policy"]

    assert registry["schema_version"] == "pool500_method_registry_v2_recent_2y_smoke_formal"
    assert registry["scope"] == "pool500_recall_methods_current_recent_2y"
    assert policy["dataset_root"] == RECENT_2Y_ROOT
    assert policy["governance_manifest_path"] == RECENT_2Y_GOVERNANCE
    assert policy["allowed_scale_tiers"] == ["smoke", "formal"]
    assert policy["formal_quantity_policy"] == "agent_managed_no_method_side_fixed_quantity_caps"
    assert policy["full_data_dataset_status"] == "sealed_archived_not_current_method_dataset_origin"
    assert policy["current_registry_excludes_historical_artifact_paths"] is True


def test_pool500_registry_sources_inherit_recent_2y_policy(sources: dict[str, dict[str, Any]]) -> None:
    for source_name, source_config in sources.items():
        current_policy = source_config["current_dataset_policy"]
        contract = source_config["dataset_contract"]

        assert current_policy["dataset_root"] == RECENT_2Y_ROOT, source_name
        assert current_policy["governance_manifest_path"] == RECENT_2Y_GOVERNANCE, source_name
        assert current_policy["allowed_scale_tiers"] == ["smoke", "formal"], source_name
        assert current_policy["formal_quantity_policy"] == "agent_managed_no_method_side_fixed_quantity_caps", source_name
        assert current_policy["full_data_derived_method_datasets"] == "archived_not_current", source_name
        assert contract["policy_type"] == "recent_2y_train_only_current_dataset_policy", source_name
        assert set(contract["scale_tiers"]) == {"smoke", "formal"}, source_name
        assert contract["scale_tiers"]["smoke"]["quantity_policy"] == "small_bounded_smoke", source_name
        assert contract["scale_tiers"]["formal"]["quantity_policy"] == "agent_managed_no_method_side_fixed_quantity_caps", source_name
        assert contract["promotion_policy"] == {
            "auto_promotion_allowed": False,
            "ranking_input_replacement_allowed": False,
            "pool1000_allowed": False,
        }, source_name


def test_pool500_registry_current_entries_do_not_expose_archived_full_data_paths(registry: dict[str, Any]) -> None:
    serialized = json.dumps(registry, ensure_ascii=False).replace("\\", "/").lower()

    for token in FORBIDDEN_CURRENT_TOKENS:
        assert token.lower() not in serialized


def test_pool500_registry_dataset_contract_forbidden_input_scopes(sources: dict[str, dict[str, Any]]) -> None:
    required_forbidden = {"holdout", "valid", "test", "clean_10000", "lopo", "oracle", "eval_label", "pool1000", "full_data_derived_method_dataset"}

    for source_name, source_config in sources.items():
        forbidden = {str(value).lower() for value in source_config["dataset_contract"]["forbidden_input_scopes"]}
        assert required_forbidden <= forbidden, source_name


def test_pool500_registry_custom_dataset_requirements_are_limited_to_model_specific_datasets(sources: dict[str, dict[str, Any]]) -> None:
    expected_custom = {"itemcf_weak", "itemcf_strong", "usercf_recall", "swing_recall", "two_tower"}

    actual_custom = {source for source, config in sources.items() if config["dataset_contract"]["custom_dataset_required"] is True}
    assert actual_custom == expected_custom
