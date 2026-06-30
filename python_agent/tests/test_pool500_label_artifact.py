from __future__ import annotations

import json
from pathlib import Path

import pytest

from rs_lab.experiments.recall.build_pool500_label_artifact import build_pool500_label_artifact

pytestmark = pytest.mark.unit


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")


def test_pool500_label_artifact_parses_string_negative_labels_strictly(tmp_path: Path) -> None:
    candidates = tmp_path / "pool500_candidates.jsonl"
    labels = tmp_path / "labels.jsonl"
    _write_jsonl(candidates, [{"user_id": "u1", "item_id": "i1", "source": "popular", "score": 1.0, "rank": 1, "metadata": {"category": "cat"}}])
    _write_jsonl(labels, [{"user_id": "u1", "parent_asin": "i1", "label_binary": "0"}])

    result = build_pool500_label_artifact(
        pool500_candidates_path=candidates,
        interaction_labels_path=labels,
        output_dir=tmp_path / "out",
        enforce_venv=False,
    )

    assert result["label_artifact"]["positive_count"] == 0
    assert result["label_artifact"]["missing_reason_counts"] == {}


def test_pool500_label_artifact_contract_includes_coverage_diagnostics(tmp_path: Path) -> None:
    candidates = tmp_path / "pool500_candidates.jsonl"
    labels = tmp_path / "labels.jsonl"
    manifest = tmp_path / "manifest.json"
    _write_jsonl(
        candidates,
        [
            {"user_id": "u1", "item_id": "i1", "source": "popular", "score": 1.0, "rank": 1, "metadata": {"category": "cat"}},
            {"user_id": "u1", "item_id": "i2", "source": "semantic", "score": 0.9, "rank": 2, "metadata": {"category": "cat"}},
            {"user_id": "u2", "item_id": "i3", "source": "itemcf_strong", "score": 0.8, "rank": 1, "metadata": {"category": "cat2"}},
        ],
    )
    _write_jsonl(
        labels,
        [
            {"user_id": "u1", "parent_asin": "i1", "label_binary": 1, "split": "valid"},
            {"user_id": "u1", "parent_asin": "missing_item", "label_binary": 1, "split": "valid"},
            {"user_id": "u3", "parent_asin": "missing_user_item", "label_binary": 1, "split": "valid"},
            {"user_id": "u2", "parent_asin": "i3", "label_binary": 0, "split": "valid"},
        ],
    )
    manifest.write_text(json.dumps({"candidate_generation_allowed": False}), encoding="utf-8")

    result = build_pool500_label_artifact(
        pool500_candidates_path=candidates,
        interaction_labels_path=labels,
        output_dir=tmp_path / "out",
        candidate_manifest_path=manifest,
        update_candidate_manifest=True,
        enforce_venv=False,
    )

    artifact = result["label_artifact"]
    assert artifact["schema_version"] == "pool500_label_artifact_v1"
    assert artifact["row_count"] == 3
    assert artifact["positive_count"] == 1
    assert artifact["positive_overlap_count"] == 1
    assert artifact["positive_overlap_user_count"] == 1
    assert artifact["candidate_hit_rate"] == pytest.approx(1 / 3, abs=0.000001)
    assert artifact["missing_reason_counts"] == {"hit": 1, "item_not_in_candidate": 1, "user_missing": 1}
    assert artifact["label_source_summary"]["split_counts"] == {"valid": 4}
    label_rows = [json.loads(line) for line in Path(artifact["path"]).read_text(encoding="utf-8").splitlines()]
    assert {row["split"] for row in label_rows} == {"valid"}
    updated_manifest = json.loads(manifest.read_text(encoding="utf-8"))
    assert updated_manifest["label_artifact"]["positive_overlap_count"] == 1
    assert updated_manifest["label_artifact"]["missing_reason_counts"] == artifact["missing_reason_counts"]
