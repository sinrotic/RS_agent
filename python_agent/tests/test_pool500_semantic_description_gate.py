from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.experiments.recall.pool500.audit_semantic_description_evidence_gate import (
    DIAGNOSTIC_ONLY,
    PASS_GUARDED_CANDIDATE,
    STOP,
    build_semantic_description_evidence_gate,
)

pytestmark = pytest.mark.unit


def _write_report(path: Path, summary: dict[str, object]) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    report = path / "semantic_description_recall_strict_report.json"
    report.write_text(json.dumps({"summary": summary}, ensure_ascii=False), encoding="utf-8")
    return report


def _passing_summary() -> dict[str, object]:
    return {
        "schema_version": "semantic_description_recall_strict_v1",
        "eval_scope": "train_metadata_description_diagnostic_only",
        "label_inputs_role": "not_used",
        "oracle_label_injection": False,
        "query_count": 6,
        "avg_strict_precision_at_5": 0.9,
        "avg_strict_precision_at_10": 0.9,
        "avg_required_precision_at_10": 1.0,
        "avg_bad_intent_rate_at_10": 0.1,
        "queries_with_strict_hit_top5": 6,
        "queries_strict_p10_ge_0_5": 6,
    }


def test_semantic_description_gate_passes_guarded_candidate_evidence(tmp_path: Path) -> None:
    report_dir = tmp_path / "semantic_description_random6"
    _write_report(report_dir, _passing_summary())

    gate = build_semantic_description_evidence_gate(diagnostic_path=report_dir)

    assert gate["decision"] == PASS_GUARDED_CANDIDATE
    assert gate["status"] == "PASS"
    assert gate["summary"]["avg_strict_precision_at_10"] == pytest.approx(0.9)
    assert gate["candidate_generation_allowed"] is False
    assert gate["ranking_input_replacement_allowed"] is False
    assert gate["promotion_allowed"] is False
    assert gate["pool1000_allowed"] is False
    assert gate["final_pool500_ready_claimed"] is False


def test_semantic_description_gate_keeps_weak_strict_fixture_diagnostic_only(tmp_path: Path) -> None:
    report_dir = tmp_path / "semantic_description_strict_v2"
    summary = _passing_summary() | {"query_count": 12, "avg_strict_precision_at_10": 0.483, "avg_bad_intent_rate_at_10": 0.267}
    _write_report(report_dir, summary)

    gate = build_semantic_description_evidence_gate(diagnostic_path=report_dir)

    assert gate["decision"] == DIAGNOSTIC_ONLY
    assert set(gate["diagnostics"]) == {
        "avg_strict_precision_at_10_below_guard_threshold",
        "avg_bad_intent_rate_at_10_above_guard_threshold",
    }
    assert gate["promotion_allowed"] is False


def test_semantic_description_gate_stops_on_oracle_or_forbidden_scope(tmp_path: Path) -> None:
    report_dir = tmp_path / "oracle" / "semantic_description"
    summary = _passing_summary() | {"oracle_label_injection": True}
    _write_report(report_dir, summary)

    gate = build_semantic_description_evidence_gate(diagnostic_path=report_dir)

    assert gate["decision"] == STOP
    assert set(gate["blockers"]) >= {"oracle_label_injection_true", "forbidden_scope_in_semantic_description_evidence"}
    assert gate["forbidden_scope_audit"]["status"] == "BLOCKED"
