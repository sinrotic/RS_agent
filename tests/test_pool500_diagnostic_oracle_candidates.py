from __future__ import annotations

import json
from pathlib import Path

import pytest

from rs_lab.experiments.recall.build_pool500_diagnostic_oracle_candidates import build_pool500_diagnostic_oracle_candidates
from rs_lab.experiments.recall.diagnose_pool500_label_coverage import diagnose_pool500_label_coverage

pytestmark = pytest.mark.unit


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def test_diagnostic_oracle_candidates_inject_positive_labels_and_keep_pool_size(tmp_path: Path) -> None:
    base = tmp_path / "base_candidates.jsonl"
    labels = tmp_path / "canonical_interactions.valid.jsonl"
    target_manifest = tmp_path / "aligned_eval_users_manifest.json"
    _write_jsonl(
        base,
        [
            {"user_id": "u1", "item_id": "base1", "source": "usercf_recall", "sources": ["usercf_recall"], "score": 0.3, "rank": 1, "metadata": {}},
            {"user_id": "u1", "item_id": "base2", "source": "two_tower", "sources": ["two_tower"], "score": 0.2, "rank": 2, "metadata": {}},
            {"user_id": "u1", "item_id": "already_hit", "source": "category", "sources": ["category"], "score": 0.1, "rank": 3, "metadata": {}},
            {"user_id": "u2", "item_id": "u2_base", "source": "popular", "sources": ["popular"], "score": 0.1, "rank": 1, "metadata": {}},
        ],
    )
    _write_jsonl(
        labels,
        [
            {"user_id": "u1", "parent_asin": "oracle1", "label_binary": 1, "split": "valid"},
            {"user_id": "u1", "parent_asin": "oracle2", "label_binary": 1, "split": "valid"},
            {"user_id": "u1", "parent_asin": "already_hit", "label_binary": 1, "split": "valid"},
            {"user_id": "u2", "parent_asin": "ignored_negative", "label_binary": 0, "split": "valid"},
        ],
    )
    _write_json(
        target_manifest,
        {
            "diagnostic_only": True,
            "candidate_generation_allowed": False,
            "ranking_input_replacement_allowed": False,
            "ranking_replacement_allowed": False,
            "promotion_allowed": False,
            "pool1000_allowed": False,
            "final_pool500_ready_claimed": False,
            "full_pool500_ready_declared": False,
            "target_user_ids": ["u1"],
        },
    )

    result = build_pool500_diagnostic_oracle_candidates(
        base_candidates_path=base,
        label_paths=[labels],
        output_dir=tmp_path / "out",
        target_user_manifest_path=target_manifest,
        min_positive_overlap=3,
        candidate_pool_size=3,
        enforce_venv=False,
    )

    output_rows = _read_jsonl(Path(result["output_path"]))
    assert result["status"] == "PASS"
    assert result["diagnostic_only"] is True
    assert result["candidate_generation_allowed"] is False
    assert result["ranking_input_replacement_allowed"] is False
    assert result["promotion_allowed"] is False
    assert result["oracle_positive_overlap_count"] == 3
    assert result["injection_summary"]["oracle_added_new_count"] == 2
    assert result["injection_summary"]["oracle_promoted_existing_count"] == 1
    assert len(output_rows) == 3
    assert {row["item_id"] for row in output_rows} == {"oracle1", "oracle2", "already_hit"}
    assert [row["rank"] for row in output_rows] == [1, 2, 3]
    assert {row["source"] for row in output_rows} == {"diagnostic_oracle_candidate"}

    report = diagnose_pool500_label_coverage(
        pool500_candidates_path=Path(result["output_path"]),
        label_paths=[labels],
        output_dir=tmp_path / "coverage",
        enforce_venv=False,
    )
    assert report["labels"]["positive_overlap_count"] == 3
    assert report["labels"]["hit_distribution"] == {"top_20": 3, "top_50": 3, "top_100": 3, "top_500": 3}


def test_diagnostic_oracle_candidates_reject_path_escape_output_names(tmp_path: Path) -> None:
    base = tmp_path / "base_candidates.jsonl"
    labels = tmp_path / "labels.jsonl"
    _write_jsonl(base, [{"user_id": "u1", "item_id": "base1", "source": "popular", "score": 1.0, "rank": 1, "metadata": {}}])
    _write_jsonl(labels, [{"user_id": "u1", "parent_asin": "oracle1", "label_binary": 1}])

    with pytest.raises(ValueError, match="simple file name"):
        build_pool500_diagnostic_oracle_candidates(
            base_candidates_path=base,
            label_paths=[labels],
            output_dir=tmp_path / "out",
            output_name="../pool500_candidates.jsonl",
            enforce_venv=False,
        )

    with pytest.raises(ValueError, match="simple file name"):
        build_pool500_diagnostic_oracle_candidates(
            base_candidates_path=base,
            label_paths=[labels],
            output_dir=tmp_path / "out",
            manifest_name=str(tmp_path / "escaped_manifest.json"),
            enforce_venv=False,
        )


def test_diagnostic_oracle_candidates_require_explicit_label_field(tmp_path: Path) -> None:
    base = tmp_path / "base_candidates.jsonl"
    labels = tmp_path / "labels.jsonl"
    _write_jsonl(base, [{"user_id": "u1", "item_id": "base1", "source": "popular", "score": 1.0, "rank": 1, "metadata": {}}])
    _write_jsonl(labels, [{"user_id": "u1", "parent_asin": "oracle1"}])

    with pytest.raises(ValueError, match="explicit label_binary or label"):
        build_pool500_diagnostic_oracle_candidates(
            base_candidates_path=base,
            label_paths=[labels],
            output_dir=tmp_path / "out",
            enforce_venv=False,
        )


def test_diagnostic_oracle_candidates_reject_underfilled_pools(tmp_path: Path) -> None:
    base = tmp_path / "base_candidates.jsonl"
    labels = tmp_path / "labels.jsonl"
    _write_jsonl(base, [{"user_id": "u1", "item_id": "base1", "source": "popular", "score": 1.0, "rank": 1, "metadata": {}}])
    _write_jsonl(labels, [{"user_id": "u1", "parent_asin": "oracle1", "label_binary": 1}])

    with pytest.raises(ValueError, match="underfilled candidate pool"):
        build_pool500_diagnostic_oracle_candidates(
            base_candidates_path=base,
            label_paths=[labels],
            output_dir=tmp_path / "out",
            candidate_pool_size=3,
            enforce_venv=False,
        )


def test_diagnostic_oracle_candidates_fail_closed_on_non_diagnostic_target_manifest(tmp_path: Path) -> None:
    base = tmp_path / "base_candidates.jsonl"
    labels = tmp_path / "labels.jsonl"
    target_manifest = tmp_path / "target_manifest.json"
    _write_jsonl(base, [{"user_id": "u1", "item_id": "base1", "source": "popular", "score": 1.0, "rank": 1, "metadata": {}}])
    _write_jsonl(labels, [{"user_id": "u1", "parent_asin": "oracle1", "label_binary": 1}])
    _write_json(target_manifest, {"diagnostic_only": False, "candidate_generation_allowed": True, "target_user_ids": ["u1"]})

    with pytest.raises(ValueError, match="diagnostic_only=true"):
        build_pool500_diagnostic_oracle_candidates(
            base_candidates_path=base,
            label_paths=[labels],
            output_dir=tmp_path / "out",
            target_user_manifest_path=target_manifest,
            enforce_venv=False,
        )


def test_diagnostic_oracle_candidates_reject_unsafe_target_manifest_flags(tmp_path: Path) -> None:
    base = tmp_path / "base_candidates.jsonl"
    labels = tmp_path / "labels.jsonl"
    target_manifest = tmp_path / "target_manifest.json"
    _write_jsonl(base, [{"user_id": "u1", "item_id": "base1", "source": "popular", "score": 1.0, "rank": 1, "metadata": {}}])
    _write_jsonl(labels, [{"user_id": "u1", "parent_asin": "oracle1", "label_binary": 1}])
    _write_json(
        target_manifest,
        {
            "diagnostic_only": True,
            "candidate_generation_allowed": False,
            "ranking_input_replacement_allowed": False,
            "ranking_replacement_allowed": False,
            "promotion_allowed": True,
            "pool1000_allowed": False,
            "final_pool500_ready_claimed": False,
            "full_pool500_ready_declared": False,
            "target_user_ids": ["u1"],
        },
    )

    with pytest.raises(ValueError, match="promotion_allowed=false"):
        build_pool500_diagnostic_oracle_candidates(
            base_candidates_path=base,
            label_paths=[labels],
            output_dir=tmp_path / "out",
            target_user_manifest_path=target_manifest,
            enforce_venv=False,
        )
