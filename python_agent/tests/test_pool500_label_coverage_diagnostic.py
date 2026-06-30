from __future__ import annotations

import json
from pathlib import Path

import pytest

from rs_lab.experiments.recall.diagnose_pool500_label_coverage import diagnose_pool500_label_coverage

pytestmark = pytest.mark.unit


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")


def test_pool500_label_coverage_reports_hits_and_missing_reasons(tmp_path: Path) -> None:
    candidates = tmp_path / "candidates.jsonl"
    valid = tmp_path / "canonical_interactions.valid.jsonl"
    test = tmp_path / "canonical_interactions.test.jsonl"
    _write_jsonl(
        candidates,
        [
            {"user": "u1", "item": "i1", "rank": 1, "source": "popular"},
            {"user": "u1", "item": "i2", "rank": 30, "source": "itemcf_strong"},
            {"user": "u2", "item": "i3", "rank": 120, "source": "semantic_title_category_expansion"},
        ],
    )
    _write_jsonl(
        valid,
        [
            {"user_id": "u1", "parent_asin": "i1", "label_binary": 1, "split": "valid"},
            {"user_id": "u1", "parent_asin": "missing_item", "label_binary": 1, "split": "valid"},
            {"user_id": "u2", "parent_asin": "i3", "label_binary": 0, "split": "valid"},
        ],
    )
    _write_jsonl(
        test,
        [
            {"user_id": "u2", "parent_asin": "i3", "label_binary": 1, "split": "test"},
            {"user_id": "u3", "parent_asin": "i9", "label_binary": 1, "split": "test"},
        ],
    )

    report = diagnose_pool500_label_coverage(
        pool500_candidates_path=candidates,
        label_paths=[valid, test],
        output_dir=tmp_path / "out",
        enforce_venv=False,
    )

    assert report["diagnostic_only"] is True
    assert report["candidate_generation_allowed"] is False
    assert report["ranking_input_replacement_allowed"] is False
    assert report["full_pool500_ready_declared"] is False
    assert report["candidate"]["candidate_users"] == 2
    assert report["candidate"]["candidate_items"] == 3
    assert report["labels"]["label_users"] == 3
    assert report["labels"]["label_positives"] == 4
    assert report["labels"]["overlap_users"] == 2
    assert report["labels"]["positive_overlap_count"] == 2
    assert report["labels"]["positive_coverage"] == 0.5
    assert report["labels"]["user_coverage"] == pytest.approx(2 / 3, abs=0.000001)
    assert report["labels"]["hit_distribution"] == {"top_20": 1, "top_50": 1, "top_100": 1, "top_500": 2}
    assert report["labels"]["missing_reason_counts"] == {"hit": 2, "item_not_in_candidate": 1, "user_missing": 1}
    assert Path(report["output_path"]).is_file()


def test_pool500_label_coverage_deduplicates_positive_pairs(tmp_path: Path) -> None:
    candidates = tmp_path / "candidates.jsonl"
    labels = tmp_path / "canonical_interactions.valid.jsonl"
    _write_jsonl(candidates, [{"user_id": "u1", "parent_asin": "i1", "rank": 5, "source": "popular"}])
    _write_jsonl(
        labels,
        [
            {"user_id": "u1", "parent_asin": "i1", "label_binary": 1},
            {"user_id": "u1", "parent_asin": "i1", "label_binary": 1},
        ],
    )

    report = diagnose_pool500_label_coverage(
        pool500_candidates_path=candidates,
        label_paths=[labels],
        output_dir=tmp_path / "out",
        enforce_venv=False,
    )

    assert report["labels"]["label_positives"] == 1
    assert report["labels"]["positive_overlap_count"] == 1
    assert report["labels"]["hit_distribution"]["top_20"] == 1
