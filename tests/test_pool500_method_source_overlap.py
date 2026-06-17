from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from rs_core.common.io import read_json
from scripts.experiments.recall.pool500.analyze_method_source_overlap import analyze_method_source_overlap

pytestmark = pytest.mark.unit


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def test_analyze_method_source_overlap_reports_user_and_item_overlap(tmp_path: Path) -> None:
    primary_candidates = tmp_path / "primary" / "candidates.jsonl"
    primary_manifest = tmp_path / "primary" / "source_index_manifest.json"
    baseline_candidates = tmp_path / "baseline" / "candidates.jsonl"
    baseline_manifest = tmp_path / "baseline" / "source_index_manifest.json"
    output_dir = tmp_path / "overlap"

    _write_jsonl(
        primary_candidates,
        [
            {"user_id": "u1", "item_id": "a", "rank": 1},
            {"user_id": "u1", "item_id": "b", "rank": 2},
            {"user_id": "u2", "item_id": "c", "rank": 1},
        ],
    )
    _write_json(primary_manifest, {"source": "co_visit_fallback_repair", "candidates_path": str(primary_candidates), "candidate_generation_allowed": False})
    _write_jsonl(
        baseline_candidates,
        [
            {"user_id": "u1", "item_id": "a", "rank": 1},
            {"user_id": "u1", "item_id": "x", "rank": 2},
            {"user_id": "u3", "item_id": "c", "rank": 1},
        ],
    )
    _write_json(baseline_manifest, {"source": "category", "candidates_path": str(baseline_candidates)})

    report = analyze_method_source_overlap(
        primary_source_index_manifest=primary_manifest,
        baseline_source_index_manifests=[baseline_manifest],
        output_dir=output_dir,
        target_per_user=2,
        overwrite=True,
        enforce_venv=False,
    )

    saved = read_json(output_dir / "source_overlap_report.json")
    overlap = saved["baseline_overlap"][0]
    assert report["status"] == "PASS"
    assert saved["primary_underfilled_user_count"] == 1
    assert overlap["baseline_source"] == "category"
    assert overlap["user_level_overlap_row_count"] == 1
    assert overlap["user_level_overlap_ratio"] == pytest.approx(0.5)
    assert overlap["item_union_overlap_count"] == 2
