from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

import rs_lab.experiments.recall.build_pool500_method_dataset as method_dataset_builder
from rs_lab.experiments.recall.build_pool500_method_dataset import (
    SOURCE_METHODS,
    build_pool500_method_dataset,
    build_pool500_method_datasets,
)
from rs_lab.experiments.recall.build_train_only_data_governance import DERIVED_DATASET_POLICIES, SCHEMA_VERSION as GOVERNANCE_SCHEMA_VERSION

pytestmark = pytest.mark.unit

HARD_SCHEMA_KEYS = {
    "schema_version",
    "layer",
    "source_method",
    "status",
    "train_only",
    "upstream_governance_manifest_path",
    "upstream_governance_manifest_hash",
    "read_files",
    "input_hashes",
    "forbidden_scopes",
    "forbidden_scope_audit",
    "selection_policy",
    "resource_scale_policy",
    "effective_user_bucket_policy",
    "effective_item_bucket_policy",
    "row_count",
    "user_count",
    "item_count",
    "dropped_reason_counts",
    "outputs",
    "config_hash",
    "candidate_generation_allowed",
    "ranking_input_replacement_allowed",
    "promotion_allowed",
    "final_pool500_ready_claimed",
}
FORBIDDEN_OUTPUT_NAMES = {
    "source_index_manifest.json",
    "candidates.jsonl",
    "enhanced_only_candidates.jsonl",
    "readiness_manifest.json",
    "promotion_manifest.json",
}


def test_collab_method_datasets_write_whitelisted_outputs_and_hard_schema(tmp_path: Path) -> None:
    governance_manifest = _write_governance_fixture(tmp_path)

    manifests = build_pool500_method_datasets(
        governance_manifest_path=governance_manifest,
        output_root=tmp_path / "method_datasets",
        overwrite=True,
        enforce_venv=False,
    )

    assert set(manifests) == set(SOURCE_METHODS)
    for source_method, manifest in manifests.items():
        output_dir = tmp_path / "method_datasets" / source_method
        assert HARD_SCHEMA_KEYS <= set(manifest)
        assert manifest["layer"] == "method_dataset"
        assert manifest["source_method"] == source_method
        assert manifest["status"] == "PASS"
        assert manifest["train_only"] is True
        assert manifest["candidate_generation_allowed"] is False
        assert manifest["ranking_input_replacement_allowed"] is False
        assert manifest["promotion_allowed"] is False
        assert manifest["final_pool500_ready_claimed"] is False
        assert manifest["resource_scale_policy"]["input_scope"] == "governance_train_only"
        assert manifest["resource_scale_policy"]["scale_tier"] == "local_formal"
        assert manifest["resource_scale_policy"]["selection_strategy"]
        assert manifest["resource_scale_policy"]["default_tier"] == "local_formal"
        assert set(manifest["resource_scale_policy"]["scale_tiers"]) == {"smoke", "diagnostic", "local_formal"}
        assert manifest["resource_scale_policy"]["p2_contract_scope"] == "method_dataset_only"
        assert manifest["forbidden_scope_audit"]["status"] == "PASS"
        assert {path.name for path in output_dir.iterdir()} == {"method_dataset_manifest.json", "method_dataset_rows.jsonl"}
        assert not (FORBIDDEN_OUTPUT_NAMES & {path.name for path in output_dir.iterdir()})
        assert _read_json(output_dir / "method_dataset_manifest.json")["source_method"] == source_method
        rows = _read_jsonl(output_dir / "method_dataset_rows.jsonl")
        assert rows
        assert {row["source_method"] for row in rows} == {source_method}
        assert all(row["train_only"] is True for row in rows)


def test_selection_uses_user_bucket_v2_and_item_cf_ready_non_over_hot(tmp_path: Path) -> None:
    governance_manifest = _write_governance_fixture(tmp_path)

    weak = build_pool500_method_dataset(
        governance_manifest_path=governance_manifest,
        output_dir=tmp_path / "weak",
        source_method="itemcf_weak",
        overwrite=True,
        enforce_venv=False,
    )
    strong = build_pool500_method_dataset(
        governance_manifest_path=governance_manifest,
        output_dir=tmp_path / "strong",
        source_method="itemcf_strong",
        overwrite=True,
        enforce_venv=False,
    )

    weak_rows = _read_jsonl(Path(weak["outputs"]["dataset_rows_path"]))
    strong_rows = _read_jsonl(Path(strong["outputs"]["dataset_rows_path"]))
    assert weak["outputs"]["dataset_schema"] == "itemcf_edge_features_v1"
    assert weak["outputs"]["feature_schema"] == "itemcf_edge_features_v1"
    assert strong["outputs"]["dataset_schema"] == "itemcf_edge_features_v1"
    assert strong["outputs"]["feature_schema"] == "itemcf_edge_features_v1"
    assert weak["schema_name"] == "itemcf_edge_features_v1"
    assert strong["schema_name"] == "itemcf_edge_features_v1"
    assert weak["unique_pair_count"] == 3
    assert weak["edge_count"] == 6
    assert weak["directed_edge_count_after_topk"] == 6
    assert strong["unique_pair_count"] == 1
    assert strong["edge_count"] == 2
    assert strong["directed_edge_count_after_topk"] == 2
    assert {(row["item_i"], row["item_j"], row["pair_support"]) for row in weak_rows} == {
        ("cf_a", "cf_b", 2),
        ("cf_a", "cf_mid", 2),
        ("cf_b", "cf_mid", 1),
    }
    assert {(row["src_item_id"], row["dst_item_id"]) for row in weak_rows} == {
        ("cf_a", "cf_b"),
        ("cf_b", "cf_a"),
        ("cf_a", "cf_mid"),
        ("cf_mid", "cf_a"),
        ("cf_b", "cf_mid"),
        ("cf_mid", "cf_b"),
    }
    assert {(row["item_i"], row["item_j"], row["pair_support"]) for row in strong_rows} == {("cf_a", "cf_b", 2)}
    assert {(row["src_item_id"], row["dst_item_id"]) for row in strong_rows} == {("cf_a", "cf_b"), ("cf_b", "cf_a")}
    assert strong["dropped_reason_counts"]["pair_below_min_support"] == 2
    assert weak["user_count"] == 3
    assert strong["user_count"] == 2
    assert strong["dropped_reason_counts"]["user_bucket_not_allowed"] == 2
    assert all(row["supporting_user_count"] == row["pair_support"] for row in weak_rows + strong_rows)
    assert all(row["supporting_user_buckets"] == {"collaborative_rich": 2} for row in strong_rows)
    assert weak["dropped_reason_counts"]["item_over_hot"] == 1
    assert weak["dropped_reason_counts"]["item_not_cf_ready"] == 1


def test_itemcf_edge_features_score_rank_and_topk_are_method_dataset_features(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    governance_manifest = _write_governance_fixture(tmp_path)
    capped_policy = json.loads(json.dumps(method_dataset_builder.RESOURCE_SCALE_POLICIES["itemcf_weak"]))
    capped_policy["scale_tiers"]["local_formal"]["top_k_per_seed"] = 1
    monkeypatch.setitem(method_dataset_builder.RESOURCE_SCALE_POLICIES, "itemcf_weak", capped_policy)

    manifest = build_pool500_method_dataset(
        governance_manifest_path=governance_manifest,
        output_dir=tmp_path / "weak_topk",
        source_method="itemcf_weak",
        overwrite=True,
        enforce_venv=False,
    )

    rows = _read_jsonl(Path(manifest["outputs"]["dataset_rows_path"]))
    cf_a_edge = next(row for row in rows if row["src_item_id"] == "cf_a")
    expected_weighted_cooc = round(1 / math.log1p(3), 6) + round(1 / math.log1p(2), 6)
    assert cf_a_edge["dst_item_id"] == "cf_mid"
    assert cf_a_edge["edge_rank"] == 1
    assert cf_a_edge["supporting_user_count"] == 2
    assert cf_a_edge["weighted_cooc"] == round(expected_weighted_cooc, 6)
    assert cf_a_edge["itemcf_score"] == round(
        cf_a_edge["weighted_cooc"] / ((cf_a_edge["src_user_count"] * cf_a_edge["dst_user_count"]) ** 0.5), 6
    )
    assert cf_a_edge["itemcf_score"] != round(cf_a_edge["cooc_cnt"] / ((cf_a_edge["src_user_count"] * cf_a_edge["dst_user_count"]) ** 0.5), 6)
    assert cf_a_edge["score_policy"] == method_dataset_builder.ITEMCF_SCORE_POLICY
    assert cf_a_edge["itemcf_score_formula"] == method_dataset_builder.ITEMCF_SCORE_FORMULA
    assert cf_a_edge["active_user_penalty_policy"] == method_dataset_builder.ITEMCF_ACTIVE_USER_PENALTY_POLICY
    assert manifest["unique_pair_count"] == 3
    assert manifest["edge_count"] == 6
    assert manifest["directed_edge_count_after_topk"] == 3
    assert manifest["top_k_per_seed"] == 1
    assert manifest["dropped_reason_counts"]["edge_over_top_k_per_seed"] == 3
    assert manifest["score_policy"] == method_dataset_builder.ITEMCF_SCORE_POLICY
    assert manifest["itemcf_score_formula"] == method_dataset_builder.ITEMCF_SCORE_FORMULA
    assert manifest["active_user_penalty_policy"] == method_dataset_builder.ITEMCF_ACTIVE_USER_PENALTY_POLICY
    assert manifest["feature_summary"]["layer"] == "method_dataset"
    assert manifest["feature_summary"]["score_policy"] == method_dataset_builder.ITEMCF_SCORE_POLICY
    assert manifest["feature_summary"]["score_formula"] == method_dataset_builder.ITEMCF_SCORE_FORMULA
    assert manifest["feature_summary"]["active_user_penalty_policy"] == method_dataset_builder.ITEMCF_ACTIVE_USER_PENALTY_POLICY
    assert manifest["feature_summary"]["rank_policy"] == "source_method + src_item_id by itemcf_score desc, cooc_cnt desc, dst_item_id asc"
    assert manifest["weighted_cooc_sum_after_topk"] == round(sum(row["weighted_cooc"] for row in rows), 6)
    assert all(row["dataset_role"] == "method_dataset_itemcf_edge_feature" for row in rows)
    assert all(row["top_k_per_seed"] == 1 for row in rows)
    assert all("dropped_reason" not in row for row in rows)


def test_swing_method_dataset_writes_graph_pair_support_rows(tmp_path: Path) -> None:
    governance_manifest = _write_governance_fixture(tmp_path)

    manifest = build_pool500_method_dataset(
        governance_manifest_path=governance_manifest,
        output_dir=tmp_path / "swing",
        source_method="swing_method_dataset",
        overwrite=True,
        enforce_venv=False,
    )

    rows = _read_jsonl(Path(manifest["outputs"]["dataset_rows_path"]))
    assert manifest["outputs"]["dataset_schema"] == "swing_item_pair_support_v1"
    assert {(row["item_i"], row["item_j"], row["graph_user_support"]) for row in rows} == {
        ("cf_a", "cf_b", 2),
        ("cf_a", "cf_mid", 2),
    }
    assert all(row["dataset_role"] == "method_dataset_swing_pair_support" for row in rows)
    assert manifest["user_count"] == 3
    assert manifest["item_count"] == 3
    assert manifest["dropped_reason_counts"]["pair_below_min_support"] == 1
    assert manifest["dropped_reason_counts"]["user_bucket_not_allowed"] == 1


def test_usercf_method_dataset_applies_user_and_item_caps(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    governance_manifest = _write_governance_fixture(tmp_path)
    capped_policy = json.loads(json.dumps(method_dataset_builder.RESOURCE_SCALE_POLICIES["usercf_method_dataset"]))
    capped_policy["scale_tiers"]["local_formal"]["max_output_users"] = 1
    capped_policy["scale_tiers"]["local_formal"]["max_items_per_user"] = 2
    monkeypatch.setitem(method_dataset_builder.RESOURCE_SCALE_POLICIES, "usercf_method_dataset", capped_policy)

    manifest = build_pool500_method_dataset(
        governance_manifest_path=governance_manifest,
        output_dir=tmp_path / "usercf_capped",
        source_method="usercf_method_dataset",
        overwrite=True,
        enforce_venv=False,
    )

    rows = _read_jsonl(Path(manifest["outputs"]["dataset_rows_path"]))
    assert manifest["user_count"] == 1
    assert len(rows) == 1
    assert all(len(row["eligible_item_sequence"]) <= 2 for row in rows)
    assert manifest["dropped_reason_counts"]["max_output_users_exceeded"] == 1
    assert manifest["dropped_reason_counts"]["items_over_user_cap"] == 1


def test_collab_method_dataset_smoke_tier_uses_smoke_caps_not_local_formal(tmp_path: Path) -> None:
    governance_manifest = _write_governance_fixture(tmp_path)

    manifest = build_pool500_method_dataset(
        governance_manifest_path=governance_manifest,
        output_dir=tmp_path / "smoke_usercf",
        source_method="usercf_method_dataset",
        scale_tier="smoke",
        overwrite=True,
        enforce_venv=False,
    )

    policy = manifest["resource_scale_policy"]
    assert policy["scale_tier"] == "smoke"
    assert policy["max_output_users"] == 1_000
    assert policy["max_items_per_user"] == 80
    assert policy["similar_users_top_k"] == 50
    assert policy["max_output_users"] != policy["scale_tiers"]["local_formal"]["max_output_users"]


def test_collab_method_dataset_resource_scale_policies_are_method_specific(tmp_path: Path) -> None:
    governance_manifest = _write_governance_fixture(tmp_path)

    manifests = build_pool500_method_datasets(
        governance_manifest_path=governance_manifest,
        output_root=tmp_path / "method_datasets",
        overwrite=True,
        enforce_venv=False,
    )

    weak_policy = manifests["itemcf_weak"]["resource_scale_policy"]
    strong_policy = manifests["itemcf_strong"]["resource_scale_policy"]
    usercf_policy = manifests["usercf_method_dataset"]["resource_scale_policy"]
    swing_policy = manifests["swing_method_dataset"]["resource_scale_policy"]
    assert weak_policy["selection_strategy"]["policy_name"] == "itemcf_weak_edges_v1"
    assert weak_policy["selection_strategy"]["eligible_user_buckets"] == ["medium_behavior", "collaborative_rich"]
    assert weak_policy["max_output_users"] == 300_000
    assert weak_policy["max_item_user_freq"] == 5_000
    assert weak_policy["min_pair_support"] == 1
    assert weak_policy["top_k_per_seed"] == 100
    assert weak_policy["score_policy"] == method_dataset_builder.ITEMCF_SCORE_POLICY
    assert weak_policy["active_user_penalty_policy"] == method_dataset_builder.ITEMCF_ACTIVE_USER_PENALTY_POLICY
    assert weak_policy["weighted_cooc_feature"] == "weighted_cooc"
    assert weak_policy["scale_tiers"]["smoke"] == {
        "max_output_users": 1_000,
        "max_items_per_user": 50,
        "max_item_user_freq": 5_000,
        "min_pair_support": 1,
        "top_k_per_seed": 100,
    }
    assert strong_policy["selection_strategy"]["policy_name"] == "itemcf_strong_edges_v1"
    assert strong_policy["selection_strategy"]["eligible_user_buckets"] == ["collaborative_rich"]
    assert strong_policy["max_output_users"] == 200_000
    assert strong_policy["max_item_user_freq"] == 3_000
    assert strong_policy["min_pair_support"] == 2
    assert strong_policy["top_k_per_seed"] == 100
    assert strong_policy["score_policy"] == method_dataset_builder.ITEMCF_SCORE_POLICY
    assert strong_policy["active_user_penalty_policy"] == method_dataset_builder.ITEMCF_ACTIVE_USER_PENALTY_POLICY
    assert strong_policy["weighted_cooc_feature"] == "weighted_cooc"
    assert strong_policy["scale_tiers"]["smoke"] == {
        "max_output_users": 1_000,
        "max_items_per_user": 50,
        "max_item_user_freq": 3_000,
        "min_pair_support": 2,
        "top_k_per_seed": 100,
    }
    assert usercf_policy["selection_strategy"]["policy_name"] == "usercf_neighbors_v1"
    assert usercf_policy["max_output_users"] == 120_000
    assert usercf_policy["similar_users_top_k"] == 200
    assert swing_policy["selection_strategy"]["policy_name"] == "swing_graph_v1"
    assert swing_policy["max_graph_users"] == 120_000
    assert swing_policy["max_item_user_freq"] == 600
    for policy in (weak_policy, strong_policy, usercf_policy, swing_policy):
        assert policy["default_tier"] == "local_formal"
        assert set(policy["scale_tiers"]) == {"smoke", "diagnostic", "local_formal"}
        local_formal = policy["scale_tiers"]["local_formal"]
        for key, value in local_formal.items():
            assert policy[key] == value
    assert weak_policy["scale_tiers"]["smoke"]["max_output_users"] == 1_000
    assert usercf_policy["scale_tiers"]["diagnostic"]["similar_users_top_k"] == 100
    assert swing_policy["scale_tiers"]["smoke"]["max_graph_users"] == 2_000
    assert {manifest["resource_scale_policy"]["p2_contract_scope"] for manifest in manifests.values()} == {"method_dataset_only"}
    assert len({manifest["config_hash"] for manifest in manifests.values()}) == len(SOURCE_METHODS)


def test_forbidden_valid_sequence_path_blocks_before_reading_rows(tmp_path: Path) -> None:
    governance_manifest = _write_governance_fixture(tmp_path)
    manifest_payload = _read_json(governance_manifest)
    valid_sequences = governance_manifest.parent / "user_sequences.valid.jsonl"
    _write_jsonl(valid_sequences, [{"user_id": "u_heavy", "recent_positive_item_sequence": ["cf_a", "cf_b"]}])
    manifest_payload["lineage"]["input_files"]["user_sequences_train"] = str(valid_sequences)
    _write_json(governance_manifest, manifest_payload)

    manifest = build_pool500_method_dataset(
        governance_manifest_path=governance_manifest,
        output_dir=tmp_path / "forbidden_valid",
        source_method="itemcf_weak",
        overwrite=True,
        enforce_venv=False,
    )

    assert manifest["status"] == "BLOCKED"
    assert manifest["row_count"] == 0
    assert manifest["outputs"] == {}
    assert manifest["dropped_reason_counts"] == {"forbidden_non_train_path:user_sequences.valid.jsonl": 1}
    assert not (tmp_path / "forbidden_valid" / "method_dataset_rows.jsonl").exists()


@pytest.mark.parametrize(
    "sequence_file_name",
    [
        "user_sequences.test.slice.jsonl",
        "user_sequences.holdout.jsonl",
        "oracle_user_sequences.train.jsonl",
        "user_sequences.eval_label.jsonl",
        "clean_10000_user_sequences.train.jsonl",
        "pool1000_user_sequences.train.jsonl",
        "source_index_user_sequences.train.jsonl",
        "embedding_user_sequences.train.jsonl",
        "user_sequences.faiss.jsonl",
        "ann_user_sequences.train.jsonl",
    ],
)
def test_forbidden_sequence_path_variants_block_before_reading_rows(tmp_path: Path, sequence_file_name: str) -> None:
    governance_manifest = _write_governance_fixture(tmp_path)
    manifest_payload = _read_json(governance_manifest)
    forbidden_sequences = governance_manifest.parent / sequence_file_name
    _write_jsonl(forbidden_sequences, [{"user_id": "u_heavy", "recent_positive_item_sequence": ["cf_a", "cf_b"]}])
    manifest_payload["lineage"]["input_files"]["user_sequences_train"] = str(forbidden_sequences)
    _write_json(governance_manifest, manifest_payload)

    manifest = build_pool500_method_dataset(
        governance_manifest_path=governance_manifest,
        output_dir=tmp_path / "forbidden_variant",
        source_method="itemcf_weak",
        overwrite=True,
        enforce_venv=False,
    )

    assert manifest["status"] == "BLOCKED"
    assert manifest["row_count"] == 0
    assert manifest["outputs"] == {}
    assert manifest["dropped_reason_counts"] == {f"forbidden_non_train_path:{sequence_file_name}": 1}
    assert not (tmp_path / "forbidden_variant" / "method_dataset_rows.jsonl").exists()


def test_missing_user_quality_bucket_v2_blocks_without_legacy_fallback(tmp_path: Path) -> None:
    governance_manifest = _write_governance_fixture(tmp_path, include_user_v2=False)

    manifest = build_pool500_method_dataset(
        governance_manifest_path=governance_manifest,
        output_dir=tmp_path / "blocked",
        source_method="itemcf_weak",
        overwrite=True,
        enforce_venv=False,
    )

    assert manifest["status"] == "BLOCKED"
    assert manifest["row_count"] == 0
    assert manifest["outputs"] == {}
    assert manifest["resource_scale_policy"]["p2_contract_scope"] == "method_dataset_only"
    assert manifest["resource_scale_policy"]["max_output_users"] == 300_000
    assert manifest["dropped_reason_counts"] == {"missing_user_quality_bucket_v2": 1}
    assert not (tmp_path / "blocked" / "method_dataset_rows.jsonl").exists()
    assert (tmp_path / "blocked" / "method_dataset_manifest.json").is_file()


def test_no_candidate_or_source_artifact_files_are_generated(tmp_path: Path) -> None:
    governance_manifest = _write_governance_fixture(tmp_path)

    build_pool500_method_dataset(
        governance_manifest_path=governance_manifest,
        output_dir=tmp_path / "usercf",
        source_method="usercf_method_dataset",
        overwrite=True,
        enforce_venv=False,
    )

    output_names = {path.name for path in (tmp_path / "usercf").iterdir()}
    assert "method_dataset_manifest.json" in output_names
    assert "method_dataset_rows.jsonl" in output_names
    assert not (output_names & FORBIDDEN_OUTPUT_NAMES)
    serialized = "\n".join(path.read_text(encoding="utf-8") for path in (tmp_path / "usercf").iterdir())
    assert "source_index_manifest" not in serialized
    assert "candidates_path" not in serialized
    assert "artifact_manifest_path" not in serialized
    assert "embedding_path" not in serialized
    assert "index_path" not in serialized
    assert "promotion_manifest" not in serialized
    assert "FULL_POOL500_READY" not in serialized


def _write_governance_fixture(tmp_path: Path, *, include_user_v2: bool = True) -> Path:
    root = tmp_path / "governance"
    root.mkdir()
    user_rows = [
        _user("u_heavy", "heavy_cf_eligible", include_user_v2),
        _user("u_heavy_2", "heavy_cf_eligible", include_user_v2),
        _user("u_medium", "medium_behavior", include_user_v2),
        _user("u_fallback", "fallback_only", include_user_v2),
    ]
    _write_jsonl(root / "user_quality_profile.jsonl", user_rows)
    _write_jsonl(
        root / "item_quality_profile.jsonl",
        [
            _item("cf_a", cf_ready=True, hotness_bucket="mid", quality_bucket_v2="cf_ready"),
            _item("cf_b", cf_ready=True, hotness_bucket="mid", quality_bucket_v2="cf_ready"),
            _item("cf_mid", cf_ready=True, hotness_bucket="mid", quality_bucket_v2="cf_ready"),
            _item("too_hot", cf_ready=True, hotness_bucket="hot", quality_bucket_v2="embedding_ready"),
            _item("cold", cf_ready=False, hotness_bucket="long_tail", quality_bucket_v2="low_frequency"),
        ],
    )
    _write_jsonl(
        root / "item_frequency_train.jsonl",
        [
            {"parent_asin": "cf_a", "frequency": 3, "user_count": 3},
            {"parent_asin": "cf_b", "frequency": 3, "user_count": 3},
            {"parent_asin": "cf_mid", "frequency": 2, "user_count": 2},
            {"parent_asin": "too_hot", "frequency": 9, "user_count": 3},
            {"parent_asin": "cold", "frequency": 1, "user_count": 1},
        ],
    )
    _write_jsonl(
        root / "user_sequences.train.jsonl",
        [
            {"user_id": "u_heavy", "recent_positive_item_sequence": ["cf_a", "cf_b", "cf_mid", "too_hot", "cold"]},
            {"user_id": "u_heavy_2", "recent_positive_item_sequence": ["cf_a", "cf_b"]},
            {"user_id": "u_medium", "recent_positive_item_sequence": ["cf_a", "cf_mid", "too_hot"]},
            {"user_id": "u_fallback", "recent_positive_item_sequence": ["cf_a", "cf_b"]},
        ],
    )
    manifest = {
        "schema_version": GOVERNANCE_SCHEMA_VERSION,
        "status": "PASS",
        "train_only": True,
        "artifacts": {
            "user_quality_profile": str(root / "user_quality_profile.jsonl"),
            "item_quality_profile": str(root / "item_quality_profile.jsonl"),
            "item_frequency_train": str(root / "item_frequency_train.jsonl"),
        },
        "lineage": {"input_files": {"user_sequences_train": str(root / "user_sequences.train.jsonl")}},
        "derived_dataset_policies": DERIVED_DATASET_POLICIES,
    }
    manifest_path = root / "manifest.json"
    _write_json(manifest_path, manifest)
    return manifest_path


def _user(user_id: str, bucket: str, include_user_v2: bool) -> dict[str, object]:
    row: dict[str, object] = {"user_id": user_id, "quality_bucket": bucket}
    if include_user_v2:
        row["quality_bucket_v2"] = _user_bucket_v2(bucket)
    return row


def _user_bucket_v2(bucket: str) -> str:
    return {
        "cold_start": "cold_start",
        "fallback_only": "fallback_only",
        "medium_behavior": "medium_behavior",
        "two_tower_train_eligible": "sequence_sufficient",
        "heavy_cf_eligible": "collaborative_rich",
    }[bucket]


def _item(parent_asin: str, *, cf_ready: bool, hotness_bucket: str, quality_bucket_v2: str) -> dict[str, object]:
    return {
        "parent_asin": parent_asin,
        "cf_ready": cf_ready,
        "hotness_bucket": hotness_bucket,
        "quality_bucket_v2": quality_bucket_v2,
        "train_only": True,
    }


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def _read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
