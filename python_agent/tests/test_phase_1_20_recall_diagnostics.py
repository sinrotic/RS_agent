from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.experiment

from rs_core.common.io import write_jsonl
from rs_lab.experiments.recall import phase_1_20_recall_diagnostics as diagnostics


REQUIRED_COMMON_FIELDS = {
    "baseline_config_path",
    "baseline_config_hash",
    "evaluation_mode",
    "split",
    "users_with_holdout",
    "hit_rate_denominator",
    "limit_users",
    "run_id",
    "output_dir",
}
EXPECTED_ORACLE_STAGES = {
    "raw_non_popular_before_fallback",
    "raw_with_fallback_before_merge",
    "merged_before_pool_limit",
    "pool_after_limit",
}


def test_phase_1_20_diagnostics_limited_run_writes_isolated_artifacts_and_keeps_baseline_unchanged(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    baseline_config = _write_diagnostics_fixture(tmp_path)
    output_dir = tmp_path / "diagnostics_out"
    baseline_before = baseline_config.read_bytes()
    baseline_hash_before = _sha256(baseline_config)

    monkeypatch.setattr(
        "sys.argv",
        [
            "phase_1_20_recall_diagnostics.py",
            "--baseline-config",
            str(baseline_config),
            "--output-dir",
            str(output_dir),
            "--limit-users",
            "1",
        ],
    )

    diagnostics.main()

    assert baseline_config.read_bytes() == baseline_before
    assert _sha256(baseline_config) == baseline_hash_before

    manifest_path = output_dir / "run_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["baseline_config_hash"] == baseline_hash_before
    assert manifest["hit_rate_denominator"] == "users_with_holdout"
    assert REQUIRED_COMMON_FIELDS <= set(manifest)

    expected_artifacts = {
        "pool_size_curve_csv": output_dir / "pool_size_curve" / "pool_size_curve.csv",
        "raw_candidate_oracle_csv": output_dir / "raw_candidate_oracle" / "raw_candidate_oracle.csv",
        "miss_analysis_csv": output_dir / "miss_analysis" / "miss_analysis.csv",
        "source_overlap_csv": output_dir / "miss_analysis" / "source_overlap.csv",
        "target_metadata_slices_csv": output_dir / "target_metadata_slices" / "target_metadata_slices.csv",
        "miss_user_opportunities_csv": output_dir / "miss_analysis" / "miss_user_opportunities.csv",
        "opportunity_gate_summary_json": output_dir / "miss_analysis" / "opportunity_gate_summary.json",
    }
    assert manifest["artifacts"] == {key: str(path) for key, path in expected_artifacts.items()}
    for path in expected_artifacts.values():
        assert path.is_file()
        assert output_dir.resolve() in path.resolve().parents

    for json_path in [
        output_dir / "pool_size_curve" / "pool_size_curve.json",
        output_dir / "raw_candidate_oracle" / "raw_candidate_oracle.json",
        output_dir / "miss_analysis" / "miss_analysis.json",
        output_dir / "miss_analysis" / "source_overlap.json",
        output_dir / "target_metadata_slices" / "target_metadata_slices.json",
        output_dir / "miss_analysis" / "miss_user_opportunities.json",
        output_dir / "miss_analysis" / "opportunity_gate_summary.json",
    ]:
        assert json_path.is_file()
        assert output_dir.resolve() in json_path.resolve().parents

    oracle_rows = _read_csv(output_dir / "raw_candidate_oracle" / "raw_candidate_oracle.csv")
    assert {row["stage"] for row in oracle_rows} == EXPECTED_ORACLE_STAGES
    assert all(REQUIRED_COMMON_FIELDS <= set(row) for row in oracle_rows)
    assert all(row["hit_rate_denominator"] == "users_with_holdout" for row in oracle_rows)

    pool_rows = _read_csv(output_dir / "pool_size_curve" / "pool_size_curve.csv")
    assert pool_rows
    assert all(REQUIRED_COMMON_FIELDS <= set(row) for row in pool_rows)
    assert all(row["hit_rate_denominator"] == "users_with_holdout" for row in pool_rows)

    gate_summary = json.loads((output_dir / "miss_analysis" / "opportunity_gate_summary.json").read_text(encoding="utf-8"))
    assert gate_summary["decision_scope"] == "recall_only_opportunity_gate"
    assert gate_summary["no_leakage_scope"] == "holdout targets diagnose opportunity only; candidate generation uses training-visible sequence and item metadata only"


def _write_diagnostics_fixture(root: Path) -> Path:
    clean = root / "clean"
    views = root / "views"
    clean.mkdir()
    views.mkdir()

    write_jsonl(clean / "user_sequences.train.jsonl", [{
        "user_id": "u1",
        "recent_item_sequence": ["seed_audio"],
        "recent_positive_item_sequence": ["seed_audio"],
        "recent_strong_positive_item_sequence": [],
        "sequence_len": 1,
    }])
    write_jsonl(clean / "canonical_interactions.valid.jsonl", [{"user_id": "u1", "parent_asin": "speaker_1", "label_binary": 1}])
    write_jsonl(views / "popular_recall.jsonl", [
        {"parent_asin": "charger_1", "category": "Accessories", "pop_score": 5, "title_clean": "USB charger"},
    ])
    write_jsonl(views / "itemcf_recall_weak.jsonl", [
        {"src_item": "seed_audio", "dst_item": "speaker_1", "score": 2.0, "category": "Audio", "title_clean": "Bluetooth speaker"},
    ])
    write_jsonl(views / "itemcf_recall_strong.jsonl", [])
    write_jsonl(views / "category_recall_items.jsonl", [
        {"parent_asin": "seed_audio", "main_category": "Audio"},
        {"parent_asin": "speaker_1", "main_category": "Audio"},
    ])
    write_jsonl(views / "category_top_items.jsonl", [{"bucket": "main::Audio", "top_items": [
        {"parent_asin": "speaker_1", "score": 1.0, "category": "Audio", "title_clean": "Bluetooth speaker"},
    ]}])

    config = root / "baseline.yaml"
    config.write_text(json.dumps({
        "clean_dir": str(clean),
        "views_dir": str(views),
        "output_dir": str(root / "unused_baseline_output"),
        "report_path": str(root / "unused_baseline_report.md"),
        "evaluation_mode": "valid_test",
        "top_k": 3,
        "candidate_pool_size": 100,
        "popular_fallback_count": 3,
        "rank_weights": {
            "popular": 1.0,
            "itemcf_weak": 1.0,
            "itemcf_strong": 1.0,
            "category": 1.0,
        },
    }), encoding="utf-8")
    return config


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
