import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

from rs_core.recsys.recall_sources import (
    DEFERRED,
    DIAGNOSTIC_ONLY,
    READY,
    get_recall_source_spec,
    list_candidate_generating_sources,
    list_recall_source_specs,
)

ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = ROOT / "configs" / "recall" / "pool500_method_registry.json"


def test_recall_source_registry_names_match_json_registry() -> None:
    registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))

    core_names = {spec.name for spec in list_recall_source_specs()}
    json_names = set(registry["sources"])

    assert core_names == json_names
    assert "user_quality" not in core_names


def test_recall_source_readiness_groups_match_pool500_status() -> None:
    specs = {spec.name: spec for spec in list_recall_source_specs()}

    ready = {name for name, spec in specs.items() if spec.readiness == READY}
    diagnostic = {name for name, spec in specs.items() if spec.readiness == DIAGNOSTIC_ONLY}
    deferred = {name for name, spec in specs.items() if spec.readiness == DEFERRED}

    assert ready == {"category", "popular", "swing_recall"}
    assert diagnostic == {"usercf_recall", "itemcf_weak", "itemcf_strong"}
    assert deferred == {
        "semantic",
        "semantic_title_category_expansion",
        "co_visit_fallback_repair",
        "two_tower",
    }


def test_pool500_sources_do_not_replace_ranking_input() -> None:
    registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))

    for spec in list_recall_source_specs():
        promotion_policy = registry["sources"][spec.name]["dataset_contract"]["promotion_policy"]

        assert not spec.ranking_input_replacement_allowed
        assert promotion_policy["ranking_input_replacement_allowed"] is False


def test_candidate_generating_sources_exclude_user_quality_policy() -> None:
    source_names = {spec.name for spec in list_candidate_generating_sources()}

    assert source_names == {spec.name for spec in list_recall_source_specs()}
    assert "user_quality" not in source_names


def test_recall_source_registry_matches_json_status_and_artifacts() -> None:
    registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))

    for source_name, source_config in registry["sources"].items():
        spec = get_recall_source_spec(source_name)

        assert spec.readiness == source_config["status"]
        assert spec.method_doc == source_config["method_doc"]
        assert spec.latest_artifact == source_config["latest_artifact"]
        assert spec.latest_row_count == source_config["latest_row_count"]
        assert spec.eligible_user_policy == source_config["eligible_user_policy"]
        assert spec.role == source_config["role"]
