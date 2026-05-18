from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from rs_core.workflow.full_data_pool500_route_gate import CANONICAL_SOURCES

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = ROOT / "configs" / "recall" / "pool500_method_registry.json"

REQUIRED_DATASET_CONTRACT_KEYS = {
    "contract_role",
    "policy_type",
    "custom_dataset_required",
    "dataset_manifest_path",
    "allowed_input_scopes",
    "forbidden_input_scopes",
    "generation_dataset_scope",
    "readiness_evaluation_scope",
    "eligible_user_policy",
    "final_merge_scope",
    "promotion_policy",
    "readiness_artifacts",
    "status",
    "notes",
}

EXPECTED_POLICIES = {
    "category": ("default_dataset_policy", False),
    "popular": ("default_dataset_policy", False),
    "swing_recall": ("guarded_ready_policy", False),
    "usercf_recall": ("custom_dataset_policy", True),
    "itemcf_weak": ("custom_dataset_policy", True),
    "itemcf_strong": ("custom_dataset_policy", True),
    "semantic": ("deferred_evidence_policy", False),
    "semantic_title_category_expansion": ("deferred_evidence_policy", False),
    "co_visit_fallback_repair": ("deferred_evidence_policy", False),
    "two_tower": ("deferred_evidence_policy", False),
}

FORBIDDEN_EVIDENCE_TOKENS = {
    "holdout",
    "valid",
    "test",
    "clean_10000",
    "lopo",
    "youtube_dnn",
}

SCOPE_FIELDS_FORBIDDEN_FROM_EVIDENCE = {
    "dataset_manifest_path",
    "allowed_input_scopes",
    "generation_dataset_scope",
    "readiness_evaluation_scope",
    "final_merge_scope",
}


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


def test_pool500_registry_dataset_contract_shape_and_status(sources: dict[str, dict[str, Any]]) -> None:
    for source_name, source_config in sources.items():
        dataset_contract = source_config.get("dataset_contract")

        assert isinstance(dataset_contract, dict), source_name
        assert REQUIRED_DATASET_CONTRACT_KEYS <= set(dataset_contract), source_name
        assert dataset_contract["status"] == source_config["status"], source_name


def test_pool500_registry_dataset_contract_policy_classification(sources: dict[str, dict[str, Any]]) -> None:
    assert set(EXPECTED_POLICIES) == CANONICAL_SOURCES

    for source_name, source_config in sources.items():
        expected_policy_type, expected_custom_dataset_required = EXPECTED_POLICIES[source_name]
        dataset_contract = source_config["dataset_contract"]

        assert dataset_contract["policy_type"] == expected_policy_type, source_name
        assert dataset_contract["custom_dataset_required"] is expected_custom_dataset_required, source_name


def test_pool500_registry_dataset_contract_forbidden_evidence_boundary(sources: dict[str, dict[str, Any]]) -> None:
    for source_name, source_config in sources.items():
        dataset_contract = source_config["dataset_contract"]
        forbidden_input_scopes = {_normalize_scope(value) for value in dataset_contract["forbidden_input_scopes"]}

        assert FORBIDDEN_EVIDENCE_TOKENS <= forbidden_input_scopes, source_name

        for field in SCOPE_FIELDS_FORBIDDEN_FROM_EVIDENCE:
            values = _flatten_scope_values(dataset_contract[field])
            forbidden_matches = sorted(
                value
                for value in values
                if any(token in _normalize_scope(value) for token in FORBIDDEN_EVIDENCE_TOKENS)
            )
            assert forbidden_matches == [], f"{source_name}.{field}: {forbidden_matches}"


def test_pool500_registry_latest_diagnostic_batch_is_stop_only(registry: dict[str, Any]) -> None:
    batch = registry["latest_diagnostic_batch"]

    assert batch["limit_users"] == 500
    assert batch["decision"] == "STOP"
    assert batch["underfilled_user_count"] > 0
    assert batch["underfilled_user_ratio"] == 1.0
    assert batch["candidate_rows"] > 0
    assert batch["ranking_input_replacement_allowed"] is False
    assert batch["pool1000_allowed"] is False
    assert batch["manifest_path"].endswith("manifest.json")
    assert batch["ready_source_stoploss_audit_path"].endswith("ready_source_stoploss_audit.json")
    assert batch["diagnostic_source_contribution_path"].endswith("diagnostic_source_contribution.json")
    assert (ROOT / batch["manifest_path"]).is_file()
    assert (ROOT / batch["ready_source_stoploss_audit_path"]).is_file()
    assert (ROOT / batch["diagnostic_source_contribution_path"]).is_file()


def test_pool500_registry_readiness_groups_are_fixed(sources: dict[str, dict[str, Any]]) -> None:
    grouped: dict[str, set[str]] = {"READY": set(), "DIAGNOSTIC_ONLY": set(), "DEFERRED": set()}
    for source_name, source_config in sources.items():
        grouped[source_config["status"]].add(source_name)

    assert grouped == {
        "READY": {"category", "popular", "swing_recall"},
        "DIAGNOSTIC_ONLY": {"usercf_recall", "itemcf_weak", "itemcf_strong"},
        "DEFERRED": {"semantic", "semantic_title_category_expansion", "co_visit_fallback_repair", "two_tower"},
    }


def test_pool500_registry_dataset_contract_blocks_promotion(sources: dict[str, dict[str, Any]]) -> None:
    for source_name, source_config in sources.items():
        dataset_contract = source_config["dataset_contract"]
        promotion_policy = dataset_contract["promotion_policy"]

        assert promotion_policy["auto_promotion_allowed"] is False, source_name
        assert promotion_policy["ranking_input_replacement_allowed"] is False, source_name
        assert promotion_policy["pool1000_allowed"] is False, source_name

        if source_config["status"] in {"DIAGNOSTIC_ONLY", "DEFERRED"}:
            status_and_policy_values = [dataset_contract["status"], *promotion_policy.values()]
            ready_language = [
                value
                for value in status_and_policy_values
                if isinstance(value, str) and _contains_ready_or_promotable_language(value)
            ]
            assert ready_language == [], source_name


def _flatten_scope_values(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    return [str(value)]


def _normalize_scope(value: Any) -> str:
    return str(value).replace("\\", "/").lower()


def _contains_ready_or_promotable_language(value: str) -> bool:
    normalized = value.lower()
    return any(token in normalized for token in ("ready", "promotable", "promote"))
