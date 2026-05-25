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
ITEMCF_SCORE_POLICY = "weighted_cooc_cosine_normalized_v1"
ITEMCF_SCORE_FORMULA = "round(weighted_cooc / sqrt(src_user_count * dst_user_count), 6)"
ITEMCF_ACTIVE_USER_PENALTY_POLICY = "round(1 / log1p(filtered_sequence_len), 6)"


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


def test_pool500_registry_contains_no_legacy_capped_route(registry: dict[str, Any]) -> None:
    serialized = json.dumps(registry, ensure_ascii=False)

    assert "capped_unified_train_behavior_dataset" not in serialized


def test_pool500_registry_light_methods_allow_full_train_only_statistics_scan(sources: dict[str, dict[str, Any]]) -> None:
    for source_name in ("category", "popular"):
        contract = sources[source_name]["dataset_contract"]
        policy = contract["input_scale_policy"]

        assert contract["policy_type"] == "default_dataset_policy"
        assert contract["custom_dataset_required"] is False
        assert policy["train_only_full_statistics_scan_allowed"] is True
        assert policy["input_size_cap_required"] is False
        assert policy["default_tier"] == "local_formal"
        assert set(policy["scale_tiers"]) == {"smoke", "diagnostic", "local_formal"}
        assert all(tier["input_size_cap_required"] is False for tier in policy["scale_tiers"].values())
        assert policy["scale_tiers"]["smoke"]["batch_user_limit"] == 500
        assert policy["scale_tiers"]["diagnostic"]["batch_user_limit"] == 5_000
        assert policy["scale_tiers"]["local_formal"]["batch_user_limit"] == "full_pool500_scope"
        assert policy["downstream_controls"] == ["output_cap", "per_user_share_cap"]
        assert policy["input_scope"] == "train_only_full_stats"
        assert policy["selection_policy_version"] == "p2_method_dataset_policy_v1"
        assert policy["selection_strategy"]["policy_name"] == "full_train_only_statistics_with_output_caps_v1"
        assert "full train-only unified statistics" in contract["generation_dataset_scope"]
        assert "no input size cap" in contract["generation_dataset_scope"]


def test_pool500_registry_heavy_methods_define_method_specific_resource_boundaries(sources: dict[str, dict[str, Any]]) -> None:
    expected = {
        "itemcf_weak": ("max_output_users", 300_000),
        "itemcf_strong": ("max_output_users", 200_000),
        "usercf_recall": ("similar_users_top_k", 200),
        "swing_recall": ("max_graph_users", 120_000),
    }

    for source_name, (field, value) in expected.items():
        contract = sources[source_name]["dataset_contract"]
        boundary = contract["method_specific_resource_boundary"]

        assert boundary["input_scope"] == "governance_train_only", source_name
        assert boundary["scale_tier"] == "local_formal_default", source_name
        assert boundary["default_tier"] == "local_formal", source_name
        assert set(boundary["scale_tiers"]) == {"smoke", "diagnostic", "local_formal"}, source_name
        assert boundary["selection_policy_version"] == "p2_method_dataset_policy_v1", source_name
        assert boundary["selection_strategy"]["policy_name"], source_name
        assert boundary[field] == value, source_name
        assert boundary["scale_tiers"]["local_formal"][field] == value, source_name
        assert boundary["scale_tiers"]["smoke"], source_name
        assert boundary["scale_tiers"]["diagnostic"], source_name
        assert boundary["p2_contract_scope"] == "method_dataset_only", source_name
        assert "P2 method dataset" in contract["generation_dataset_scope"], source_name


def test_pool500_registry_itemcf_edge_feature_smoke_contract_is_fixed(sources: dict[str, dict[str, Any]]) -> None:
    expected_smoke_limits = {
        "itemcf_weak": {"max_item_user_freq": 5_000, "min_pair_support": 1, "top_k_per_seed": 100},
        "itemcf_strong": {"max_item_user_freq": 3_000, "min_pair_support": 2, "top_k_per_seed": 100},
    }

    for source_name, expected_limits in expected_smoke_limits.items():
        boundary = sources[source_name]["dataset_contract"]["method_specific_resource_boundary"]
        smoke = boundary["scale_tiers"]["smoke"]

        assert boundary["itemcf_feature_schema"] == "itemcf_edge_features_v1", source_name
        assert boundary["top_k_per_seed"] == 100, source_name
        assert boundary["score_policy"] == ITEMCF_SCORE_POLICY, source_name
        assert boundary["itemcf_score_formula"] == ITEMCF_SCORE_FORMULA, source_name
        assert boundary["active_user_penalty_policy"] == ITEMCF_ACTIVE_USER_PENALTY_POLICY, source_name
        assert boundary["weighted_cooc_feature"] == "weighted_cooc", source_name
        for key, expected_value in expected_limits.items():
            assert smoke[key] == expected_value, source_name
        assert smoke["max_output_users"] == 1_000, source_name
        assert smoke["max_items_per_user"] == 50, source_name


def test_pool500_registry_deferred_methods_have_bounded_method_specific_data_definitions(sources: dict[str, dict[str, Any]]) -> None:
    semantic_definition = sources["semantic_title_category_expansion"]["dataset_contract"]["method_specific_data_definition"]
    co_visit_definition = sources["co_visit_fallback_repair"]["dataset_contract"]["method_specific_data_definition"]

    assert semantic_definition["dataset_name"] == "semantic_seed_metadata_v1"
    assert semantic_definition["max_metadata_rows"] > 0
    assert semantic_definition["seed_window"] > 0
    assert semantic_definition["per_token_item_limit"] > 0
    assert semantic_definition["default_tier"] == "local_formal"
    assert set(semantic_definition["scale_tiers"]) == {"smoke", "diagnostic", "local_formal"}
    assert semantic_definition["scale_tiers"]["local_formal"]["max_metadata_rows"] == semantic_definition["max_metadata_rows"]
    assert semantic_definition["scale_tiers"]["smoke"]["seed_window"] == 20
    assert semantic_definition["p2_contract_scope"] == "method_dataset_only"
    assert semantic_definition["selection_policy_version"] == "p2_method_dataset_policy_v1"
    assert semantic_definition["selection_strategy"]["policy_name"] == "semantic_seed_metadata_v1"
    assert co_visit_definition["dataset_name"] == "co_visit_fallback_repair_v1"
    assert co_visit_definition["items_per_seed"] > 0
    assert co_visit_definition["items_per_user"] > 0
    assert co_visit_definition["max_bucket_items"] > 0
    assert co_visit_definition["default_tier"] == "local_formal"
    assert set(co_visit_definition["scale_tiers"]) == {"smoke", "diagnostic", "local_formal"}
    assert co_visit_definition["scale_tiers"]["local_formal"]["items_per_user"] == co_visit_definition["items_per_user"]
    assert co_visit_definition["scale_tiers"]["smoke"]["items_per_seed"] == 40
    assert co_visit_definition["p2_contract_scope"] == "method_dataset_only"
    assert co_visit_definition["selection_policy_version"] == "p2_method_dataset_policy_v1"
    assert co_visit_definition["selection_strategy"]["policy_name"] == "co_visit_fallback_repair_v1"
    assert sources["semantic_title_category_expansion"]["status"] == "DEFERRED"
    assert sources["co_visit_fallback_repair"]["status"] == "DEFERRED"
    assert "not a lightweight full-statistics route" in sources["semantic_title_category_expansion"]["dataset_contract"]["generation_dataset_scope"]
    assert "not a lightweight full-statistics route" in sources["co_visit_fallback_repair"]["dataset_contract"]["generation_dataset_scope"]


def test_pool500_registry_p2_policy_fields_avoid_source_artifact_ready_semantics(sources: dict[str, dict[str, Any]]) -> None:
    p2_policy_fields = ("input_scale_policy", "method_specific_resource_boundary", "method_specific_data_definition")
    forbidden_tokens = ("capped_unified_train_behavior_dataset", "source_artifact", "candidate", "full_pool500_ready", "promotion", "source_index")

    for source_name, source_config in sources.items():
        contract = source_config["dataset_contract"]
        for field in p2_policy_fields:
            if field not in contract:
                continue
            serialized = json.dumps(contract[field], ensure_ascii=False).lower()
            hits = [token for token in forbidden_tokens if token in serialized]
            assert hits == [], f"{source_name}.{field}: {hits}"


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
