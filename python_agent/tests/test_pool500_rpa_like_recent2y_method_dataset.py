from __future__ import annotations

from pathlib import Path

import pytest

from rs_core.common.io import iter_jsonl, read_json, write_json, write_jsonl
from rs_lab.experiments.recall.build_rpa_like_recent2y_method_dataset import (
    MAX_ALLOWED_RSS_MB,
    RPALikeRecent2YDatasetConfig,
    build_rpa_like_recent2y_method_dataset,
)

pytestmark = pytest.mark.unit


def test_rpa_like_recent2y_smoke_writes_balanced_train_only_rows(tmp_path: Path) -> None:
    data_root = _write_dataset_fixture(tmp_path)
    output_dir = tmp_path / "outputs" / "smoke"

    manifest = build_rpa_like_recent2y_method_dataset(
        RPALikeRecent2YDatasetConfig(
            data_root=data_root,
            output_dir=output_dir,
            run_id="smoke_fixture",
            scale_tier="smoke",
            smoke_user_limit=4,
            max_rss_mb=MAX_ALLOWED_RSS_MB,
            overwrite=True,
            enforce_venv=False,
        )
    )

    rows = list(iter_jsonl(output_dir / "method_dataset_rows.jsonl"))
    assert manifest["status"] == "PASS"
    assert manifest["dataset_tier"] == "smoke"
    assert manifest["row_schema_version"] == "rpa_like_eligible_sequence_v1"
    assert manifest["diagnostic_only"] is True
    assert manifest["train_only"] is True
    assert manifest["candidate_generation_allowed"] is False
    assert manifest["promotion_allowed"] is False
    assert manifest["ready_source_artifact"] is False
    assert manifest["policy"]["paper_reference"]["doi"] == "10.1145/1297231.1297241"
    assert {row["target_bucket"] for row in rows} == {"sparse_seq_len_eq1", "medium_like_seq_len_2_4"}
    assert all(row["train_only"] is True for row in rows)
    assert all(row["diagnostic_only"] is True for row in rows)
    assert all(row["candidate_generation_allowed"] is False for row in rows)
    assert all(1 <= row["eligible_seed_item_count"] <= 4 for row in rows)
    assert not (output_dir / "source_index_manifest.json").exists()
    assert not (output_dir / "candidates.jsonl").exists()

    no_oracle = read_json(output_dir / "no_oracle_audit.json")
    assert no_oracle["status"] == "PASS"
    assert no_oracle["uses_valid"] is False
    assert no_oracle["uses_test"] is False
    assert no_oracle["eval_labels_used_for_candidate_generation"] is False


def test_rpa_like_recent2y_formal_keeps_all_eligible_short_sequence_users(tmp_path: Path) -> None:
    data_root = _write_dataset_fixture(tmp_path)
    output_dir = tmp_path / "outputs" / "formal"

    manifest = build_rpa_like_recent2y_method_dataset(
        RPALikeRecent2YDatasetConfig(
            data_root=data_root,
            output_dir=output_dir,
            run_id="formal_fixture",
            scale_tier="formal",
            max_rss_mb=MAX_ALLOWED_RSS_MB,
            overwrite=True,
            enforce_venv=False,
        )
    )

    rows = list(iter_jsonl(output_dir / "method_dataset_rows.jsonl"))
    assert manifest["dataset_tier"] == "formal"
    assert manifest["policy"]["sample_count_caps"] == "none"
    assert {row["user_id"] for row in rows} == {"u_sparse", "u_medium", "u_four"}
    assert manifest["bucket_counts"] == {"sparse_seq_len_eq1": 1, "medium_like_seq_len_2_4": 2}
    assert manifest["dropped_reason_counts"]["sequence_too_long_for_rpa_like"] == 1
    assert manifest["dropped_reason_counts"]["user_quality_missing"] == 1
    assert manifest["dropped_reason_counts"]["empty_sequence_after_item_filter"] == 1
    blocked_row = next(row for row in rows if row["user_id"] == "u_four")
    assert blocked_row["dropped_seed_reasons"] == {"item_quality_bucket_not_allowed": 1}


def test_rpa_like_recent2y_rejects_forbidden_paths(tmp_path: Path) -> None:
    data_root = _write_dataset_fixture(tmp_path / "pool1000")

    with pytest.raises(ValueError, match="Forbidden input"):
        build_rpa_like_recent2y_method_dataset(
            RPALikeRecent2YDatasetConfig(
                data_root=data_root,
                output_dir=tmp_path / "outputs" / "bad",
                run_id="bad",
                scale_tier="smoke",
                enforce_venv=False,
            )
        )


def test_rpa_like_recent2y_rejects_rss_above_local_5g_contract(tmp_path: Path) -> None:
    data_root = _write_dataset_fixture(tmp_path)

    with pytest.raises(ValueError, match="local 5G memory contract"):
        build_rpa_like_recent2y_method_dataset(
            RPALikeRecent2YDatasetConfig(
                data_root=data_root,
                output_dir=tmp_path / "outputs" / "rss",
                run_id="rss_bad",
                scale_tier="smoke",
                max_rss_mb=MAX_ALLOWED_RSS_MB + 1,
                enforce_venv=False,
            )
        )


def test_rpa_like_recent2y_writes_resource_audit(tmp_path: Path) -> None:
    data_root = _write_dataset_fixture(tmp_path)
    output_dir = tmp_path / "outputs" / "resource"

    build_rpa_like_recent2y_method_dataset(
        RPALikeRecent2YDatasetConfig(
            data_root=data_root,
            output_dir=output_dir,
            run_id="resource_fixture",
            scale_tier="smoke",
            smoke_user_limit=2,
            max_rss_mb=MAX_ALLOWED_RSS_MB,
            overwrite=True,
            enforce_venv=False,
        )
    )

    resource = read_json(output_dir / "resource_audit.json")
    assert resource["status"] == "PASS"
    assert resource["resource_status"] == "PASS"
    assert resource["max_allowed_rss_mb"] == MAX_ALLOWED_RSS_MB
    assert resource["peak_rss_mb"] > 0
    assert resource["peak_rss_mb"] <= MAX_ALLOWED_RSS_MB
    assert resource["memory_samples"]
    assert {sample["stage"] for sample in resource["memory_samples"]} >= {"start", "after_rows_written", "end"}


def _write_dataset_fixture(tmp_path: Path) -> Path:
    data_root = tmp_path / "recent2y"
    governance_root = data_root / "train_only_governance"
    governance_root.mkdir(parents=True)
    write_json(data_root / "manifest.json", {"schema_version": "recent_window_2y_1m_3m_v1"})
    write_json(governance_root / "manifest.json", {"schema_version": "train_only_governance_v1", "train_only": True})
    write_jsonl(
        governance_root / "user_quality_profile.jsonl",
        [
            {"user_id": "u_sparse", "quality_bucket_v2": "fallback_only"},
            {"user_id": "u_medium", "quality_bucket_v2": "fallback_only"},
            {"user_id": "u_four", "quality_bucket_v2": "sequence_sufficient"},
            {"user_id": "u_long", "quality_bucket_v2": "collaborative_rich"},
            {"user_id": "u_empty_after_filter", "quality_bucket_v2": "fallback_only"},
        ],
    )
    write_jsonl(
        governance_root / "item_quality_profile.jsonl",
        [
            {"parent_asin": "i1", "quality_bucket_v2": "cf_ready"},
            {"parent_asin": "i2", "quality_bucket_v2": "cf_ready"},
            {"parent_asin": "i3", "quality_bucket_v2": "cf_ready"},
            {"parent_asin": "i4", "quality_bucket_v2": "cf_ready"},
            {"parent_asin": "i5", "quality_bucket_v2": "cf_ready"},
            {"parent_asin": "i_bad", "quality_bucket_v2": "blocked"},
        ],
    )
    write_jsonl(
        governance_root / "item_frequency_train.jsonl",
        [
            {"parent_asin": "i1", "user_count": 5},
            {"parent_asin": "i2", "user_count": 3},
            {"parent_asin": "i3", "user_count": 2},
            {"parent_asin": "i4", "user_count": 1},
            {"parent_asin": "i5", "user_count": 1},
            {"parent_asin": "i_bad", "user_count": 10},
        ],
    )
    write_jsonl(
        data_root / "user_sequences.train.jsonl",
        [
            {
                "user_id": "u_sparse",
                "sequence_len": 1,
                "positive_sequence_len": 1,
                "recent_positive_item_sequence": ["i1"],
                "recent_positive_timestamp_sequence": [1],
            },
            {
                "user_id": "u_medium",
                "sequence_len": 2,
                "positive_sequence_len": 2,
                "recent_positive_item_sequence": ["i1", "i2"],
                "recent_positive_timestamp_sequence": [1, 2],
            },
            {
                "user_id": "u_four",
                "sequence_len": 5,
                "positive_sequence_len": 5,
                "recent_positive_item_sequence": ["i1", "i2", "i3", "i4", "i_bad"],
                "recent_positive_timestamp_sequence": [1, 2, 3, 4, 5],
            },
            {
                "user_id": "u_long",
                "sequence_len": 5,
                "positive_sequence_len": 5,
                "recent_positive_item_sequence": ["i1", "i2", "i3", "i4", "i5"],
                "recent_positive_timestamp_sequence": [1, 2, 3, 4, 5],
            },
            {
                "user_id": "u_missing_quality",
                "sequence_len": 1,
                "positive_sequence_len": 1,
                "recent_positive_item_sequence": ["i1"],
                "recent_positive_timestamp_sequence": [1],
            },
            {
                "user_id": "u_empty_after_filter",
                "sequence_len": 1,
                "positive_sequence_len": 1,
                "recent_positive_item_sequence": ["i_missing"],
                "recent_positive_timestamp_sequence": [1],
            },
        ],
    )
    write_jsonl(data_root / "canonical_interactions.valid.jsonl", [{"user_id": "u_sparse", "parent_asin": "label"}])
    write_jsonl(data_root / "canonical_interactions.test.jsonl", [{"user_id": "u_medium", "parent_asin": "label"}])
    return data_root
