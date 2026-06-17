from __future__ import annotations

from pathlib import Path

from rs_core.common.io import write_json, write_jsonl
from rs_lab.experiments.recall.pool500.methods.category.builder import expand_category_candidates_for_users


def test_category_on_demand_expands_requested_users_from_index_only_artifacts(tmp_path: Path) -> None:
    artifact_dir = tmp_path / "category_all_eligible"
    artifact_dir.mkdir()
    method_manifest_path = artifact_dir / "method_dataset_manifest.json"
    source_manifest_path = artifact_dir / "source_index_manifest.json"
    eligible_users_path = artifact_dir / "eligible_users.jsonl"
    profile_path = artifact_dir / "user_category_profile.jsonl"
    top_items_path = artifact_dir / "category_top_items_index.jsonl"
    train_sequences_path = artifact_dir / "train_user_sequences.jsonl"
    coverage_path = artifact_dir / "coverage_audit.json"
    resource_path = artifact_dir / "resource_audit.json"

    write_jsonl(
        eligible_users_path,
        [
            {"user_id": "u1", "quality_bucket": "medium_behavior", "sequence_len": 2, "positive_count": 1, "unique_item_count": 2},
            {"user_id": "u2", "quality_bucket": "medium_behavior", "sequence_len": 1, "positive_count": 0, "unique_item_count": 1},
        ],
    )
    write_jsonl(
        profile_path,
        [
            {
                "user_id": "u1",
                "top_profile_buckets": [
                    {"bucket": "main::Books", "weight": 1.0, "share": 1.0, "seed_hit_count": 1, "rank": 1},
                    {"bucket": "main::Games", "weight": 0.8, "share": 0.8, "seed_hit_count": 1, "rank": 2},
                ],
            },
            {"user_id": "u2", "top_profile_buckets": [{"bucket": "main::Games", "weight": 1.0, "share": 1.0, "seed_hit_count": 1, "rank": 1}]},
        ],
    )
    write_jsonl(
        train_sequences_path,
        [
            {"user_id": "u1", "recent_item_sequence": ["seen_item", "also_seen"], "recent_positive_item_sequence": ["seen_item"]},
            {"user_id": "u2", "recent_item_sequence": ["game_1"], "recent_positive_item_sequence": []},
        ],
    )
    write_jsonl(
        top_items_path,
        [
            {
                "bucket": "main::Books",
                "top_items": [
                    {"parent_asin": "seen_item", "score": 100, "recent_pop_score": 9},
                    {"parent_asin": "book_1", "score": 90, "recent_pop_score": 8},
                    {"parent_asin": "book_2", "score": 80, "recent_pop_score": 7},
                ],
            },
            {
                "bucket": "main::Games",
                "top_items": [
                    {"parent_asin": "game_1", "score": 70, "recent_pop_score": 6},
                    {"parent_asin": "game_2", "score": 60, "recent_pop_score": 5},
                ],
            },
        ],
    )
    write_json(coverage_path, {"fallback_usage": {"fallback_buckets": ["main::Books"]}})
    write_json(resource_path, {"config": {"per_user": 3, "category_bucket_cap_per_user": 1, "fallback_bucket_count": 1}})
    write_json(
        method_manifest_path,
        {
            "source": "category",
            "canonical_source": "category",
            "candidate_materialization": "none",
            "input_lineage": {"train_user_sequences_path": str(train_sequences_path)},
        },
    )
    write_json(
        source_manifest_path,
        {
            "source": "category",
            "canonical_source": "category",
            "scale_tier": "all_eligible",
            "candidate_materialization": "none",
            "candidates_path": None,
            "method_dataset_manifest_path": str(method_manifest_path),
            "eligible_users_path": str(eligible_users_path),
            "user_category_profile_path": str(profile_path),
            "category_top_items_index_path": str(top_items_path),
            "outputs": {
                "method_dataset_manifest": str(method_manifest_path),
                "eligible_users": str(eligible_users_path),
                "user_category_profile": str(profile_path),
                "category_top_items_index": str(top_items_path),
                "coverage_audit": str(coverage_path),
                "resource_audit": str(resource_path),
            },
        },
    )

    rows = expand_category_candidates_for_users(source_index_manifest_path=source_manifest_path, user_ids=["u1", "missing", "u1"])

    assert [row["user_id"] for row in rows] == ["u1", "u1"]
    assert {row["item_id"] for row in rows} == {"book_1", "game_1"}
    assert "seen_item" not in {row["item_id"] for row in rows}
    assert all(row["source"] == "category" for row in rows)
    assert all(row["canonical_source"] == "category" for row in rows)
    assert all(row["sources"] == ["category"] for row in rows)
    assert [row["rank"] for row in rows] == [1, 2]
