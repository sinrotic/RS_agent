from __future__ import annotations

import json
from pathlib import Path

import pytest

from rs_lab.experiments.recall.build_pool500_two_tower_method_dataset import build_pool500_two_tower_method_dataset
from rs_lab.experiments.recall.build_train_only_data_governance import (
    build_train_only_data_governance,
    load_governance_manifest,
    method_dataset_policies,
)

pytestmark = pytest.mark.unit


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")


def _read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _make_clean_manifest(tmp_path: Path) -> Path:
    clean_dir = tmp_path / "clean_full"
    interactions = []
    interactions.extend(_interaction_rows("u_heavy", ["h1", "h2", "h3", "h4", "h5", "h6", "h7", "h8", "h9", "h10"], 1))
    interactions.extend(_interaction_rows("u_heavy_neighbor", ["h1"], 20))
    interactions.extend(_interaction_rows("u_two", ["hot", "t2", "t3"], 30))
    interactions.extend(_interaction_rows("u_hot_neighbor_a", ["hot"], 40))
    interactions.extend(_interaction_rows("u_hot_neighbor_b", ["hot"], 45))
    interactions.extend(_interaction_rows("u_medium", ["m1", "m2", "m1", "m2"], 50))
    interactions.extend(_interaction_rows("u_fallback", ["f1", "f2"], 60))
    interactions.extend(_interaction_rows("u_cold", ["c1"], 70))
    _write_jsonl(clean_dir / "canonical_interactions.train.jsonl", interactions)
    _write_jsonl(
        clean_dir / "canonical_items.jsonl",
        [
            {"parent_asin": item_id, "title": f"Title {item_id}", "category": "Office", "main_category": "Office"}
            for item_id in sorted({row["parent_asin"] for row in interactions} | {"no_pos"})
        ],
    )
    _write_jsonl(
        clean_dir / "user_sequences.train.jsonl",
        [
            _sequence_row("u_heavy", ["h1", "h2", "h3", "h4", "h5", "h6", "h7", "h8", "h9", "h10"]),
            _sequence_row("u_two", ["hot", "t2", "t3"]),
            _sequence_row("u_medium", ["m1", "m2", "m1", "m2"]),
            _sequence_row("u_fallback", ["f1", "f2"]),
            _sequence_row("u_cold", ["c1"]),
        ],
    )
    _write_jsonl(clean_dir / "canonical_interactions.valid.jsonl", [{"must_not_be_read": True}])
    _write_jsonl(clean_dir / "canonical_interactions.test.jsonl", [{"must_not_be_read": True}])
    _write_jsonl(clean_dir / "holdout.jsonl", [{"must_not_be_read": True}])
    manifest = clean_dir / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "train_user_sequences_path": "user_sequences.train.jsonl",
                "canonical_items_path": "canonical_items.jsonl",
                "split_paths": {
                    "train": "canonical_interactions.train.jsonl",
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return manifest


def _interaction_rows(user_id: str, items: list[str], start_ts: int) -> list[dict[str, object]]:
    return [
        {
            "user_id": user_id,
            "parent_asin": item_id,
            "category": "Electronics" if item_id in {"hot", "t2"} else "Office",
            "timestamp": start_ts + index,
            "label_binary": 1,
            "split": "train",
        }
        for index, item_id in enumerate(items)
    ]


def _sequence_row(user_id: str, items: list[str]) -> dict[str, object]:
    return {
        "user_id": user_id,
        "sequence_len": len(items),
        "positive_sequence_len": len(items),
        "recent_item_sequence": items,
        "recent_positive_item_sequence": items,
        "recent_positive_timestamp_sequence": list(range(100, 100 + len(items))),
    }


def test_governance_builds_required_artifacts_and_manifest_schema(tmp_path: Path) -> None:
    clean_manifest = _make_clean_manifest(tmp_path)
    output_dir = tmp_path / "governance"

    manifest = build_train_only_data_governance(
        clean_manifest_path=clean_manifest,
        output_dir=output_dir,
        overwrite=True,
        enforce_venv=False,
    )

    expected_files = {
        "user_quality_profile.jsonl",
        "eligible_user_quality_manifest.json",
        "quality_bucket_summary.json",
        "item_frequency_train.jsonl",
        "item_universe_summary.json",
        "item_quality_profile.jsonl",
        "item_quality_summary.json",
        "cold_start_user_profile.jsonl",
        "long_tail_item_profile.jsonl",
        "leakage_audit.json",
        "manifest.json",
    }
    assert {path.name for path in output_dir.iterdir()} == expected_files
    persisted = load_governance_manifest(output_dir / "manifest.json")
    assert persisted == manifest
    assert manifest["schema_version"] == "train_only_data_governance_v1"
    assert manifest["train_only"] is True
    assert manifest["valid_used"] is False
    assert manifest["test_used"] is False
    assert manifest["holdout_used"] is False
    assert manifest["lopo_used"] is False
    assert manifest["clean_full_modified"] is False
    assert len(manifest["lineage"]["input_hashes"]["canonical_interactions_train_sha256"]) == 64
    assert manifest["lineage"]["allowed_inputs"] == ["manifest.json", "canonical_interactions.train.jsonl", "user_sequences.train.jsonl", "canonical_items.jsonl"]
    assert Path(manifest["artifacts"]["item_quality_profile"]).name == "item_quality_profile.jsonl"
    policies = method_dataset_policies(manifest)
    expected_policy_sources = {
        "itemcf_strong",
        "itemcf_weak",
        "two_tower",
        "usercf_recall",
        "swing_recall",
        "popular",
        "category",
        "semantic",
        "co_visit_fallback_repair",
    }
    assert set(policies) == expected_policy_sources
    for policy in policies.values():
        assert policy["method_dataset_policy"] == "train_only_method_dataset"
        assert policy["train_only_inputs"]
        assert policy["eligible_user_policy"]
        assert policy["eligible_item_policy"]
        assert policy["required_fields"]
        assert {"valid", "test", "holdout", "lopo", "oracle", "eval_label"} <= set(policy["forbidden_scopes"])
        assert policy["output_role"]
        assert "train_only_inputs" in policy["acceptance_checks"] or "train_only_session_or_co_visit_inputs" in policy["acceptance_checks"]
    assert policies["itemcf_strong"]["eligible_user_buckets"] == ["collaborative_rich"]
    assert policies["itemcf_strong"]["min_overlap"] == 2
    assert policies["itemcf_strong"]["item_weighting_policy"] == "item_idf_downweight_super_hot_items"
    assert policies["itemcf_weak"]["eligible_user_buckets"] == ["collaborative_rich", "medium_behavior"]
    assert "item_quality_profile.jsonl" in policies["two_tower"]["train_only_inputs"]
    assert "item_quality_profile.jsonl" in policies["two_tower"]["allowed_inputs"]
    assert policies["two_tower"]["item_universe_policy"] == "hot_item_universe_from_train_frequency"
    assert policies["usercf_recall"]["eligible_user_buckets"] == ["collaborative_rich"]
    assert policies["usercf_recall"]["min_overlap"] == 2
    assert policies["swing_recall"]["eligible_user_buckets"] == ["collaborative_rich", "medium_behavior"]
    assert policies["swing_recall"]["common_user_count_min"] == 2
    assert policies["swing_recall"]["score_policy"] == "nonnegative"
    assert policies["popular"]["eligible_item_policy"] == "train_item_frequency_only"
    assert policies["category"]["category_min_item_count"] == 5
    assert policies["category"]["fallback_policy"] == "popular_fallback_when_category_too_sparse"
    assert policies["semantic"]["eligible_item_policy"] == "catalog_title_category_metadata_only"
    assert policies["semantic"]["similarity_threshold_policy"]["record_in_manifest"] is True
    assert policies["co_visit_fallback_repair"]["co_visit_count_min"] == 2


def test_governance_user_quality_buckets_and_cold_start_profile(tmp_path: Path) -> None:
    clean_manifest = _make_clean_manifest(tmp_path)
    output_dir = tmp_path / "governance"

    manifest = build_train_only_data_governance(
        clean_manifest_path=clean_manifest,
        output_dir=output_dir,
        overwrite=True,
        enforce_venv=False,
    )

    profiles = {row["user_id"]: row for row in _read_jsonl(output_dir / "user_quality_profile.jsonl")}
    assert profiles["u_heavy"]["quality_bucket"] == "heavy_cf_eligible"
    assert profiles["u_heavy"]["quality_bucket_v2"] == "collaborative_rich"
    assert profiles["u_heavy"]["eligible_for_itemcf_strong"] is True
    assert profiles["u_two"]["quality_bucket"] == "two_tower_train_eligible"
    assert profiles["u_two"]["quality_bucket_v2"] == "sequence_sufficient"
    assert profiles["u_two"]["eligible_for_two_tower"] is True
    assert profiles["u_medium"]["quality_bucket"] == "medium_behavior"
    assert profiles["u_medium"]["quality_bucket_v2"] == "medium_behavior"
    assert profiles["u_medium"]["eligible_for_itemcf_weak"] is True
    assert profiles["u_fallback"]["quality_bucket"] == "fallback_only"
    assert profiles["u_fallback"]["quality_bucket_v2"] == "fallback_only"
    assert profiles["u_cold"]["quality_bucket"] == "cold_start"
    assert profiles["u_cold"]["quality_bucket_v2"] == "cold_start"
    cold_rows = _read_jsonl(output_dir / "cold_start_user_profile.jsonl")
    assert [row["user_id"] for row in cold_rows] == ["u_cold"]
    assert manifest["quality_bucket_summary"]["bucket_counts"] == {
        "cold_start": 1,
        "fallback_only": 1,
        "medium_behavior": 1,
        "sequence_sufficient": 1,
        "collaborative_rich": 1,
    }


def test_governance_item_frequency_and_universe_summary(tmp_path: Path) -> None:
    clean_manifest = _make_clean_manifest(tmp_path)
    output_dir = tmp_path / "governance"

    manifest = build_train_only_data_governance(
        clean_manifest_path=clean_manifest,
        output_dir=output_dir,
        overwrite=True,
        enforce_venv=False,
    )

    frequency = {row["parent_asin"]: row for row in _read_jsonl(output_dir / "item_frequency_train.jsonl")}
    assert frequency["h1"]["frequency"] == 2
    assert frequency["h1"]["user_count"] == 2
    assert frequency["hot"]["frequency"] == 3
    assert frequency["no_pos"]["frequency"] == 0
    assert frequency["t2"]["is_long_tail"] is True
    long_tail = {row["parent_asin"] for row in _read_jsonl(output_dir / "long_tail_item_profile.jsonl")}
    assert {"t2", "f1", "f2", "c1"} <= long_tail
    item_quality = {row["parent_asin"]: row for row in _read_jsonl(output_dir / "item_quality_profile.jsonl")}
    required_fields = {
        "parent_asin",
        "positive_event_count",
        "unique_positive_user_count",
        "train_interaction_count",
        "train_positive_count",
        "train_strong_positive_count",
        "global_pop_rank",
        "category",
        "main_category",
        "category_pop_rank",
        "title_ready",
        "category_ready",
        "text_ready",
        "semantic_ready",
        "cf_ready",
        "two_tower_ready",
        "fallback_ready",
        "hotness_bucket",
        "quality_bucket",
        "quality_bucket_v2",
        "bucket_reason",
        "dropped_reasons",
        "train_only",
        "source_layer",
    }
    assert required_fields <= set(item_quality["h1"])
    assert item_quality["h1"]["positive_event_count"] == 2
    assert item_quality["h1"]["unique_positive_user_count"] == 2
    assert item_quality["hot"]["quality_bucket_v2"] == "embedding_ready"
    assert item_quality["no_pos"]["quality_bucket_v2"] == "no_positive"
    assert manifest["item_quality_summary"]["item_quality_bucket_v2_enum"] == [
        "no_positive",
        "single_seed",
        "low_frequency",
        "mid_frequency",
        "cf_ready",
        "embedding_ready",
    ]
    summary = manifest["item_universe_summary"]
    assert summary["universes_by_min_freq"]["min_freq_gte_2"]["retained_item_count"] == 4
    assert summary["universes_by_min_freq"]["min_freq_gte_3"]["retained_item_count"] == 1
    assert summary["universes_by_top_k"]["top_50000"]["retained_item_count"] == summary["total_item_count"]


def test_governance_leakage_audit_is_train_only_and_forbids_non_train_inputs(tmp_path: Path) -> None:
    clean_manifest = _make_clean_manifest(tmp_path)
    output_dir = tmp_path / "governance"

    build_train_only_data_governance(
        clean_manifest_path=clean_manifest,
        output_dir=output_dir,
        overwrite=True,
        enforce_venv=False,
    )

    audit = _read_json(output_dir / "leakage_audit.json")
    assert audit["status"] == "PASS"
    assert audit["train_only"] is True
    assert audit["valid_used"] is False
    assert audit["test_used"] is False
    assert audit["holdout_used"] is False
    assert audit["lopo_used"] is False
    assert [Path(path).name for path in audit["read_files"]] == [
        "manifest.json",
        "canonical_interactions.train.jsonl",
        "user_sequences.train.jsonl",
        "canonical_items.jsonl",
    ]
    assert any("canonical_interactions.valid.jsonl" in path for path in audit["forbidden_inputs"])
    assert audit["forbidden_path_scan"]["hits"] == []


def test_governance_rejects_valid_test_holdout_as_train_inputs(tmp_path: Path) -> None:
    clean_manifest = _make_clean_manifest(tmp_path)
    manifest_payload = _read_json(clean_manifest)
    manifest_payload["split_paths"]["train"] = str(clean_manifest.parent / "canonical_interactions.valid.jsonl")
    clean_manifest.write_text(json.dumps(manifest_payload, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(ValueError, match="Forbidden governance scope|canonical_interactions.train.jsonl"):
        build_train_only_data_governance(
            clean_manifest_path=clean_manifest,
            output_dir=tmp_path / "governance",
            overwrite=True,
            enforce_venv=False,
        )


def test_governance_rejects_clean_10000_source_scope(tmp_path: Path) -> None:
    clean_manifest = _make_clean_manifest(tmp_path)
    clean_10000 = tmp_path / "amazon_2023_recall_clean_10000"
    clean_10000.mkdir()
    redirected_manifest = clean_10000 / "manifest.json"
    redirected_manifest.write_text(clean_manifest.read_text(encoding="utf-8"), encoding="utf-8")

    with pytest.raises(ValueError, match="Forbidden non-train path"):
        build_train_only_data_governance(
            clean_manifest_path=redirected_manifest,
            output_dir=tmp_path / "governance",
            overwrite=True,
            enforce_venv=False,
        )


def test_governance_deduplicates_item_unique_positive_users(tmp_path: Path) -> None:
    clean_manifest = _make_clean_manifest(tmp_path)
    clean_dir = clean_manifest.parent
    rows = _read_jsonl(clean_dir / "canonical_interactions.train.jsonl")
    rows.extend(_interaction_rows("u_dup", ["dup", "dup", "dup"], 200))
    _write_jsonl(clean_dir / "canonical_interactions.train.jsonl", rows)
    _write_jsonl(clean_dir / "canonical_items.jsonl", [{"parent_asin": "dup", "title": "Dup", "category": "Office", "main_category": "Office"}])

    build_train_only_data_governance(
        clean_manifest_path=clean_manifest,
        output_dir=tmp_path / "governance",
        overwrite=True,
        enforce_venv=False,
    )

    item_quality = {row["parent_asin"]: row for row in _read_jsonl(tmp_path / "governance" / "item_quality_profile.jsonl")}
    assert item_quality["dup"]["positive_event_count"] == 3
    assert item_quality["dup"]["unique_positive_user_count"] == 1


@pytest.mark.parametrize(
    "payload",
    [
        {"metadata": {"validation_source": "canonical_interactions.train.jsonl"}},
        {"split_paths": {"train": "canonical_interactions.train.jsonl"}, "features": [{"source": "oracle_score"}]},
        {"split_paths": {"train": "canonical_interactions.train.jsonl"}, "nested": {"path": "data/pool1000/foo.jsonl"}},
    ],
)
def test_governance_forbidden_scope_scanner_is_recursive(tmp_path: Path, payload: dict[str, object]) -> None:
    clean_manifest = _make_clean_manifest(tmp_path)
    manifest_payload = _read_json(clean_manifest)
    manifest_payload.update(payload)
    clean_manifest.write_text(json.dumps(manifest_payload, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(ValueError, match="Forbidden governance scope"):
        build_train_only_data_governance(
            clean_manifest_path=clean_manifest,
            output_dir=tmp_path / "governance",
            overwrite=True,
            enforce_venv=False,
        )


def test_governance_smoke_manifest_satisfies_two_tower_policy_validation(tmp_path: Path) -> None:
    clean_manifest = _make_clean_manifest(tmp_path)
    governance_manifest = build_train_only_data_governance(
        clean_manifest_path=clean_manifest,
        output_dir=tmp_path / "governance",
        scale_tier="smoke",
        overwrite=True,
        enforce_venv=False,
    )

    two_tower_manifest = build_pool500_two_tower_method_dataset(
        clean_manifest_path=clean_manifest,
        governance_manifest_path=Path(governance_manifest["artifacts"]["manifest"]),
        output_dir=tmp_path / "two_tower",
        scale_tier="smoke",
        overwrite=True,
        enforce_venv=False,
    )

    assert two_tower_manifest["status"] == "PASS"
    assert Path(two_tower_manifest["input_artifacts"]["item_quality_profile"]).name == "item_quality_profile.jsonl"
    assert "item_quality_profile.jsonl" in governance_manifest["derived_dataset_policies"]["two_tower"]["train_only_inputs"]


def test_governance_allows_non_train_split_metadata_without_reading_it(tmp_path: Path) -> None:
    clean_manifest = _make_clean_manifest(tmp_path)
    manifest_payload = _read_json(clean_manifest)
    manifest_payload["split_paths"]["valid"] = "canonical_interactions.valid.jsonl"
    manifest_payload["split_paths"]["test"] = "canonical_interactions.test.jsonl"
    clean_manifest.write_text(json.dumps(manifest_payload, ensure_ascii=False), encoding="utf-8")

    manifest = build_train_only_data_governance(
        clean_manifest_path=clean_manifest,
        output_dir=tmp_path / "governance",
        scale_tier="smoke",
        overwrite=True,
        enforce_venv=False,
    )

    read_file_names = [Path(path).name for path in _read_json(tmp_path / "governance" / "leakage_audit.json")["read_files"]]
    assert "canonical_interactions.valid.jsonl" not in read_file_names
    assert "canonical_interactions.test.jsonl" not in read_file_names
    assert manifest["limits"] == {"limit_users": 500, "limit_interactions": 20_000}
    assert manifest["resource_scale_policy"]["scale_tier"] == "smoke"


def test_governance_streaming_smoke_limits_are_recorded(tmp_path: Path) -> None:
    clean_manifest = _make_clean_manifest(tmp_path)
    output_dir = tmp_path / "governance"

    manifest = build_train_only_data_governance(
        clean_manifest_path=clean_manifest,
        output_dir=output_dir,
        limit_interactions=4,
        limit_users=2,
        overwrite=True,
        enforce_venv=False,
    )

    assert manifest["limits"] == {"limit_users": 2, "limit_interactions": 4}
    assert manifest["quality_bucket_summary"]["profiled_user_count"] == 2
    assert len(_read_jsonl(output_dir / "user_quality_profile.jsonl")) == 2
