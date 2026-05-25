from __future__ import annotations

import hashlib
import inspect
import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

import rs_core.workflow.pool500_shadow_ranking as pool500_shadow_ranking
from rs_core.recsys.types import MergedCandidate
from rs_core.workflow.pool500_ranking_adapter import POOL500_LINEAGE_KEY
from rs_core.workflow.pool500_shadow_ranking import (
    FULL_POOL500_READY,
    PASS,
    DIAGNOSTIC_FROZEN_POOL_SCHEMA_VERSION,
    SCHEMA_VERSION,
    STOP,
    build_pool500_fixed_ranking_comparison_configs,
    build_pool500_shadow_ranking_evidence,
    run_pool500_diagnostic_frozen_pool_ranking,
    run_pool500_fixed_ranking_comparison_report,
    run_pool500_shadow_ranking,
    validate_pool500_diagnostic_frozen_pool_ranking_evidence,
    validate_pool500_shadow_ranking_evidence,
)


def _evidence(**overrides: object) -> dict[str, object]:
    evidence = build_pool500_shadow_ranking_evidence(
        diagnostic_method_id="pool500_shadow_ranker_metrics_v1",
        comparison_group="current_pool200_ranking_baseline",
        shadow_metrics={"ndcg_at_20_delta": 0.01, "coverage_delta": 0.0},
        source_artifact_gate_result={"decision": FULL_POOL500_READY},
        source_shadow_evidence_validation={"status": PASS},
    )
    evidence.update(overrides)
    return evidence


def _blocker_codes(result: dict[str, object]) -> set[str]:
    return {blocker["code"] for blocker in result["blockers"]}  # type: ignore[index]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_frozen_pool_fixture(
    tmp_path: Path,
    *,
    source: str = "popular",
    manifest_overrides: dict[str, object] | None = None,
    rows: list[dict[str, object]] | None = None,
) -> tuple[Path, Path, str, str]:
    candidate_path = tmp_path / "pool500_candidates.jsonl"
    manifest_path = tmp_path / "manifest.json"
    if rows is None:
        rows = [{"user_id": "u1", "item_id": "i1", "source": source, "score": 1.0, "rank": 1, "metadata": {"category": "cat"}}]
    candidate_path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    manifest = {
        "candidate_generation_allowed": False,
        "ranking_input_replacement_allowed": False,
        "ranking_replacement_allowed": False,
        "promotion_allowed": False,
        "pool1000_allowed": False,
        "final_pool500_ready_claimed": False,
        "full_pool500_ready_declared": False,
    }
    manifest.update(manifest_overrides or {})
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return candidate_path, manifest_path, _sha256(candidate_path), _sha256(manifest_path)


def test_pool500_shadow_ranking_evidence_is_diagnostic_only_contract() -> None:
    evidence = _evidence()
    validation = validate_pool500_shadow_ranking_evidence(evidence)

    assert evidence["schema_version"] == SCHEMA_VERSION
    assert evidence["report_semantics"] == "diagnostic shadow ranking report"
    assert evidence["diagnostic_method_id"] == "pool500_shadow_ranker_metrics_v1"
    assert evidence["comparison_group"] == "current_pool200_ranking_baseline"
    assert isinstance(evidence["shadow_metrics"], dict)
    assert evidence["candidate_generation_allowed"] is False
    assert evidence["ranking_input_replacement_allowed"] is False
    assert evidence["ranking_replacement_allowed"] is False
    assert evidence["promotion_allowed"] is False
    assert evidence["pool1000_allowed"] is False
    assert evidence["diagnostic_only"] is True
    assert evidence["not_ranking_input"] is True
    assert evidence["current_ranking_route_unchanged"] is True
    assert evidence["promotion_requires_future_plan"] is True
    assert validation["status"] == PASS
    assert validation["blockers"] == []


def test_pool500_shadow_ranking_validation_preserves_diagnostic_boundaries() -> None:
    validation = validate_pool500_shadow_ranking_evidence(_evidence())

    assert validation["candidate_generation_allowed"] is False
    assert validation["ranking_input_replacement_allowed"] is False
    assert validation["ranking_replacement_allowed"] is False
    assert validation["promotion_allowed"] is False
    assert validation["pool1000_allowed"] is False
    assert validation["diagnostic_only"] is True
    assert validation["not_ranking_input"] is True
    assert validation["current_ranking_route_unchanged"] is True
    assert validation["promotion_requires_future_plan"] is True


@pytest.mark.parametrize(
    "field",
    [
        "candidate_generation_allowed",
        "ranking_input_replacement_allowed",
        "ranking_replacement_allowed",
        "promotion_allowed",
        "pool1000_allowed",
    ],
)
def test_pool500_shadow_ranking_evidence_rejects_truthy_forbidden_flags(field: str) -> None:
    validation = validate_pool500_shadow_ranking_evidence(_evidence(**{field: True}))

    assert validation["decision"] == STOP
    assert "POOL500_SHADOW_RANKING_DIAGNOSTIC_FLAG_REQUIRED" in _blocker_codes(validation)
    assert validation[field] is False


@pytest.mark.parametrize(
    "field",
    [
        "lineage_hash",
        "baseline_artifact_hash",
        "failure_recovery_strategy",
        "cleanup_strategy",
    ],
)
@pytest.mark.parametrize("value", [None, ""])
def test_pool500_shadow_ranking_evidence_rejects_missing_hard_gate_strings(field: str, value: object) -> None:
    validation = validate_pool500_shadow_ranking_evidence(_evidence(**{field: value}))

    assert validation["decision"] == STOP
    assert "POOL500_SHADOW_RANKING_HARD_GATE_FIELD_REQUIRED" in _blocker_codes(validation)


@pytest.mark.parametrize(
    "field",
    [
        "lineage_hash",
        "baseline_artifact_hash",
        "failure_recovery_strategy",
        "cleanup_strategy",
    ],
)
def test_pool500_shadow_ranking_evidence_rejects_absent_hard_gate_strings(field: str) -> None:
    evidence = _evidence()
    evidence.pop(field)
    validation = validate_pool500_shadow_ranking_evidence(evidence)

    assert validation["decision"] == STOP
    assert "POOL500_SHADOW_RANKING_HARD_GATE_FIELD_REQUIRED" in _blocker_codes(validation)


@pytest.mark.parametrize("resource_budget", [None, [], {}])
def test_pool500_shadow_ranking_evidence_rejects_missing_resource_budget(resource_budget: object) -> None:
    validation = validate_pool500_shadow_ranking_evidence(_evidence(resource_budget=resource_budget))

    assert validation["decision"] == STOP
    assert "POOL500_SHADOW_RANKING_RESOURCE_BUDGET_REQUIRED" in _blocker_codes(validation)


def test_pool500_shadow_ranking_evidence_rejects_absent_resource_budget() -> None:
    evidence = _evidence()
    evidence.pop("resource_budget")
    validation = validate_pool500_shadow_ranking_evidence(evidence)

    assert validation["decision"] == STOP
    assert "POOL500_SHADOW_RANKING_RESOURCE_BUDGET_REQUIRED" in _blocker_codes(validation)


@pytest.mark.parametrize(
    "resource_budget",
    [
        {"rows": 100},
        {"min_rows": 1},
    ],
)
def test_pool500_shadow_ranking_evidence_rejects_resource_budget_without_positive_max_cap(resource_budget: dict[str, object]) -> None:
    validation = validate_pool500_shadow_ranking_evidence(_evidence(resource_budget=resource_budget))

    assert validation["decision"] == STOP
    assert "POOL500_SHADOW_RANKING_RESOURCE_BUDGET_CAP_REQUIRED" in _blocker_codes(validation)


@pytest.mark.parametrize(
    "resource_budget",
    [
        {"max_rows": 0},
        {"max_rows": -1},
        {"max_rows": "100"},
    ],
)
def test_pool500_shadow_ranking_evidence_rejects_invalid_resource_budget_caps(resource_budget: dict[str, object]) -> None:
    validation = validate_pool500_shadow_ranking_evidence(_evidence(resource_budget=resource_budget))

    assert validation["decision"] == STOP
    assert "POOL500_SHADOW_RANKING_RESOURCE_BUDGET_CAP_INVALID" in _blocker_codes(validation)


@pytest.mark.parametrize(
    "forbidden_payload",
    [
        {"current_ranking_route": "pool500"},
        {"candidate_id": "pool500-v1"},
        {"candidate_type": "replacement"},
        {"promotion_lane": "ranking"},
        {"promotion_eligible": True},
        {"lane": "champion"},
        {"run_kind": "variant"},
        {"shadow_metrics": {"run_kind": "variant"}},
        {"shadow_metrics": {"nested": {"run_kind": "challenger"}}},
        {"shadow_metrics": {"run_kind": "candidate"}},
        {"shadow_metrics": {"run_kind": "champion"}},
    ],
)
def test_pool500_shadow_ranking_evidence_rejects_promotion_route_semantics(forbidden_payload: dict[str, object]) -> None:
    validation = validate_pool500_shadow_ranking_evidence(_evidence(**forbidden_payload))

    assert validation["decision"] == STOP
    assert _blocker_codes(validation) & {
        "POOL500_SHADOW_RANKING_FORBIDDEN_FIELD",
        "POOL500_SHADOW_RANKING_FORBIDDEN_RUN_KIND",
    }


def test_pool500_shadow_ranking_evidence_validates_source_gate_linkage_when_supplied() -> None:
    artifact_validation = validate_pool500_shadow_ranking_evidence(_evidence(source_artifact_gate_decision="DIAGNOSTIC_ONLY_PARTIAL"))
    shadow_validation = validate_pool500_shadow_ranking_evidence(_evidence(source_shadow_evidence_decision=STOP))

    assert artifact_validation["decision"] == STOP
    assert "POOL500_SOURCE_ARTIFACT_GATE_NOT_FULL_READY" in _blocker_codes(artifact_validation)
    assert shadow_validation["decision"] == STOP
    assert "POOL500_SOURCE_SHADOW_EVIDENCE_NOT_PASS" in _blocker_codes(shadow_validation)


def test_pool500_shadow_runner_ranks_candidates_and_emits_diagnostic_evidence() -> None:
    result = run_pool500_shadow_ranking(
        diagnostic_method_id="pool500_shadow_ranker_metrics_v1",
        comparison_group="current_pool200_ranking_baseline",
        candidates_by_user={
            "u1": [
                MergedCandidate("i1", ["popular"], {"popular": 0.2}, "cat"),
                MergedCandidate("i2", ["semantic"], {"semantic": 0.5}, "cat"),
            ],
        },
        config={"rank_weights": {"popular": 1.0, "semantic": 1.0}},
        artifact_gate_result={"decision": FULL_POOL500_READY, "status": PASS},
        recall_shadow_evidence_validation={"status": PASS},
        top_k=1,
    )

    assert result["status"] == PASS
    assert result["evidence"]["report_semantics"] == "diagnostic shadow ranking report"
    assert result["evidence"]["diagnostic_only"] is True
    assert result["evidence"]["not_ranking_input"] is True
    assert result["evidence"]["current_ranking_route_unchanged"] is True
    assert result["evidence"]["promotion_requires_future_plan"] is True
    assert result["evidence"]["lineage_hash"]
    assert result["evidence"]["baseline_artifact_hash"]
    assert isinstance(result["evidence"]["resource_budget"], dict)
    assert result["evidence"]["failure_recovery_strategy"]
    assert result["evidence"]["cleanup_strategy"]
    assert result["evidence"]["shadow_metrics"]["user_count"] == 1
    assert result["evidence"]["shadow_metrics"]["top_k"] == 1
    assert result["ranking_results"]["u1"][0]["parent_asin"] == "i2"
    top_item = result["ranking_results"]["u1"][0]
    score_trace = top_item["score_trace"]
    assert [stage["stage"] for stage in score_trace] == ["coarse", "fine", "rerank"]
    assert top_item["final_rank"] == 1
    assert top_item["rank_movement"] == {"coarse_to_fine": 0, "fine_to_final": 0, "coarse_to_final": 0}
    assert result["evidence"]["shadow_metrics"]["stage_trace_coverage"] == {"coarse": 1.0, "fine": 1.0, "rerank": 1.0}


def test_pool500_shadow_runner_rows_adapter_path_preserves_score_trace() -> None:
    result = run_pool500_shadow_ranking(
        diagnostic_method_id="pool500_shadow_ranker_metrics_v1",
        comparison_group="current_pool200_ranking_baseline",
        rows=[
            {"user_id": "u1", "item_id": "i1", "source": "popular_recall", "score": 0.2, "rank": 2, "metadata": {"category": "cat"}},
            {"user_id": "u1", "item_id": "i2", "source": "semantic", "score": 0.5, "rank": 1, "metadata": {"category": "cat"}},
        ],
        config={"rank_weights": {"popular": 1.0, "semantic": 1.0}},
        artifact_gate_result={"decision": FULL_POOL500_READY, "status": PASS},
        recall_shadow_evidence_validation={"status": PASS},
        top_k=2,
    )

    assert result["status"] == PASS
    assert result["adapter_result"]["status"] == PASS
    score_traces = [item["score_trace"] for item in result["ranking_results"]["u1"]]
    assert score_traces
    assert all([stage["stage"] for stage in trace] == ["coarse", "fine", "rerank"] for trace in score_traces)
    assert result["evidence"]["shadow_metrics"]["stage_trace_coverage"] == {"coarse": 1.0, "fine": 1.0, "rerank": 1.0}


def test_pool500_shadow_runner_does_not_use_pool200_ranking_run_row() -> None:
    source = inspect.getsource(pool500_shadow_ranking)

    assert "build_ranking_run_row" not in source


def test_pool500_shadow_runner_stops_before_ranking_when_preflight_fails() -> None:
    result = run_pool500_shadow_ranking(
        diagnostic_method_id="pool500_shadow_ranker_metrics_v1",
        comparison_group="current_pool200_ranking_baseline",
        candidates_by_user={"u1": [MergedCandidate("i1", ["popular"], {"popular": 1.0})]},
        config={},
        artifact_gate_result={"decision": "DIAGNOSTIC_ONLY_PARTIAL", "status": PASS},
        recall_shadow_evidence_validation={"status": PASS},
    )

    assert result["status"] == STOP
    assert result["ranking_results"] == {}
    assert result["evidence"]["shadow_metrics"]["stopped_before_ranking"] is True
    assert "POOL500_SOURCE_ARTIFACT_GATE_NOT_FULL_READY" in _blocker_codes(result)


def test_diagnostic_frozen_pool_lane_ranks_fixed_path_hash_input(tmp_path: Path) -> None:
    candidate_path, manifest_path, candidate_hash, manifest_hash = _write_frozen_pool_fixture(tmp_path)

    result = run_pool500_diagnostic_frozen_pool_ranking(
        diagnostic_method_id="pool500_diagnostic_frozen_pool_ranker_v1",
        comparison_group="frozen_v5_baseline",
        config={"rank_weights": {"popular": 1.0}},
        pool500_candidates_path=candidate_path,
        candidate_manifest_path=manifest_path,
        expected_candidate_hash=candidate_hash,
        expected_manifest_hash=manifest_hash,
        source_artifact_gate_result={"decision": "STOP"},
        top_k=1,
    )

    assert result["status"] == PASS
    assert result["schema_version"] == DIAGNOSTIC_FROZEN_POOL_SCHEMA_VERSION
    assert result["evidence"]["schema_version"] == DIAGNOSTIC_FROZEN_POOL_SCHEMA_VERSION
    assert result["evidence"]["input_contract"] == "frozen_diagnostic_candidate_pool"
    assert result["evidence"]["expected_candidate_hash"] == candidate_hash
    assert result["evidence"]["computed_candidate_hash"] == candidate_hash
    assert result["evidence"]["source_artifact_gate_decision_observed"] == "STOP"
    assert result["evidence"]["ranking_input_replacement_allowed"] is False
    assert result["ranking_results"]["u1"][0]["parent_asin"] == "i1"


def test_diagnostic_frozen_pool_lane_rejects_rows_only_input(tmp_path: Path) -> None:
    candidate_path, manifest_path, candidate_hash, manifest_hash = _write_frozen_pool_fixture(tmp_path)

    result = run_pool500_diagnostic_frozen_pool_ranking(
        diagnostic_method_id="pool500_diagnostic_frozen_pool_ranker_v1",
        comparison_group="frozen_v5_baseline",
        config={},
        pool500_candidates_path="latest/pool500_candidates.jsonl",
        candidate_manifest_path=manifest_path,
        expected_candidate_hash=candidate_hash,
        expected_manifest_hash=manifest_hash,
    )

    assert result["status"] == STOP
    assert result["ranking_results"] == {}
    assert "POOL500_DIAGNOSTIC_RANKING_INFERRED_PATH_FORBIDDEN" in _blocker_codes(result)
    assert "POOL500_DIAGNOSTIC_RANKING_PATH_REQUIRED" in _blocker_codes(result)


@pytest.mark.parametrize(
    ("candidate_hash", "manifest_hash", "expected_code"),
    [
        ("bad", None, "POOL500_DIAGNOSTIC_RANKING_CANDIDATE_HASH_MISMATCH"),
        (None, "bad", "POOL500_DIAGNOSTIC_RANKING_MANIFEST_HASH_MISMATCH"),
    ],
)
def test_diagnostic_frozen_pool_lane_rejects_hash_mismatch(tmp_path: Path, candidate_hash: str | None, manifest_hash: str | None, expected_code: str) -> None:
    candidate_path, manifest_path, actual_candidate_hash, actual_manifest_hash = _write_frozen_pool_fixture(tmp_path)

    result = run_pool500_diagnostic_frozen_pool_ranking(
        diagnostic_method_id="pool500_diagnostic_frozen_pool_ranker_v1",
        comparison_group="frozen_v5_baseline",
        config={},
        pool500_candidates_path=candidate_path,
        candidate_manifest_path=manifest_path,
        expected_candidate_hash=candidate_hash or actual_candidate_hash,
        expected_manifest_hash=manifest_hash or actual_manifest_hash,
    )

    assert result["status"] == STOP
    assert result["ranking_results"] == {}
    assert expected_code in _blocker_codes(result)


def test_diagnostic_frozen_pool_lane_rejects_missing_manifest_hash(tmp_path: Path) -> None:
    candidate_path, manifest_path, candidate_hash, _ = _write_frozen_pool_fixture(tmp_path)

    result = run_pool500_diagnostic_frozen_pool_ranking(
        diagnostic_method_id="pool500_diagnostic_frozen_pool_ranker_v1",
        comparison_group="frozen_v5_baseline",
        config={},
        pool500_candidates_path=candidate_path,
        candidate_manifest_path=manifest_path,
        expected_candidate_hash=candidate_hash,
        expected_manifest_hash="",
    )

    assert result["status"] == STOP
    assert "POOL500_DIAGNOSTIC_RANKING_HASH_REQUIRED" in _blocker_codes(result)


def test_diagnostic_frozen_pool_lane_rejects_promotion_flags(tmp_path: Path) -> None:
    candidate_path, manifest_path, candidate_hash, manifest_hash = _write_frozen_pool_fixture(tmp_path, manifest_overrides={"promotion_allowed": True})

    result = run_pool500_diagnostic_frozen_pool_ranking(
        diagnostic_method_id="pool500_diagnostic_frozen_pool_ranker_v1",
        comparison_group="frozen_v5_baseline",
        config={},
        pool500_candidates_path=candidate_path,
        candidate_manifest_path=manifest_path,
        expected_candidate_hash=candidate_hash,
        expected_manifest_hash=manifest_hash,
    )

    assert result["status"] == STOP
    assert "POOL500_DIAGNOSTIC_RANKING_PROMOTION_FORBIDDEN" in _blocker_codes(result)


def test_diagnostic_frozen_pool_lane_does_not_emit_full_pool500_ready(tmp_path: Path) -> None:
    candidate_path, manifest_path, candidate_hash, manifest_hash = _write_frozen_pool_fixture(tmp_path)

    result = run_pool500_diagnostic_frozen_pool_ranking(
        diagnostic_method_id="pool500_diagnostic_frozen_pool_ranker_v1",
        comparison_group="frozen_v5_baseline",
        config={},
        pool500_candidates_path=candidate_path,
        candidate_manifest_path=manifest_path,
        expected_candidate_hash=candidate_hash,
        expected_manifest_hash=manifest_hash,
        source_artifact_gate_result={"decision": FULL_POOL500_READY},
    )

    assert result["status"] == STOP
    assert "POOL500_DIAGNOSTIC_RANKING_FULL_READY_FORBIDDEN" in _blocker_codes(result)
    assert result["evidence"].get("source_artifact_gate_decision") is None


def test_diagnostic_lane_adapter_stop_blocks_ranking(tmp_path: Path) -> None:
    candidate_path, manifest_path, _, manifest_hash = _write_frozen_pool_fixture(tmp_path, source="itemcf")
    candidate_hash = _sha256(candidate_path)

    result = run_pool500_diagnostic_frozen_pool_ranking(
        diagnostic_method_id="pool500_diagnostic_frozen_pool_ranker_v1",
        comparison_group="frozen_v5_baseline",
        config={},
        pool500_candidates_path=candidate_path,
        candidate_manifest_path=manifest_path,
        expected_candidate_hash=candidate_hash,
        expected_manifest_hash=manifest_hash,
    )

    assert result["status"] == STOP
    assert result["ranking_results"] == {}
    assert "POOL500_FORBIDDEN_SOURCE_LABEL" in _blocker_codes(result)


def test_diagnostic_lane_outputs_diagnostic_schema_v1_not_formal_schema(tmp_path: Path) -> None:
    candidate_path, manifest_path, candidate_hash, manifest_hash = _write_frozen_pool_fixture(tmp_path)

    result = run_pool500_diagnostic_frozen_pool_ranking(
        diagnostic_method_id="pool500_diagnostic_frozen_pool_ranker_v1",
        comparison_group="frozen_v5_baseline",
        config={},
        pool500_candidates_path=candidate_path,
        candidate_manifest_path=manifest_path,
        expected_candidate_hash=candidate_hash,
        expected_manifest_hash=manifest_hash,
    )
    validation = validate_pool500_diagnostic_frozen_pool_ranking_evidence({"schema_version": SCHEMA_VERSION})

    assert result["evidence"]["schema_version"] == DIAGNOSTIC_FROZEN_POOL_SCHEMA_VERSION
    assert result["evidence"]["schema_version"] != SCHEMA_VERSION
    assert validation["status"] == STOP
    assert "POOL500_DIAGNOSTIC_RANKING_FORMAL_SCHEMA_FORBIDDEN" in _blocker_codes(validation)


def test_diagnostic_interpretation_blocks_missing_aggregation() -> None:
    evidence = {
        "schema_version": DIAGNOSTIC_FROZEN_POOL_SCHEMA_VERSION,
        "input_contract": "frozen_diagnostic_candidate_pool",
        "pool500_candidates_path": "pool500_candidates.jsonl",
        "candidate_manifest_path": "manifest.json",
        "expected_candidate_hash": "a",
        "computed_candidate_hash": "a",
        "expected_manifest_hash": "b",
        "computed_manifest_hash": "b",
        "category_coverage": {"cat": 1},
        "multi_source_item_ratio": 1.0,
        "metadata_missing_rate": 0.0,
        "category_missing_rate": 0.0,
        "top_category_ratio": 0.5,
        "interpretation_label": "comparable",
        "underfilled_user_count": 0,
        "candidate_generation_allowed": False,
        "ranking_input_replacement_allowed": False,
        "ranking_replacement_allowed": False,
        "promotion_allowed": False,
        "pool1000_allowed": False,
        "diagnostic_only": True,
        "not_ranking_input": True,
        "current_ranking_route_unchanged": True,
        "promotion_requires_future_plan": True,
    }

    validation = validate_pool500_diagnostic_frozen_pool_ranking_evidence(evidence)

    assert validation["status"] == STOP
    assert validation["interpretation_label"] == "blocked"
    assert "POOL500_DIAGNOSTIC_AGGREGATION_REQUIRED" in _blocker_codes(validation)


def test_diagnostic_interpretation_blocks_forbidden_source(tmp_path: Path) -> None:
    candidate_path, manifest_path, _, manifest_hash = _write_frozen_pool_fixture(tmp_path, source="itemcf")
    candidate_hash = _sha256(candidate_path)

    result = run_pool500_diagnostic_frozen_pool_ranking(
        diagnostic_method_id="pool500_diagnostic_frozen_pool_ranker_v1",
        comparison_group="frozen_v5_baseline",
        config={},
        pool500_candidates_path=candidate_path,
        candidate_manifest_path=manifest_path,
        expected_candidate_hash=candidate_hash,
        expected_manifest_hash=manifest_hash,
    )

    assert result["status"] == STOP
    assert result["validation"]["interpretation_label"] == "blocked"
    assert "POOL500_FORBIDDEN_SOURCE_LABEL" in _blocker_codes(result)


def test_diagnostic_interpretation_marks_underfilled_as_mechanism_only(tmp_path: Path) -> None:
    rows = [
        {"user_id": "u1", "item_id": "i1", "source": "popular", "score": 1.0, "rank": 1, "metadata": {"category": "cat"}},
        {"user_id": "u2", "item_id": "i2", "source": "category", "score": 0.9, "rank": 1, "metadata": {"category": "cat"}},
    ]
    candidate_path, manifest_path, candidate_hash, manifest_hash = _write_frozen_pool_fixture(tmp_path, rows=rows)

    result = run_pool500_diagnostic_frozen_pool_ranking(
        diagnostic_method_id="pool500_diagnostic_frozen_pool_ranker_v1",
        comparison_group="frozen_v5_baseline",
        config={"rank_weights": {"popular": 1.0, "category": 1.0}},
        pool500_candidates_path=candidate_path,
        candidate_manifest_path=manifest_path,
        expected_candidate_hash=candidate_hash,
        expected_manifest_hash=manifest_hash,
        top_k=1,
    )

    assert result["status"] == PASS
    assert result["evidence"]["underfilled_user_count"] == 2
    assert result["validation"]["status"] == PASS


def test_diagnostic_interpretation_marks_incomplete_sources_as_mechanism_only(tmp_path: Path) -> None:
    rows = [
        {"user_id": "u1", "item_id": f"i{index}", "source": "popular", "score": 1.0, "rank": index + 1, "metadata": {"category": "cat"}}
        for index in range(500)
    ]
    candidate_path, manifest_path, candidate_hash, manifest_hash = _write_frozen_pool_fixture(tmp_path, rows=rows)

    result = run_pool500_diagnostic_frozen_pool_ranking(
        diagnostic_method_id="pool500_diagnostic_frozen_pool_ranker_v1",
        comparison_group="frozen_v5_baseline",
        config={"rank_weights": {"popular": 1.0}},
        pool500_candidates_path=candidate_path,
        candidate_manifest_path=manifest_path,
        expected_candidate_hash=candidate_hash,
        expected_manifest_hash=manifest_hash,
    )

    assert result["status"] == PASS
    assert result["evidence"]["underfilled_user_count"] == 0
    assert result["validation"]["status"] == PASS


def test_diagnostic_interpretation_marks_normal_fixture_as_comparable() -> None:
    evidence = {
        "schema_version": DIAGNOSTIC_FROZEN_POOL_SCHEMA_VERSION,
        "input_contract": "frozen_diagnostic_candidate_pool",
        "pool500_candidates_path": "pool500_candidates.jsonl",
        "candidate_manifest_path": "manifest.json",
        "expected_candidate_hash": "a",
        "computed_candidate_hash": "a",
        "expected_manifest_hash": "b",
        "computed_manifest_hash": "b",
        "user_count": 100,
        "underfilled_user_count": 2,
        "source_coverage": {
            "popular": 100,
            "category": 100,
            "semantic": 100,
            "semantic_title_category_expansion": 100,
            "itemcf_weak": 100,
            "itemcf_strong": 100,
            "co_visit_fallback_repair": 100,
            "usercf_recall": 100,
            "swing_recall": 100,
            "two_tower": 100,
        },
        "category_coverage": {"cat-a": 600, "cat-b": 400},
        "multi_source_item_ratio": 0.1,
        "metadata_missing_rate": 0.01,
        "category_missing_rate": 0.05,
        "top_category_ratio": 0.95,
        "interpretation_label": "comparable",
        "candidate_generation_allowed": False,
        "ranking_input_replacement_allowed": False,
        "ranking_replacement_allowed": False,
        "promotion_allowed": False,
        "pool1000_allowed": False,
        "diagnostic_only": True,
        "not_ranking_input": True,
        "current_ranking_route_unchanged": True,
        "promotion_requires_future_plan": True,
    }

    validation = validate_pool500_diagnostic_frozen_pool_ranking_evidence(evidence)

    assert validation["status"] == PASS
    assert validation["interpretation_label"] == "comparable"


def test_pool500_diagnostic_flags_preserved(tmp_path: Path) -> None:
    candidate_path, manifest_path, candidate_hash, manifest_hash = _write_frozen_pool_fixture(tmp_path)

    result = run_pool500_diagnostic_frozen_pool_ranking(
        diagnostic_method_id="pool500_diagnostic_frozen_pool_ranker_v1",
        comparison_group="frozen_v5_baseline",
        config={"rank_weights": {"popular": 1.0}},
        pool500_candidates_path=candidate_path,
        candidate_manifest_path=manifest_path,
        expected_candidate_hash=candidate_hash,
        expected_manifest_hash=manifest_hash,
        top_k=1,
    )

    assert result["status"] == PASS
    evidence = result["evidence"]
    assert evidence["candidate_generation_allowed"] is False
    assert evidence["ranking_input_replacement_allowed"] is False
    assert evidence["ranking_replacement_allowed"] is False
    assert evidence["promotion_allowed"] is False
    assert evidence["pool1000_allowed"] is False
    assert evidence["diagnostic_only"] is True
    assert evidence["not_ranking_input"] is True
    assert evidence["current_ranking_route_unchanged"] is True
    assert evidence["promotion_requires_future_plan"] is True
    assert result["validation"]["status"] == PASS


@pytest.mark.parametrize(
    "forbidden_payload",
    [
        {"promotion_allowed": True},
        {"ranking_replacement_allowed": True},
        {"promotion_eligible": True},
        {"run_kind": "variant"},
        {"shadow_metrics": {"run_kind": "challenger"}},
    ],
)
def test_pool500_no_promotion_or_variant_semantics(forbidden_payload: dict[str, object]) -> None:
    validation = validate_pool500_shadow_ranking_evidence(_evidence(**forbidden_payload))

    assert validation["status"] == STOP
    assert _blocker_codes(validation) & {
        "POOL500_SHADOW_RANKING_DIAGNOSTIC_FLAG_REQUIRED",
        "POOL500_SHADOW_RANKING_FORBIDDEN_FIELD",
        "POOL500_SHADOW_RANKING_FORBIDDEN_RUN_KIND",
    }


def test_pool500_shadow_does_not_use_pool200_build_ranking_run_row() -> None:
    source = inspect.getsource(pool500_shadow_ranking)

    assert "build_ranking_run_row" not in source


def test_pool500_r_configs_are_shadow_only() -> None:
    configs = build_pool500_fixed_ranking_comparison_configs()

    assert [config_id for config_id in configs if config_id.startswith("R")] == ["R1", "R2", "R3"]
    assert configs["R1"]["fallback_heavy_topk_cap"] == {"enabled": True, "max_topk_ratio": 0.5}
    assert configs["R2"]["source_diversity_constrained_rerank"] == {"enabled": True, "max_per_source_topk_ratio": 0.5}
    assert configs["R3"]["conservative_quality_guard"] == {"enabled": True}
    assert configs["R3"]["ltr_model"] == {"enabled": False}
    for config in (configs["R1"], configs["R2"], configs["R3"]):
        assert config["top_k"] == 20
        assert config.get("candidate_generation_allowed") is None
        assert config.get("ranking_input_replacement_allowed") is None
        assert config.get("ranking_replacement_allowed") is None
        assert config.get("promotion_allowed") is None
        assert config.get("run_kind") is None


def test_pool500_label_absence_does_not_block(tmp_path: Path) -> None:
    rows = [
        {
            "user_id": "u1",
            "item_id": "i1",
            "source": "popular",
            "score": 1.0,
            "rank": 1,
            "metadata": {"category": "cat", POOL500_LINEAGE_KEY: [{"source": "popular"}]},
        }
    ]
    candidate_path, manifest_path, candidate_hash, manifest_hash = _write_frozen_pool_fixture(tmp_path, rows=rows)

    result = run_pool500_diagnostic_frozen_pool_ranking(
        diagnostic_method_id="pool500_diagnostic_frozen_pool_ranker_v1",
        comparison_group="frozen_v5_baseline",
        config={"rank_weights": {"popular": 1.0}},
        pool500_candidates_path=candidate_path,
        candidate_manifest_path=manifest_path,
        expected_candidate_hash=candidate_hash,
        expected_manifest_hash=manifest_hash,
        top_k=1,
    )

    assert result["status"] == PASS
    metrics = result["evidence"]["shadow_metrics"]
    assert metrics["label_metrics_available"] is False
    assert metrics["label_adjacent_metrics"] == {}
    assert result["evidence"]["label_metrics_available"] is False
    assert result["evidence"]["label_adjacent_metrics"] == {}
    assert not any("lift" in key for key in metrics)
    assert not any("lift" in key for key in result["evidence"])


def test_pool500_quality_guard_mechanism_only() -> None:
    result = run_pool500_shadow_ranking(
        diagnostic_method_id="pool500_shadow_ranker_metrics_v1",
        comparison_group="current_pool200_ranking_baseline",
        candidates_by_user={
            "u1": [
                MergedCandidate("i1", ["popular"], {"popular": 1.0}, None, {POOL500_LINEAGE_KEY: [{"source": "popular"}]}),
            ],
        },
        config={"rank_weights": {"popular": 1.0}},
        artifact_gate_result={"decision": FULL_POOL500_READY, "status": PASS},
        recall_shadow_evidence_validation={"status": PASS},
        top_k=1,
    )

    assert result["status"] == PASS
    assert result["evidence"]["shadow_metrics"]["category_missing_rate"] == 1.0
    assert result["evidence"]["shadow_metrics"]["interpretation_label"] == "mechanism_only"
    assert result["validation"]["status"] == PASS


def test_pool500_evidence_schema_contract(tmp_path: Path) -> None:
    candidate_path, manifest_path, candidate_hash, manifest_hash = _write_frozen_pool_fixture(tmp_path)

    result = run_pool500_diagnostic_frozen_pool_ranking(
        diagnostic_method_id="pool500_diagnostic_frozen_pool_ranker_v1",
        comparison_group="frozen_v5_baseline",
        config={"rank_weights": {"popular": 1.0}},
        pool500_candidates_path=candidate_path,
        candidate_manifest_path=manifest_path,
        expected_candidate_hash=candidate_hash,
        expected_manifest_hash=manifest_hash,
        top_k=1,
    )
    validation = validate_pool500_diagnostic_frozen_pool_ranking_evidence(result["evidence"])

    assert result["schema_version"] == DIAGNOSTIC_FROZEN_POOL_SCHEMA_VERSION
    assert result["evidence"]["schema_version"] == DIAGNOSTIC_FROZEN_POOL_SCHEMA_VERSION
    assert result["evidence"]["schema_version"] != SCHEMA_VERSION
    assert result["evidence"]["report_semantics"] == "diagnostic frozen-pool shadow ranking report"
    assert result["evidence"]["input_contract"] == "frozen_diagnostic_candidate_pool"
    assert validation["status"] == PASS
    assert validation["blockers"] == []


def test_pool500_metric_missing_behavior() -> None:
    result = run_pool500_shadow_ranking(
        diagnostic_method_id="pool500_shadow_ranker_metrics_v1",
        comparison_group="current_pool200_ranking_baseline",
        candidates_by_user={
            "u1": [
                MergedCandidate("i1", ["popular"], {"popular": 1.0}, "cat", {}),
                MergedCandidate("i2", ["co_visit_fallback_repair"], {"co_visit_fallback_repair": 0.9}, "cat", {"fallback_used": True}),
            ],
        },
        config={"rank_weights": {"popular": 1.0, "co_visit_fallback_repair": 1.0}},
        artifact_gate_result={"decision": FULL_POOL500_READY, "status": PASS},
        recall_shadow_evidence_validation={"status": PASS},
        top_k=2,
    )

    metrics = result["evidence"]["shadow_metrics"]
    assert result["status"] == PASS
    assert metrics["fallback_exposure_topk_ratio"] is None
    assert metrics["interpretation_label"] == "mechanism_only"
    assert result["validation"]["status"] == PASS
    assert metrics["label_metrics_available"] is False
    assert metrics["label_adjacent_metrics"] == {}



def test_fixed_ranking_comparison_configs_are_bounded_and_keep_itemcf_as_group_key() -> None:
    configs = build_pool500_fixed_ranking_comparison_configs()

    assert list(configs) == ["B0", "D1", "D2", "A1", "A2", "R1", "R2", "R3"]
    assert all(config["top_k"] == 20 for config in configs.values())
    assert "topk_source_minimums" not in configs["B0"]
    assert configs["D1"]["topk_source_minimums"] == {"itemcf": 1}
    assert configs["D2"]["topk_source_minimums"] == {"itemcf": 1, "semantic": 1, "category": 1}
    assert configs["A1"]["normalized_additive_ranking"]["weights"]["source_signal"] == 0.2
    assert configs["A2"]["normalized_additive_ranking"]["weights"]["source_signal"] == 0.4
    assert configs["R1"]["fallback_heavy_topk_cap"] == {"enabled": True, "max_topk_ratio": 0.5}
    assert configs["R2"]["source_diversity_constrained_rerank"] == {"enabled": True, "max_per_source_topk_ratio": 0.5}
    assert configs["R3"]["conservative_quality_guard"] == {"enabled": True}
    assert configs["R3"]["ltr_model"] == {"enabled": False}


def test_fixed_ranking_comparison_report_emits_explainable_case_diff(tmp_path: Path) -> None:
    rows = [
        {"user_id": "u1", "item_id": "i1", "source": "popular", "score": 1.0, "rank": 1, "metadata": {"category": "cat-a"}},
        {"user_id": "u1", "item_id": "i2", "source": "semantic", "score": 0.9, "rank": 2, "metadata": {"category": "cat-b"}},
        {"user_id": "u1", "item_id": "i3", "source": "itemcf_weak", "score": 0.8, "rank": 3, "metadata": {"category": "cat-b"}},
        {"user_id": "u1", "item_id": "i3", "source": "itemcf_strong", "score": 0.7, "rank": 4, "metadata": {"category": "cat-b"}},
    ]
    candidate_path, manifest_path, candidate_hash, manifest_hash = _write_frozen_pool_fixture(tmp_path, rows=rows)

    report = run_pool500_fixed_ranking_comparison_report(
        diagnostic_method_id="pool500_diagnostic_fixed_comparison_v1",
        comparison_group="frozen_v5_baseline",
        pool500_candidates_path=candidate_path,
        candidate_manifest_path=manifest_path,
        expected_candidate_hash=candidate_hash,
        expected_manifest_hash=manifest_hash,
    )

    assert report["status"] == PASS
    assert report["report_semantics"] == "diagnostic fixed ranking comparison report"
    expected_config_ids = ["B0", "D1", "D2", "A1", "A2", "R1", "R2", "R3"]
    assert report["fixed_config_ids"] == expected_config_ids
    assert report["top_k"] == 20
    assert report["top10_view_source"] == "truncated_from_top20"
    assert report["promotion_allowed"] is False
    assert set(report["comparison_results"]) == set(expected_config_ids)
    for summary in report["comparison_results"].values():
        assert summary["stage_trace_coverage"] == {"coarse": 1.0, "fine": 1.0, "rerank": 1.0}
        assert summary["score_trace"]["u1"]
        assert summary["rank_movement"]["u1"]
        assert summary["score_components"]["u1"]
    for rows in report["case_diffs"].values():
        assert rows
        row = rows[0]
        assert {
            "user_id",
            "parent_asin",
            "baseline_rank",
            "variant_rank",
            "rank_delta",
            "baseline_score",
            "variant_score",
            "score_delta",
            "sources",
            "category",
            "baseline_score_trace",
            "variant_score_trace",
            "baseline_score_components",
            "variant_score_components",
            "rank_movement",
            "dominant_score_component",
            "source_delta",
            "category_delta",
            "interpretation_label",
        } <= set(row)
        assert not ({"itemcf", "two_tower_seed", "final_two_tower_seed"} & set(row["sources"]))


def test_fixed_ranking_comparison_report_redacts_raw_candidate_metadata(tmp_path: Path) -> None:
    rows = [
        {"user_id": "u1", "item_id": "i1", "source": "popular", "score": 1.0, "rank": 1, "metadata": {"category": "cat", "holdout_hit": True, "label_binary": 1, "future_clicks": 3}},
    ]
    candidate_path, manifest_path, candidate_hash, manifest_hash = _write_frozen_pool_fixture(tmp_path, rows=rows)

    report = run_pool500_fixed_ranking_comparison_report(
        diagnostic_method_id="pool500_diagnostic_fixed_comparison_v1",
        comparison_group="frozen_v5_baseline",
        pool500_candidates_path=candidate_path,
        candidate_manifest_path=manifest_path,
        expected_candidate_hash=candidate_hash,
        expected_manifest_hash=manifest_hash,
    )

    serialized = json.dumps(report["comparison_results"])
    assert "holdout_hit" not in serialized
    assert "label_binary" not in serialized
    assert "future_clicks" not in serialized
    assert "metadata" not in report["comparison_results"]["B0"]["ranking_results"]["u1"][0]



def test_fixed_ranking_report_explicit_label_artifact_reaches_comparable_state(tmp_path: Path) -> None:
    rows = [
        {"user_id": "u1", "item_id": "i1", "source": "popular", "score": 1.0, "rank": 1, "metadata": {"category": "cat"}},
    ]
    candidate_path, manifest_path, candidate_hash, manifest_hash = _write_frozen_pool_fixture(tmp_path, rows=rows)
    label_path = tmp_path / "labels.jsonl"
    label_path.write_text(json.dumps({"schema_version": "pool500_label_artifact_v1", "user_id": "u1", "parent_asin": "i1", "label_binary": 1}) + "\n", encoding="utf-8")

    report = run_pool500_fixed_ranking_comparison_report(
        diagnostic_method_id="pool500_diagnostic_fixed_comparison_v1",
        comparison_group="frozen_v5_baseline",
        pool500_candidates_path=candidate_path,
        candidate_manifest_path=manifest_path,
        expected_candidate_hash=candidate_hash,
        expected_manifest_hash=manifest_hash,
        label_artifact_path=label_path,
        label_evaluator_enabled=True,
    )

    assert report["recommended_diagnostic_config_id"] == "R1"
    assert report["recommendation_scope"] == "diagnostic_followup_only"
    assert report["promotion_readiness"] == "not_allowed_in_this_report"
    assert report["comparison_results"]["B0"]["label_state"] == "label_comparable"
    assert report["comparison_results"]["B0"]["label_artifact_metadata"]["candidate_coverage"] == 1.0
    assert report["comparison_results"]["B0"]["label_artifact_metadata"]["coverage_thresholds"] == {
        "topk_union_candidate_coverage": 1.0,
        "user_label_coverage": 1.0,
        "positive_user_coverage": 1.0,
    }
    assert report["comparison_results"]["B0"]["label_artifact_metadata"]["failed_thresholds"] == []
    assert report["label_metric_definition_version"] == "pool500_label_metrics_per_user_mean_v1"
    assert report["label_metric_eligibility"] is True
    assert report["all_configs_label_comparable"] is True
    assert report["baseline_label_comparable"] is True
    assert report["metrics_summary"]["per_config"]["B0"]["label_state"] == "label_comparable"


def test_fixed_ranking_summary_projection_rejects_report_absent_authority_field(tmp_path: Path) -> None:
    candidate_path, manifest_path, candidate_hash, manifest_hash = _write_frozen_pool_fixture(tmp_path)
    report = run_pool500_fixed_ranking_comparison_report(
        diagnostic_method_id="pool500_diagnostic_fixed_comparison_v1",
        comparison_group="frozen_v5_baseline",
        pool500_candidates_path=candidate_path,
        candidate_manifest_path=manifest_path,
        expected_candidate_hash=candidate_hash,
        expected_manifest_hash=manifest_hash,
    )
    summary = dict(report["metrics_summary"])
    summary["promotion_allowed"] = True

    with pytest.raises(AssertionError):
        pool500_shadow_ranking.assert_pool500_summary_projection_matches_report(report, summary)


def _write_label_artifact_fixture(tmp_path: Path, rows: list[dict[str, object]], name: str = "labels.jsonl") -> Path:
    label_path = tmp_path / name
    label_path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    return label_path


def _pool500_comparison_report_for_label_fixture(
    tmp_path: Path,
    *,
    rows: list[dict[str, object]] | None = None,
    manifest_overrides: dict[str, object] | None = None,
    label_path: Path | None = None,
    label_evaluator_enabled: bool = True,
) -> dict[str, object]:
    candidate_path, manifest_path, candidate_hash, manifest_hash = _write_frozen_pool_fixture(
        tmp_path,
        rows=rows or [{"user_id": "u1", "item_id": "i1", "source": "popular", "score": 1.0, "rank": 1, "metadata": {"category": "cat"}}],
        manifest_overrides=manifest_overrides,
    )
    return run_pool500_fixed_ranking_comparison_report(
        diagnostic_method_id="pool500_diagnostic_fixed_comparison_v1",
        comparison_group="frozen_v5_baseline",
        pool500_candidates_path=candidate_path,
        candidate_manifest_path=manifest_path,
        expected_candidate_hash=candidate_hash,
        expected_manifest_hash=manifest_hash,
        label_artifact_path=label_path,
        label_evaluator_enabled=label_evaluator_enabled,
    )


def _summary_for_config(report: dict[str, object], config_id: str = "B0") -> dict[str, object]:
    return report["comparison_results"][config_id]  # type: ignore[index]


def test_label_aware_no_label_artifact_fixture_pending_without_lift(tmp_path: Path) -> None:
    report = _pool500_comparison_report_for_label_fixture(tmp_path)
    summary = _summary_for_config(report)

    assert summary["label_state"] == "pending_label"
    assert summary["label_metrics_available"] is False
    assert summary["label_adjacent_metrics"] == {}
    assert summary["label_artifact_metadata"] is None
    assert report["promotion_readiness"] == "not_allowed_in_this_report"
    assert "ready" not in str(report["promotion_readiness"]).lower()
    assert not any("lift" in key.lower() for key in summary)
    assert not any("lift" in key.lower() for key in summary["shadow_metrics"])


def test_label_aware_invalid_schema_fixture_blocks_label_metrics(tmp_path: Path) -> None:
    label_path = _write_label_artifact_fixture(
        tmp_path,
        [{"schema_version": "bad_schema", "user": "u1", "parent_asin": "i1", "label_binary": 1}],
    )

    report = _pool500_comparison_report_for_label_fixture(tmp_path, label_path=label_path)
    summary = _summary_for_config(report)

    assert summary["label_state"] == "label_invalid"
    assert summary["label_metrics_available"] is False
    assert summary["label_adjacent_metrics"] == {}
    assert report["status"] == PASS
    assert report["label_metric_eligibility"] is False
    assert report["label_evaluation_state_by_config"]["B0"] == "label_invalid"


def test_label_aware_string_zero_label_is_not_positive(tmp_path: Path) -> None:
    label_path = _write_label_artifact_fixture(
        tmp_path,
        [{"schema_version": "pool500_label_artifact_v1", "user_id": "u1", "parent_asin": "i1", "label_binary": "0"}],
    )

    report = _pool500_comparison_report_for_label_fixture(tmp_path, label_path=label_path)
    summary = _summary_for_config(report)

    assert summary["label_state"] == "label_insufficient"
    assert summary["label_artifact_metadata"]["positive_count"] == 0
    assert report["status"] == PASS
    assert report["label_metric_eligibility"] is False


def test_label_aware_unsupported_string_label_becomes_invalid_blocker(tmp_path: Path) -> None:
    label_path = _write_label_artifact_fixture(
        tmp_path,
        [{"schema_version": "pool500_label_artifact_v1", "user_id": "u1", "parent_asin": "i1", "label_binary": "maybe"}],
    )

    report = _pool500_comparison_report_for_label_fixture(tmp_path, label_path=label_path)
    summary = _summary_for_config(report)

    assert summary["label_state"] == "label_invalid"
    assert report["status"] == PASS
    assert report["label_metric_eligibility"] is False


def test_label_aware_low_coverage_fixture_marks_label_insufficient(tmp_path: Path) -> None:
    rows = [
        {"user_id": "u1", "item_id": "i1", "source": "popular", "score": 1.0, "rank": 1, "metadata": {"category": "cat"}},
        {"user_id": "u1", "item_id": "i2", "source": "semantic", "score": 0.9, "rank": 2, "metadata": {"category": "cat"}},
    ]
    label_path = _write_label_artifact_fixture(
        tmp_path,
        [{"schema_version": "pool500_label_artifact_v1", "user_id": "u2", "parent_asin": "i9", "label_binary": 1}],
    )

    report = _pool500_comparison_report_for_label_fixture(tmp_path, rows=rows, label_path=label_path)
    summary = _summary_for_config(report)

    assert summary["label_state"] == "label_insufficient"
    assert summary["label_metrics_available"] is False
    assert summary["label_adjacent_metrics"] == {}
    assert summary["label_artifact_metadata"]["candidate_coverage"] == 0.0
    assert summary["label_artifact_metadata"]["user_coverage"] == 0.0
    assert summary["label_artifact_metadata"]["failed_thresholds"] == [
        "topk_union_candidate_coverage",
        "user_label_coverage",
        "positive_user_coverage",
    ]
    assert report["status"] == PASS
    assert report["label_metric_eligibility"] is False


def test_label_aware_eligible_fixture_computes_label_evaluator_metrics(tmp_path: Path) -> None:
    label_path = _write_label_artifact_fixture(
        tmp_path,
        [{"schema_version": "pool500_label_artifact_v1", "user_id": "u1", "parent_asin": "i1", "label_binary": 1}],
    )

    report = _pool500_comparison_report_for_label_fixture(tmp_path, label_path=label_path)
    summary = _summary_for_config(report)
    metrics = summary["label_adjacent_metrics"]

    assert summary["label_state"] == "label_comparable"
    assert summary["label_metrics_available"] is True
    assert metrics["label_metric_definition_version"] == "pool500_label_metrics_per_user_mean_v1"
    assert metrics["hit_at_20"] == 1.0
    assert metrics["ndcg_at_20"] == 1.0
    assert metrics["mrr_at_20"] == 1.0
    assert metrics["recall_at_20"] == 1.0
    assert metrics["eligible_user_count"] == 1
    assert summary["label_artifact_metadata"]["candidate_coverage"] == 1.0


def test_label_aware_partial_union_coverage_marks_label_insufficient_without_stopping_report(tmp_path: Path) -> None:
    rows = [
        {"user_id": "u1", "item_id": "i1", "source": "popular", "score": 1.0, "rank": 1, "metadata": {"category": "cat"}},
        {"user_id": "u1", "item_id": "i2", "source": "semantic", "score": 0.9, "rank": 2, "metadata": {"category": "cat"}},
    ]
    label_path = _write_label_artifact_fixture(
        tmp_path,
        [{"schema_version": "pool500_label_artifact_v1", "user_id": "u1", "parent_asin": "i1", "label_binary": 1}],
    )

    report = _pool500_comparison_report_for_label_fixture(tmp_path, rows=rows, label_path=label_path)
    summary = _summary_for_config(report)

    assert report["status"] == PASS
    assert report["label_metric_eligibility"] is False
    assert summary["label_state"] == "label_insufficient"
    assert summary["label_artifact_metadata"]["topk_union_candidate_coverage"] == 0.5
    assert summary["label_artifact_metadata"]["user_label_coverage"] == 1.0
    assert summary["label_artifact_metadata"]["positive_user_coverage"] == 1.0
    assert summary["label_artifact_metadata"]["failed_thresholds"] == ["topk_union_candidate_coverage"]


def test_full_pool_candidate_coverage_is_diagnostic_not_label_gate_denominator(tmp_path: Path) -> None:
    rows = [
        {
            "user_id": "u1",
            "item_id": f"i{index:02d}",
            "source": "popular",
            "score": float(100 - index),
            "rank": index,
            "metadata": {"category": "cat"},
        }
        for index in range(1, 22)
    ]
    label_path = _write_label_artifact_fixture(
        tmp_path,
        [
            {
                "schema_version": "pool500_label_artifact_v1",
                "user_id": "u1",
                "parent_asin": f"i{index:02d}",
                "label_binary": 1,
            }
            for index in range(1, 21)
        ],
    )

    report = _pool500_comparison_report_for_label_fixture(tmp_path, rows=rows, label_path=label_path)
    metadata = _summary_for_config(report)["label_artifact_metadata"]

    assert report["label_metric_eligibility"] is True
    assert _summary_for_config(report)["label_state"] == "label_comparable"
    assert metadata["topk_union_candidate_coverage"] == 1.0
    assert metadata["full_pool_candidate_coverage_diagnostic"] == 0.952381
    assert metadata["failed_thresholds"] == []



def test_label_aware_metrics_use_per_user_mean_definition(tmp_path: Path) -> None:
    rows = [
        {"user_id": "u1", "item_id": "i1", "source": "popular", "score": 1.0, "rank": 1, "metadata": {"category": "cat"}},
        {"user_id": "u1", "item_id": "i2", "source": "semantic", "score": 0.9, "rank": 2, "metadata": {"category": "cat"}},
        {"user_id": "u2", "item_id": "j1", "source": "popular", "score": 1.0, "rank": 1, "metadata": {"category": "cat"}},
        {"user_id": "u2", "item_id": "j2", "source": "semantic", "score": 0.9, "rank": 2, "metadata": {"category": "cat"}},
    ]
    label_path = _write_label_artifact_fixture(
        tmp_path,
        [
            {"schema_version": "pool500_label_artifact_v1", "user_id": "u1", "parent_asin": "i1", "label_binary": 0},
            {"schema_version": "pool500_label_artifact_v1", "user_id": "u1", "parent_asin": "i2", "label_binary": 1},
            {"schema_version": "pool500_label_artifact_v1", "user_id": "u2", "parent_asin": "j1", "label_binary": 1},
            {"schema_version": "pool500_label_artifact_v1", "user_id": "u2", "parent_asin": "j2", "label_binary": 1},
        ],
    )

    report = _pool500_comparison_report_for_label_fixture(tmp_path, rows=rows, label_path=label_path)
    metrics = _summary_for_config(report)["label_adjacent_metrics"]

    assert report["label_metric_definition_version"] == "pool500_label_metrics_per_user_mean_v1"
    assert report["label_metric_eligibility"] is True
    assert metrics["eligible_user_count"] == 2
    assert metrics["hit_at_20"] == 1.0
    assert metrics["ndcg_at_20"] == 0.815465
    assert metrics["mrr_at_20"] == 0.75
    assert metrics["recall_at_20"] == 1.0


def test_summary_projection_helper_faithfully_copies_label_authority_fields(tmp_path: Path) -> None:
    label_path = _write_label_artifact_fixture(
        tmp_path,
        [{"schema_version": "pool500_label_artifact_v1", "user_id": "u1", "parent_asin": "i1", "label_binary": 1}],
    )
    report = _pool500_comparison_report_for_label_fixture(tmp_path, label_path=label_path)
    summary = report["metrics_summary"]

    pool500_shadow_ranking.assert_pool500_summary_projection_matches_report(report, summary)
    assert summary["recommended_diagnostic_config_id"] == report["recommended_diagnostic_config_id"]
    assert summary["recommendation_scope"] == report["recommendation_scope"]
    assert summary["promotion_readiness"] == report["promotion_readiness"]
    assert summary["per_config"]["B0"]["label_state"] == report["comparison_results"]["B0"]["label_state"]
    assert summary["per_config"]["B0"]["label_artifact_metadata"] == report["comparison_results"]["B0"]["label_artifact_metadata"]
    assert summary["per_config"]["B0"]["label_adjacent_metrics"] == report["comparison_results"]["B0"]["label_adjacent_metrics"]
    assert summary["per_config"]["B0"]["blocker_count"] == len(report["comparison_results"]["B0"]["blockers"])


def test_summary_projection_rejects_authority_mismatch_and_report_absent_label_fields(tmp_path: Path) -> None:
    report = _pool500_comparison_report_for_label_fixture(tmp_path)
    summary = json.loads(json.dumps(report["metrics_summary"]))
    summary["promotion_readiness"] = "promotion-ready"

    with pytest.raises(AssertionError):
        pool500_shadow_ranking.assert_pool500_summary_projection_matches_report(report, summary)

    summary = json.loads(json.dumps(report["metrics_summary"]))
    summary["label_metric_eligibility"] = not report["label_metric_eligibility"]

    with pytest.raises(AssertionError):
        pool500_shadow_ranking.assert_pool500_summary_projection_matches_report(report, summary)

    summary = json.loads(json.dumps(report["metrics_summary"]))
    summary["per_config"]["B0"]["promotion_ready"] = True

    with pytest.raises(AssertionError):
        pool500_shadow_ranking.assert_pool500_summary_projection_matches_report(report, summary)


def test_summary_projection_sanitizes_label_metadata_from_report(tmp_path: Path) -> None:
    label_path = _write_label_artifact_fixture(
        tmp_path,
        [{"schema_version": "pool500_label_artifact_v1", "user_id": "u1", "parent_asin": "i1", "label_binary": 1}],
    )
    report = _pool500_comparison_report_for_label_fixture(tmp_path, label_path=label_path)
    report = json.loads(json.dumps(report))
    report["comparison_results"]["B0"]["label_artifact_metadata"]["positive_pairs"] = [["u1", "i1"]]
    report["comparison_results"]["B0"]["label_artifact_metadata"]["ranked_positive_positions"] = {"u1\ti1": 1}

    summary = pool500_shadow_ranking.build_pool500_fixed_ranking_metrics_summary(report)

    assert "positive_pairs" not in summary["per_config"]["B0"]["label_artifact_metadata"]
    assert "ranked_positive_positions" not in summary["per_config"]["B0"]["label_artifact_metadata"]
    pool500_shadow_ranking.assert_pool500_summary_projection_matches_report(report, summary)


def test_summary_projection_rejects_label_metadata_internal_leak(tmp_path: Path) -> None:
    label_path = _write_label_artifact_fixture(
        tmp_path,
        [{"schema_version": "pool500_label_artifact_v1", "user_id": "u1", "parent_asin": "i1", "label_binary": 1}],
    )
    report = _pool500_comparison_report_for_label_fixture(tmp_path, label_path=label_path)
    summary = json.loads(json.dumps(report["metrics_summary"]))
    summary["per_config"]["B0"]["label_artifact_metadata"]["positive_pairs"] = [["u1", "i1"]]

    with pytest.raises(AssertionError):
        pool500_shadow_ranking.assert_pool500_summary_projection_matches_report(report, summary)


@pytest.mark.parametrize("forbidden_value", [FULL_POOL500_READY, "promotion-ready", "production-ready"])
def test_summary_projection_rejects_forbidden_ready_semantics_even_when_matched(tmp_path: Path, forbidden_value: str) -> None:
    report = _pool500_comparison_report_for_label_fixture(tmp_path)
    report = json.loads(json.dumps(report))
    report["label_ineligible_reason"] = forbidden_value
    summary = json.loads(json.dumps(report["metrics_summary"]))
    summary["label_ineligible_reason"] = forbidden_value

    with pytest.raises(AssertionError):
        pool500_shadow_ranking.assert_pool500_summary_projection_matches_report(report, summary)


@pytest.mark.parametrize("field", ["candidate", "challenger", "champion", "production_ready", "promotion_ready"])
def test_summary_projection_rejects_forbidden_machine_semantics_in_report(tmp_path: Path, field: str) -> None:
    report = _pool500_comparison_report_for_label_fixture(tmp_path)
    report = json.loads(json.dumps(report))
    report[field] = "R1"
    summary = json.loads(json.dumps(report["metrics_summary"]))

    with pytest.raises(AssertionError):
        pool500_shadow_ranking.assert_pool500_summary_projection_matches_report(report, summary)


def test_category_high_missing_plus_r1_diagnostic_followup_blocks_promotion_ready(tmp_path: Path) -> None:
    rows = [
        {"user_id": "u1", "item_id": "i1", "source": "co_visit_fallback_repair", "score": 1.0, "rank": 1, "metadata": {"fallback_used": True}},
        {"user_id": "u1", "item_id": "i2", "source": "popular", "score": 0.9, "rank": 2, "metadata": {"category": "cat"}},
    ]

    report = _pool500_comparison_report_for_label_fixture(tmp_path, rows=rows, label_evaluator_enabled=False)

    assert report["recommended_diagnostic_config_id"] == "R1"
    assert report["recommendation_scope"] == "diagnostic_followup_only"
    assert report["promotion_readiness"] == "not_allowed_in_this_report"
    assert report["comparison_results"]["R1"]["category_missing_rate"] >= 0.5
    assert report["comparison_results"]["R1"]["interpretation_label"] == "mechanism_only"
    assert "production-ready" not in json.dumps(report).lower()
    assert "promotion-ready" not in json.dumps(report).lower()


@pytest.mark.parametrize(
    "forbidden_payload",
    [
        {"source_artifact_gate_result": {"decision": FULL_POOL500_READY}},
        {"candidate": {"id": "pool500"}},
        {"challenger": "R1"},
        {"champion": "B0"},
        {"production_ready": True},
        {"promotion_ready": True},
        {"promotion_readiness": "promotion-ready"},
    ],
)
def test_label_aware_forbidden_semantics_fail_validation(forbidden_payload: dict[str, object]) -> None:
    evidence = {
        "schema_version": DIAGNOSTIC_FROZEN_POOL_SCHEMA_VERSION,
        "input_contract": "frozen_diagnostic_candidate_pool",
        "pool500_candidates_path": "pool500_candidates.jsonl",
        "candidate_manifest_path": "manifest.json",
        "expected_candidate_hash": "a",
        "computed_candidate_hash": "a",
        "expected_manifest_hash": "b",
        "computed_manifest_hash": "b",
        "user_count": 1,
        "underfilled_user_count": 0,
        "source_coverage": {"popular": 1},
        "category_coverage": {"cat": 1},
        "multi_source_item_ratio": 0.0,
        "metadata_missing_rate": 0.0,
        "category_missing_rate": 0.0,
        "top_category_ratio": 1.0,
        "candidate_generation_allowed": False,
        "ranking_input_replacement_allowed": False,
        "ranking_replacement_allowed": False,
        "promotion_allowed": False,
        "pool1000_allowed": False,
        "diagnostic_only": True,
        "not_ranking_input": True,
        "current_ranking_route_unchanged": True,
        "promotion_requires_future_plan": True,
        **forbidden_payload,
    }

    validation = validate_pool500_diagnostic_frozen_pool_ranking_evidence(evidence)

    assert validation["status"] == STOP


def test_label_artifact_discovery_precedence_and_known_output_not_consumed(tmp_path: Path) -> None:
    explicit_label = _write_label_artifact_fixture(
        tmp_path,
        [{"schema_version": "pool500_label_artifact_v1", "user_id": "u1", "parent_asin": "explicit", "label_binary": 1}],
        "explicit_labels.jsonl",
    )
    manifest_label = _write_label_artifact_fixture(
        tmp_path,
        [{"schema_version": "pool500_label_artifact_v1", "user_id": "u1", "parent_asin": "manifest", "label_binary": 1}],
        "manifest_labels.jsonl",
    )
    _write_label_artifact_fixture(
        tmp_path,
        [{"schema_version": "pool500_label_artifact_v1", "user_id": "u1", "parent_asin": "known", "label_binary": 1}],
        "pool500_labels.jsonl",
    )

    explicit_report = _pool500_comparison_report_for_label_fixture(
        tmp_path,
        rows=[{"user_id": "u1", "item_id": "explicit", "source": "popular", "score": 1.0, "rank": 1, "metadata": {"category": "cat"}}],
        manifest_overrides={"label_artifact_path": str(manifest_label)},
        label_path=explicit_label,
    )
    manifest_report = _pool500_comparison_report_for_label_fixture(
        tmp_path,
        rows=[{"user_id": "u1", "item_id": "manifest", "source": "popular", "score": 1.0, "rank": 1, "metadata": {"category": "cat"}}],
        manifest_overrides={"label_artifact_path": str(manifest_label)},
    )
    known_report = _pool500_comparison_report_for_label_fixture(
        tmp_path,
        rows=[{"user_id": "u1", "item_id": "known", "source": "popular", "score": 1.0, "rank": 1, "metadata": {"category": "cat"}}],
    )

    assert _summary_for_config(explicit_report)["label_artifact_metadata"]["path"] == str(explicit_label)
    assert _summary_for_config(explicit_report)["label_state"] == "label_comparable"
    assert _summary_for_config(manifest_report)["label_artifact_metadata"]["path"] == str(manifest_label)
    assert _summary_for_config(manifest_report)["label_state"] == "label_comparable"
    assert _summary_for_config(known_report)["label_state"] == "pending_label"
    assert _summary_for_config(known_report)["label_metrics_available"] is False
    assert _summary_for_config(known_report)["label_adjacent_metrics"] == {}


def test_label_artifact_manifest_nested_path_reaches_comparable_state(tmp_path: Path) -> None:
    manifest_label = _write_label_artifact_fixture(
        tmp_path,
        [{"schema_version": "pool500_label_artifact_v1", "user_id": "u1", "parent_asin": "i1", "label_binary": 1}],
        "manifest_nested_labels.jsonl",
    )

    report = _pool500_comparison_report_for_label_fixture(
        tmp_path,
        manifest_overrides={"label_artifact": {"path": manifest_label.name}},
    )
    summary = _summary_for_config(report)

    assert summary["label_state"] == "label_comparable"
    assert summary["label_artifact_metadata"]["path"] == str(manifest_label)
    assert summary["label_artifact_metadata"]["candidate_coverage"] == 1.0
    assert summary["label_artifact_metadata"]["user_coverage"] == 1.0
    assert summary["label_artifact_metadata"]["positive_coverage"] == 1.0
    assert summary["label_artifact_metadata"]["join_key"] == "user_id,parent_asin"
    assert report["metrics_summary"]["per_config"]["B0"]["label_state"] == "label_comparable"


def test_label_artifact_item_id_join_key_is_comparable_with_positive_coverage(tmp_path: Path) -> None:
    label_path = _write_label_artifact_fixture(
        tmp_path,
        [{"schema_version": "pool500_label_artifact_v1", "user_id": "u1", "item_id": "i1", "rating": 5}],
    )

    report = _pool500_comparison_report_for_label_fixture(tmp_path, label_path=label_path)
    summary = _summary_for_config(report)

    assert summary["label_state"] == "label_comparable"
    assert summary["label_metrics_available"] is True
    assert summary["label_artifact_metadata"]["join_key"] == "user_id,item_id"
    assert summary["label_artifact_metadata"]["candidate_coverage"] == 1.0
    assert summary["label_artifact_metadata"]["positive_coverage"] == 1.0
    assert summary["label_adjacent_metrics"]["label_positive_count"] == 1
    assert summary["label_adjacent_metrics"]["hit_at_20"] == 1.0


def test_label_artifact_zero_positive_coverage_is_not_comparable(tmp_path: Path) -> None:
    label_path = _write_label_artifact_fixture(
        tmp_path,
        [{"schema_version": "pool500_label_artifact_v1", "user_id": "u1", "parent_asin": "i1", "label_binary": 0}],
    )

    report = _pool500_comparison_report_for_label_fixture(tmp_path, label_path=label_path)
    summary = _summary_for_config(report)

    assert summary["label_state"] == "label_insufficient"
    assert summary["label_metrics_available"] is False
    assert summary["label_adjacent_metrics"] == {}
    assert summary["label_artifact_metadata"]["candidate_coverage"] == 1.0
    assert summary["label_artifact_metadata"]["user_coverage"] == 1.0
    assert summary["label_artifact_metadata"]["positive_coverage"] == 0.0


def test_label_aware_report_never_emits_readiness_or_formal_ready_semantics(tmp_path: Path) -> None:
    label_path = _write_label_artifact_fixture(
        tmp_path,
        [{"schema_version": "pool500_label_artifact_v1", "user_id": "u1", "parent_asin": "i1", "label_binary": 1}],
    )

    report = _pool500_comparison_report_for_label_fixture(tmp_path, label_path=label_path)
    serialized = json.dumps(report)

    assert report["promotion_readiness"] == "not_allowed_in_this_report"
    assert report["promotion_allowed"] is False
    assert report["ranking_input_replacement_allowed"] is False
    assert report["ranking_replacement_allowed"] is False
    assert "FULL_POOL500_READY" not in serialized
    assert "promotion-ready" not in serialized.lower()
    assert "production-ready" not in serialized.lower()
    assert "FULL_POOL500_READY" not in report["promotion_readiness"]


def test_run_pool500_shadow_ranking_has_no_formal_full_pool500_ready_path_usage() -> None:
    source = inspect.getsource(run_pool500_shadow_ranking)

    assert "FULL_POOL500_READY" not in source
