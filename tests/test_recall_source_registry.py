import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

from rs_core.recsys.recall_sources import (
    DEFERRED,
    DIAGNOSTIC_ONLY,
    READY,
    READY_CANDIDATE,
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
    registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    specs = {spec.name: spec for spec in list_recall_source_specs()}

    ready = {name for name, spec in specs.items() if spec.readiness == READY}
    diagnostic = {name for name, spec in specs.items() if spec.readiness == DIAGNOSTIC_ONLY}
    deferred = {name for name, spec in specs.items() if spec.readiness == DEFERRED}
    ready_candidate = {name for name, spec in specs.items() if spec.readiness == READY_CANDIDATE}

    assert ready == {name for name, config in registry["sources"].items() if config["status"] == READY}
    assert diagnostic == {name for name, config in registry["sources"].items() if config["status"] == DIAGNOSTIC_ONLY}
    assert deferred == {name for name, config in registry["sources"].items() if config["status"] == DEFERRED}
    assert ready_candidate == {name for name, config in registry["sources"].items() if config["status"] == READY_CANDIDATE}


def test_usercf_registry_blocks_bare_ready_and_tracks_non_ready_diagnostic_status() -> None:
    registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    usercf = registry["sources"]["usercf_recall"]
    contract = usercf["dataset_contract"]
    spec = get_recall_source_spec("usercf_recall")

    assert spec.readiness == DIAGNOSTIC_ONLY
    assert usercf["status"] == DIAGNOSTIC_ONLY
    assert contract["status"] == DIAGNOSTIC_ONLY
    assert usercf["future_promotion_status"] == "DIAGNOSTIC_ONLY_NOT_READY"
    assert contract["future_promotion_status"] == "DIAGNOSTIC_ONLY_NOT_READY"
    assert usercf["governance"]["candidate_generation_allowed"] is False
    assert usercf["governance"]["ranking_input_replacement_allowed"] is False
    assert usercf["governance"]["pool1000_allowed"] is False
    assert usercf["governance"]["promotion_allowed"] is False
    assert usercf["governance"]["final_pool500_ready_claimed"] is False


def test_pool500_sources_do_not_replace_ranking_input() -> None:
    registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))

    for spec in list_recall_source_specs():
        promotion_policy = registry["sources"][spec.name]["dataset_contract"]["promotion_policy"]

        assert not spec.ranking_input_replacement_allowed
        assert promotion_policy["ranking_input_replacement_allowed"] is False


def test_candidate_generating_sources_follow_explicit_route_gate_policy() -> None:
    source_names = {spec.name for spec in list_candidate_generating_sources()}

    assert source_names == {"popular", "itemcf_strong", "semantic"}
    assert "user_quality" not in source_names
    assert "category" not in source_names
    assert "swing_recall" not in source_names
    assert get_recall_source_spec("semantic").readiness == READY_CANDIDATE
    assert "semantic_title_category_expansion" not in source_names
    assert "usercf_recall" not in source_names
    assert "co_visit_fallback_repair" not in source_names


def test_semantic_title_category_expansion_is_retired_into_semantic_live() -> None:
    registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    source = registry["sources"]["semantic_title_category_expansion"]
    contract = source["dataset_contract"]
    spec = get_recall_source_spec("semantic_title_category_expansion")

    assert spec.readiness == DEFERRED
    assert spec.role == "merged_into_semantic_live_not_independent_online_source"
    assert spec.eligible_user_policy == "retired_independent_source_covered_by_semantic_live_description_recall"
    assert contract["formal_blocker"] == "merged_into_semantic_live_not_independent_online_source"
    assert source["promotion_recommendation"]["candidate_generation_allowed"] is False
    assert source["promotion_recommendation"]["ranking_input_replacement_allowed"] is False
    assert source["promotion_recommendation"]["pool1000_allowed"] is False


def test_usercf_and_co_visit_are_artifact_backed_online_without_generation_promotion() -> None:
    registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    usercf = registry["sources"]["usercf_recall"]
    co_visit = registry["sources"]["co_visit_fallback_repair"]

    assert get_recall_source_spec("usercf_recall").readiness == DIAGNOSTIC_ONLY
    assert usercf["online_exposure"]["online_exposure_mode"] == "artifact_backed_pool500_only"
    assert usercf["online_exposure"]["serving_artifact_backed_allowed"] is True
    assert usercf["online_exposure"]["serving_online_candidate_generation_allowed"] is False
    assert usercf["governance"]["candidate_generation_allowed"] is False
    assert usercf["governance"]["ranking_input_replacement_allowed"] is False
    assert usercf["governance"]["pool1000_allowed"] is False
    assert usercf["governance"]["final_pool500_ready_claimed"] is False

    assert get_recall_source_spec("co_visit_fallback_repair").readiness == DEFERRED
    assert co_visit["online_exposure"]["online_exposure_mode"] == "artifact_backed_pool500_only"
    assert co_visit["online_exposure"]["serving_artifact_backed_allowed"] is True
    assert co_visit["online_exposure"]["serving_online_candidate_generation_allowed"] is False
    assert co_visit["online_exposure"]["batch_scoped_evidence_only"] is True
    assert co_visit["dataset_contract"]["promotion_policy"]["candidate_generation_allowed"] is False
    assert co_visit["dataset_contract"]["promotion_policy"]["ranking_input_replacement_allowed"] is False
    assert co_visit["dataset_contract"]["promotion_policy"]["pool1000_allowed"] is False
    assert co_visit["dataset_contract"]["promotion_policy"]["final_pool500_ready_claimed"] is False
    assert co_visit["task_readiness"] == "FALLBACK_REPAIR_GUARDED_CANDIDATE"


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
