from __future__ import annotations

import json
from pathlib import Path

import pytest

from rs_lab.experiments.recall.build_pool500_user_quality_profile import build_pool500_user_quality_profile

pytestmark = pytest.mark.unit


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")


def _write_clean_manifest(tmp_path: Path) -> Path:
    clean_dir = tmp_path / "clean"
    clean_dir.mkdir()
    train_sequences = clean_dir / "user_sequences.train.jsonl"
    heavy_items = [f"heavy_{index}" for index in range(12)]
    shared_items = heavy_items[:3]
    _write_jsonl(
        train_sequences,
        [
            {
                "user_id": "heavy",
                "recent_item_sequence": heavy_items * 2,
                "recent_positive_item_sequence": heavy_items + heavy_items[:8],
            },
            {
                "user_id": "neighbor_a",
                "recent_item_sequence": ["heavy_0", "heavy_1", "neighbor_only_a"],
                "recent_positive_item_sequence": ["heavy_0", "heavy_1", "neighbor_only_a"],
            },
            {
                "user_id": "neighbor_b",
                "recent_item_sequence": ["heavy_1", "heavy_2", "neighbor_only_b"],
                "recent_positive_item_sequence": ["heavy_1", "heavy_2", "neighbor_only_b"],
            },
            {
                "user_id": "neighbor_c",
                "recent_item_sequence": ["heavy_2", "neighbor_only_c", "neighbor_only_d"],
                "recent_positive_item_sequence": ["heavy_2", "neighbor_only_c", "neighbor_only_d"],
            },
            {
                "user_id": "medium",
                "recent_item_sequence": ["medium_0", "medium_1", "medium_2", "medium_0", "medium_1"],
                "recent_positive_item_sequence": ["medium_0", "medium_1", "medium_2", "medium_0", "medium_1"],
            },
            {
                "user_id": "fallback",
                "recent_item_sequence": ["fallback_0", "fallback_0"],
                "recent_positive_item_sequence": ["fallback_0", "fallback_0"],
            },
        ],
    )
    items = clean_dir / "canonical_items.jsonl"
    item_rows = []
    for index, item_id in enumerate(heavy_items):
        item_rows.append({"parent_asin": item_id, "main_category": "Electronics" if index % 2 else "Office"})
    item_rows.extend(
        [
            {"parent_asin": item_id, "main_category": "Shared"}
            for item_id in [*shared_items, "neighbor_only_a", "neighbor_only_b", "neighbor_only_c", "neighbor_only_d"]
        ]
    )
    item_rows.extend(
        [
            {"parent_asin": "medium_0", "main_category": "Books"},
            {"parent_asin": "medium_1", "main_category": "Books"},
            {"parent_asin": "medium_2", "main_category": "Office"},
            {"parent_asin": "fallback_0", "main_category": "Home"},
        ]
    )
    _write_jsonl(items, item_rows)
    manifest = clean_dir / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "train_user_sequences_path": str(train_sequences),
                "canonical_items_path": str(items),
                "split_paths": {"train": str(clean_dir / "canonical_interactions.train.jsonl")},
            }
        ),
        encoding="utf-8",
    )
    return manifest


def test_user_quality_profile_writes_manifest_schema_and_summary(tmp_path: Path) -> None:
    clean_manifest = _write_clean_manifest(tmp_path)
    output_dir = tmp_path / "profile"

    manifest = build_pool500_user_quality_profile(
        clean_manifest_path=clean_manifest,
        output_dir=output_dir,
        limit_users=6,
        overwrite=True,
        enforce_venv=False,
    )

    persisted_manifest = json.loads((output_dir / "eligible_user_quality_manifest.json").read_text(encoding="utf-8"))
    summary = json.loads((output_dir / "quality_bucket_summary.json").read_text(encoding="utf-8"))
    resource_audit = json.loads((output_dir / "resource_audit.json").read_text(encoding="utf-8"))
    assert persisted_manifest == manifest
    assert manifest["schema_version"] == "pool500_user_quality_profile_v1"
    assert manifest["policy_role"] == "eligibility_policy_not_recall_source"
    assert manifest["train_only"] is True
    assert manifest["ranking_input_replacement_allowed"] is False
    assert manifest["pool1000_allowed"] is False
    assert manifest["final_pool500_ready_claimed"] is False
    assert set(manifest["required_profile_fields"]) <= set(manifest["profiles"][0])
    assert summary["bucket_counts"] == {"heavy_cf_eligible": 1, "medium_behavior": 1, "fallback_only": 4}
    assert summary["eligible_counts"] == {"usercf": 1, "itemcf": 2, "swing": 2, "fallback_only": 4}
    assert resource_audit["uses_valid"] is False
    assert resource_audit["uses_test"] is False
    assert resource_audit["uses_holdout"] is False


def test_user_quality_bucket_rules_and_eligibility(tmp_path: Path) -> None:
    clean_manifest = _write_clean_manifest(tmp_path)

    manifest = build_pool500_user_quality_profile(
        clean_manifest_path=clean_manifest,
        output_dir=tmp_path / "profile",
        limit_users=6,
        overwrite=True,
        enforce_venv=False,
    )

    profiles = {profile["user_id"]: profile for profile in manifest["profiles"]}
    assert profiles["heavy"]["quality_bucket"] == "heavy_cf_eligible"
    assert profiles["heavy"]["eligible_for_usercf"] is True
    assert profiles["heavy"]["eligible_for_itemcf"] is True
    assert profiles["heavy"]["eligible_for_swing"] is True
    assert profiles["heavy"]["fallback_only"] is False
    assert profiles["medium"]["quality_bucket"] == "medium_behavior"
    assert profiles["medium"]["eligible_for_usercf"] is False
    assert profiles["medium"]["eligible_for_itemcf"] is True
    assert profiles["medium"]["eligible_for_swing"] is True
    assert profiles["fallback"]["quality_bucket"] == "fallback_only"
    assert profiles["fallback"]["fallback_only"] is True


def test_user_quality_rejects_holdout_valid_test_inputs(tmp_path: Path) -> None:
    clean_dir = tmp_path / "clean"
    clean_dir.mkdir()
    valid_sequences = clean_dir / "user_sequences.valid.jsonl"
    valid_sequences.write_text('{"user_id":"u1","recent_positive_item_sequence":["i1"]}\n', encoding="utf-8")
    items = clean_dir / "canonical_items.jsonl"
    items.write_text('{"parent_asin":"i1","main_category":"A"}\n', encoding="utf-8")
    manifest = clean_dir / "manifest.json"
    manifest.write_text(
        json.dumps({"train_user_sequences_path": str(valid_sequences), "canonical_items_path": str(items)}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Forbidden non-train input"):
        build_pool500_user_quality_profile(
            clean_manifest_path=manifest,
            output_dir=tmp_path / "profile",
            limit_users=1,
            overwrite=True,
            enforce_venv=False,
        )


def test_user_quality_requires_strict_manifest_keys(tmp_path: Path) -> None:
    clean_dir = tmp_path / "clean"
    clean_dir.mkdir()
    train_sequences = clean_dir / "user_sequences.train.jsonl"
    train_sequences.write_text('{"user_id":"u1","recent_positive_item_sequence":["i1"]}\n', encoding="utf-8")
    items = clean_dir / "canonical_items.jsonl"
    items.write_text('{"parent_asin":"i1","main_category":"A"}\n', encoding="utf-8")
    manifest = clean_dir / "manifest.json"
    manifest.write_text(
        json.dumps({"user_sequences_train_path": str(train_sequences), "item_metadata_path": str(items)}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="train_user_sequences_path"):
        build_pool500_user_quality_profile(
            clean_manifest_path=manifest,
            output_dir=tmp_path / "profile",
            limit_users=1,
            overwrite=True,
            enforce_venv=False,
        )


def test_user_quality_rejects_final_ready_full_run_shape(tmp_path: Path) -> None:
    clean_manifest = _write_clean_manifest(tmp_path)

    with pytest.raises(ValueError, match="batch-scoped"):
        build_pool500_user_quality_profile(
            clean_manifest_path=clean_manifest,
            output_dir=tmp_path / "profile",
            limit_users=0,
            overwrite=True,
            enforce_venv=False,
        )


def test_user_quality_registry_contract_stays_policy_not_source() -> None:
    registry = json.loads(Path("configs/recall/pool500_method_registry.json").read_text(encoding="utf-8"))

    assert "user_quality" not in registry["sources"]
    contract = registry["user_quality"]["dataset_contract"]
    assert contract["policy_type"] == "batch_scoped_train_only_policy"
    assert contract["promotion_policy"] == {
        "auto_promotion_allowed": False,
        "ranking_input_replacement_allowed": False,
        "pool1000_allowed": False,
        "final_pool500_ready_claimed": False,
    }
    assert {"holdout", "valid", "test"} <= set(contract["forbidden_input_scopes"])
