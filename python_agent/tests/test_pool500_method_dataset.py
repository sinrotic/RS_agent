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


@pytest.fixture(autouse=True)
def _recent_2y_governance_fixture_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(method_dataset_builder, "RECENT_2Y_GOVERNANCE_MANIFEST", tmp_path / "governance" / "manifest.json")


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
        assert manifest["resource_scale_policy"]["input_scope"] == "recent_window_2y_train_only_governance"
        assert manifest["resource_scale_policy"]["scale_tier"] == "smoke"
        assert manifest["resource_scale_policy"]["selection_strategy"]
        assert manifest["resource_scale_policy"]["default_tier"] == "formal"
        assert set(manifest["resource_scale_policy"]["scale_tiers"]) == {"smoke", "formal"}
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


def test_itemcf_weak_coverage_profile_broadens_users_and_items_without_changing_layer(tmp_path: Path) -> None:
    governance_manifest = _write_governance_fixture(tmp_path)

    manifest = build_pool500_method_dataset(
        governance_manifest_path=governance_manifest,
        output_dir=tmp_path / "weak_coverage",
        source_method="itemcf_weak",
        itemcf_coverage_profile="weak_coverage",
        overwrite=True,
        enforce_venv=False,
    )

    rows = _read_jsonl(Path(manifest["outputs"]["dataset_rows_path"]))
    policy = manifest["resource_scale_policy"]
    assert manifest["status"] == "PASS"
    assert manifest["outputs"]["dataset_schema"] == "itemcf_edge_features_v1"
    assert manifest["candidate_generation_allowed"] is False
    assert manifest["ranking_input_replacement_allowed"] is False
    assert policy["coverage_profile"] == "weak_coverage"
    assert policy["max_output_users"] == 0
    assert policy["max_output_users_semantics"] == "agent_managed_unlimited_actual_eligible_users"
    assert policy["max_items_per_user"] == 0
    assert policy["max_items_per_user_semantics"] == "agent_managed_unlimited_user_history"
    assert policy["max_item_user_freq"] == 0
    assert policy["max_item_user_freq_semantics"] == "agent_managed_no_method_cap"
    assert policy["top_k_per_seed"] == 0
    assert policy["top_k_per_seed_semantics"] == "agent_managed_no_method_cap"
    assert policy["item_quality_buckets"] == ["cf_ready", "embedding_ready"]
    assert policy["allow_over_hot"] is True
    assert manifest["selection_policy"]["eligible_user_buckets"] == ["medium_behavior", "sequence_sufficient", "collaborative_rich"]
    assert "embedding_ready" in manifest["effective_item_bucket_policy"]
    assert manifest["unique_pair_count"] == 6
    assert manifest["directed_edge_count_after_topk"] == 12
    assert {row["src_item_id"] for row in rows} >= {"cf_a", "cf_b", "cf_mid", "too_hot"}
    assert {row["dst_item_id"] for row in rows} >= {"cf_a", "cf_b", "cf_mid", "too_hot"}
    assert all(row["top_k_per_seed"] == 0 for row in rows)
    assert manifest["dropped_reason_counts"]["item_quality_bucket_not_allowed"] == 1
    assert "item_over_hot" not in manifest["dropped_reason_counts"]


def test_itemcf_weak_denoised_profile_keeps_coverage_but_applies_noise_controls(tmp_path: Path) -> None:
    governance_manifest = _write_governance_fixture(tmp_path, include_sequence_user=True)

    manifest = build_pool500_method_dataset(
        governance_manifest_path=governance_manifest,
        output_dir=tmp_path / "weak_denoised",
        source_method="itemcf_weak",
        itemcf_coverage_profile="weak_denoised",
        overwrite=True,
        enforce_venv=False,
    )

    rows = _read_jsonl(Path(manifest["outputs"]["dataset_rows_path"]))
    policy = manifest["resource_scale_policy"]
    assert manifest["status"] == "PASS"
    assert manifest["candidate_generation_allowed"] is False
    assert policy["coverage_profile"] == "weak_denoised"
    assert policy["dataset_variant"] == "itemcf_weak_denoised_formal_v1"
    assert policy["score_policy"] == method_dataset_builder.ITEMCF_SCORE_POLICY
    assert policy["shrinkage_alpha"] == 0.0
    assert policy["top_k_per_seed"] == 200
    assert policy["allow_over_hot"] is True
    assert policy["weighting_policy"] == "existing_weighted_cooc_cosine_with_seed_topk200_cap_v1"
    assert manifest["selection_policy"]["eligible_user_buckets"] == ["medium_behavior", "sequence_sufficient", "collaborative_rich"]
    assert manifest["selection_policy"]["eligible_item_policy"] == "cf_ready_or_embedding_ready_with_support1_and_seed_topk200_route_gate"
    assert manifest["score_policy"] == method_dataset_builder.ITEMCF_SCORE_POLICY
    assert manifest["itemcf_score_formula"] == method_dataset_builder.ITEMCF_SCORE_FORMULA
    assert manifest["shrinkage_alpha"] == 0.0
    assert manifest["top_k_per_seed"] == 200
    assert {"too_hot", "cf_hot"} & ({row["src_item_id"] for row in rows} | {row["dst_item_id"] for row in rows})
    assert "embed_seed" in {row["src_item_id"] for row in rows} | {row["dst_item_id"] for row in rows}
    assert "item_over_hot" not in manifest["dropped_reason_counts"]
    assert all(row["score_policy"] == method_dataset_builder.ITEMCF_SCORE_POLICY for row in rows)
    assert all(row["shrinkage_alpha"] == 0.0 for row in rows)
    assert all(row["top_k_per_seed"] == 200 for row in rows)



def test_augcf_lite_profile_adds_train_only_observed_pseudo_metadata(tmp_path: Path) -> None:
    governance_manifest = _write_governance_fixture(tmp_path)

    baseline = build_pool500_method_dataset(
        governance_manifest_path=governance_manifest,
        output_dir=tmp_path / "weak_baseline",
        source_method="itemcf_weak",
        itemcf_coverage_profile="weak_coverage",
        overwrite=True,
        enforce_venv=False,
    )
    manifest = build_pool500_method_dataset(
        governance_manifest_path=governance_manifest,
        output_dir=tmp_path / "augcf_lite",
        source_method="itemcf_weak",
        itemcf_coverage_profile="augcf_lite",
        overwrite=True,
        enforce_venv=False,
    )

    rows = _read_jsonl(Path(manifest["outputs"]["dataset_rows_path"]))
    policy = manifest["resource_scale_policy"]
    assert manifest["status"] == "PASS"
    assert manifest["candidate_generation_allowed"] is False
    assert manifest["ranking_input_replacement_allowed"] is False
    assert manifest["promotion_allowed"] is False
    assert manifest["final_pool500_ready_claimed"] is False
    assert policy["coverage_profile"] == "augcf_lite"
    assert policy["score_policy"] == "augcf_lite_profile_score_v1"
    assert policy["augmentation_policy"] == "train_only_observed_pseudo_low_freq_v1"
    assert policy["pseudo_weight"] == 0.25
    assert manifest["selection_policy"]["eligible_item_policy"] == "cf_ready_or_embedding_ready_train_only_observed_pseudo_augcf_lite"
    assert manifest["score_policy"] == "augcf_lite_profile_score_v1"
    assert manifest["unique_pair_count"] == baseline["unique_pair_count"]
    assert all(row["score_policy"] == "augcf_lite_profile_score_v1" for row in rows)
    assert all(row["augmentation_policy"] == "train_only_observed_pseudo_low_freq_v1" for row in rows)
    assert all(row["augcf_family"] == "AugCF-lite" for row in rows)
    assert all(row["augcf_reproduction_level"] == "lightweight_train_only_profile" for row in rows)
    assert all(row["gan_enabled"] is False for row in rows)
    assert all(row["gumbel_softmax_enabled"] is False for row in rows)
    assert all(row["pseudo_pseudo_pairs_enabled"] is False for row in rows)
    assert all("itemcf_score" in row for row in rows)
    assert all("base_itemcf_score" in row for row in rows)
    assert all("augcf_lite_score" in row for row in rows)
    assert all(row["pseudo_contribution_sum"] <= policy["pseudo_weight"] for row in rows)
    augmented_rows = [row for row in rows if row["pseudo_contribution_sum"] > 0]
    assert augmented_rows
    assert all(row["augcf_lite_score"] >= row["base_itemcf_score"] for row in augmented_rows)
    assert all(row["observed_pair_support"] + row["augmented_pair_support"] == row["pair_support"] for row in rows)


def test_itemcf_relaxed_strong_profile_broadens_strong_without_matching_weak_coverage(tmp_path: Path) -> None:
    governance_manifest = _write_governance_fixture(tmp_path, include_sequence_user=True)

    strict = build_pool500_method_dataset(
        governance_manifest_path=governance_manifest,
        output_dir=tmp_path / "strong_strict",
        source_method="itemcf_strong",
        overwrite=True,
        enforce_venv=False,
    )
    relaxed = build_pool500_method_dataset(
        governance_manifest_path=governance_manifest,
        output_dir=tmp_path / "strong_relaxed",
        source_method="itemcf_strong",
        itemcf_coverage_profile="relaxed_strong",
        overwrite=True,
        enforce_venv=False,
    )

    rows = _read_jsonl(Path(relaxed["outputs"]["dataset_rows_path"]))
    policy = relaxed["resource_scale_policy"]
    assert relaxed["status"] == "PASS"
    assert relaxed["outputs"]["dataset_schema"] == "itemcf_edge_features_v1"
    assert relaxed["candidate_generation_allowed"] is False
    assert relaxed["ranking_input_replacement_allowed"] is False
    assert relaxed["promotion_allowed"] is False
    assert relaxed["final_pool500_ready_claimed"] is False
    assert policy["coverage_profile"] == "relaxed_strong"
    assert policy["dataset_variant"] == "itemcf_strong_relaxed_seedsrc_smoke_v3"
    assert policy["selection_strategy"]["policy_name"] == "itemcf_strong_relaxed_edges_v1"
    assert policy["selection_strategy"]["eligible_user_buckets"] == ["sequence_sufficient", "collaborative_rich"]
    assert policy["item_quality_buckets"] == ["cf_ready", "embedding_ready"]
    assert policy["src_item_quality_buckets"] == ["cf_ready", "embedding_ready"]
    assert policy["dst_item_quality_buckets"] == ["cf_ready", "embedding_ready"]
    assert policy["allow_over_hot"] is False
    assert policy["src_allow_over_hot"] is True
    assert policy["relaxed_scale_tiers"]["smoke"]["max_output_users"] == 5_000
    assert set(policy["relaxed_scale_tiers"]) == {"smoke", "formal"}
    assert policy["relaxed_scale_tiers"]["formal"]["max_output_users"] == 0
    assert policy["max_output_users"] == 5_000
    assert policy["max_items_per_user"] == 60
    assert policy["max_item_user_freq"] == 8_000
    assert policy["min_pair_support"] == 1
    assert policy["top_k_per_seed"] == 150
    assert policy["src_sequence_key"] == "recent_strong_positive_item_sequence"
    assert policy["dst_sequence_key"] == "recent_positive_item_sequence"
    assert policy["directed_seed_to_candidate_only"] is True
    assert relaxed["selection_policy"]["eligible_user_buckets"] == ["sequence_sufficient", "collaborative_rich"]
    assert relaxed["selection_policy"]["eligible_user_policy"] == "sequence_sufficient_or_collaborative_rich_for_relaxed_strong_itemcf"
    assert "hot allowed" in relaxed["effective_item_bucket_policy"]
    assert "dst candidate items in {cf_ready, embedding_ready} and non-hot" in relaxed["effective_item_bucket_policy"]
    assert relaxed["edge_count"] > strict["edge_count"]
    assert relaxed["unique_pair_count"] == 16
    assert relaxed["edge_count"] == 16
    assert {(row["src_item_id"], row["dst_item_id"], row["pair_support"]) for row in rows} == {
        ("cf_a", "cf_b", 2),
        ("cf_b", "cf_a", 2),
        ("cf_a", "cf_mid", 2),
        ("cf_mid", "cf_a", 2),
        ("cf_b", "cf_mid", 1),
        ("cf_mid", "cf_b", 1),
        ("embed_seed", "cf_a", 1),
        ("embed_seed", "cf_mid", 1),
        ("cf_a", "embed_seed", 1),
        ("cf_mid", "embed_seed", 1),
        ("too_hot", "cf_a", 1),
        ("too_hot", "cf_b", 1),
        ("too_hot", "cf_mid", 1),
        ("cf_hot", "cf_a", 1),
        ("cf_hot", "cf_mid", 1),
        ("cf_hot", "embed_seed", 1),
    }
    assert {row["src_item_id"] for row in rows} == {"cf_a", "cf_b", "cf_mid", "embed_seed", "too_hot", "cf_hot"}
    assert {row["dst_item_id"] for row in rows} == {"cf_a", "cf_b", "cf_mid", "embed_seed"}
    assert "too_hot" not in {row["dst_item_id"] for row in rows}
    assert "cf_hot" not in {row["dst_item_id"] for row in rows}
    assert relaxed["dropped_reason_counts"]["user_bucket_not_allowed"] == 2
    assert relaxed["dropped_reason_counts"]["pair_below_min_support"] == 0
    assert relaxed["dropped_reason_counts"]["item_over_hot"] == 2


def test_usercf_relaxed_iuf_profile_broadens_item_universe_without_candidate_generation(tmp_path: Path) -> None:
    governance_manifest = _write_governance_fixture(tmp_path, include_sequence_user=True)

    strict = build_pool500_method_dataset(
        governance_manifest_path=governance_manifest,
        output_dir=tmp_path / "usercf_strict",
        source_method="usercf_method_dataset",
        overwrite=True,
        enforce_venv=False,
    )
    relaxed = build_pool500_method_dataset(
        governance_manifest_path=governance_manifest,
        output_dir=tmp_path / "usercf_relaxed_iuf",
        source_method="usercf_method_dataset",
        itemcf_coverage_profile="usercf_relaxed_iuf",
        overwrite=True,
        enforce_venv=False,
    )

    rows = _read_jsonl(Path(relaxed["outputs"]["dataset_rows_path"]))
    policy = relaxed["resource_scale_policy"]
    assert relaxed["status"] == "PASS"
    assert relaxed["outputs"]["dataset_schema"] == "eligible_user_sequence_v1"
    assert relaxed["candidate_generation_allowed"] is False
    assert relaxed["ranking_input_replacement_allowed"] is False
    assert relaxed["promotion_allowed"] is False
    assert relaxed["final_pool500_ready_claimed"] is False
    assert policy["coverage_profile"] == "usercf_relaxed_iuf"
    assert policy["dataset_variant"] == "usercf_relaxed_iuf_smoke_v1"
    assert policy["item_quality_buckets"] == ["cf_ready", "embedding_ready"]
    assert policy["allow_over_hot"] is True
    assert policy["weighting_policy"] == "iuf_cosine_user_similarity_v1"
    assert relaxed["weighting_policy"] == "iuf_cosine_user_similarity_v1"
    assert relaxed["preprocessing_policy"] == "usercf_relaxed_cf_or_embedding_ready_hot_allowed_train_only_v1"
    assert relaxed["selection_policy"]["eligible_user_buckets"] == ["sequence_sufficient", "collaborative_rich"]
    assert relaxed["selection_policy"]["eligible_item_policy"] == "cf_ready_or_embedding_ready_with_hot_allowed_as_iuf_weighted_similarity_signal"
    assert "IUF-weighted similarity signal" in relaxed["effective_item_bucket_policy"]
    assert relaxed["row_count"] > strict["row_count"]
    assert relaxed["item_count"] > strict["item_count"]
    assert {row["user_id"] for row in rows} == {"u_heavy", "u_heavy_2", "u_sequence"}
    sequence_row = next(row for row in rows if row["user_id"] == "u_sequence")
    assert "embed_seed" in sequence_row["eligible_item_sequence"]
    assert "cf_hot" in sequence_row["eligible_item_sequence"]
    assert "too_hot" in {item_id for row in rows for item_id in row["eligible_item_sequence"]}
    assert "item_over_hot" not in relaxed["dropped_reason_counts"]



def test_current_method_dataset_rejects_non_2y_governance_manifest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    governance_manifest = _write_governance_fixture(tmp_path)
    monkeypatch.setattr(method_dataset_builder, "RECENT_2Y_GOVERNANCE_MANIFEST", tmp_path / "other" / "manifest.json")

    with pytest.raises(ValueError, match="recent 2y train-only governance"):
        build_pool500_method_dataset(
            governance_manifest_path=governance_manifest,
            output_dir=tmp_path / "wrong_manifest",
            source_method="itemcf_weak",
            overwrite=True,
            enforce_venv=False,
        )


def test_itemcf_relaxed_strong_scale_tiers_have_distinct_caps(tmp_path: Path) -> None:
    governance_manifest = _write_governance_fixture(tmp_path, include_sequence_user=True)

    smoke = build_pool500_method_dataset(
        governance_manifest_path=governance_manifest,
        output_dir=tmp_path / "strong_relaxed_smoke",
        source_method="itemcf_strong",
        scale_tier="smoke",
        itemcf_coverage_profile="relaxed_strong",
        overwrite=True,
        enforce_venv=False,
    )
    formal = build_pool500_method_dataset(
        governance_manifest_path=governance_manifest,
        output_dir=tmp_path / "strong_relaxed_formal",
        source_method="itemcf_strong",
        scale_tier="formal",
        itemcf_coverage_profile="relaxed_strong",
        overwrite=True,
        enforce_venv=False,
    )

    assert smoke["resource_scale_policy"]["dataset_variant"] == "itemcf_strong_relaxed_seedsrc_smoke_v3"
    assert smoke["resource_scale_policy"]["max_output_users"] == 5_000
    assert formal["resource_scale_policy"]["dataset_variant"] == "itemcf_strong_relaxed_seedsrc_formal_v3"
    assert formal["resource_scale_policy"]["max_output_users"] == 0
    assert smoke["resource_scale_policy"]["max_items_per_user"] == 60
    assert formal["resource_scale_policy"]["max_items_per_user"] == 0
    assert smoke["candidate_generation_allowed"] is False
    assert formal["candidate_generation_allowed"] is False


def test_itemcf_coverage_profiles_are_source_specific(tmp_path: Path) -> None:
    governance_manifest = _write_governance_fixture(tmp_path)

    with pytest.raises(ValueError, match="weak_coverage profile is only supported for itemcf_weak"):
        build_pool500_method_dataset(
            governance_manifest_path=governance_manifest,
            output_dir=tmp_path / "bad_weak_profile",
            source_method="itemcf_strong",
            itemcf_coverage_profile="weak_coverage",
            overwrite=True,
            enforce_venv=False,
        )

    with pytest.raises(ValueError, match="relaxed_strong profile is only supported for itemcf_strong"):
        build_pool500_method_dataset(
            governance_manifest_path=governance_manifest,
            output_dir=tmp_path / "bad_strong_profile",
            source_method="itemcf_weak",
            itemcf_coverage_profile="relaxed_strong",
            overwrite=True,
            enforce_venv=False,
        )

    with pytest.raises(ValueError, match="weak_denoised profile is only supported for itemcf_weak"):
        build_pool500_method_dataset(
            governance_manifest_path=governance_manifest,
            output_dir=tmp_path / "bad_weak_denoised_profile",
            source_method="itemcf_strong",
            itemcf_coverage_profile="weak_denoised",
            overwrite=True,
            enforce_venv=False,
        )

    with pytest.raises(ValueError, match="augcf_lite profile is only supported for itemcf_weak"):
        build_pool500_method_dataset(
            governance_manifest_path=governance_manifest,
            output_dir=tmp_path / "bad_augcf_lite_profile",
            source_method="itemcf_strong",
            itemcf_coverage_profile="augcf_lite",
            overwrite=True,
            enforce_venv=False,
        )

    with pytest.raises(ValueError, match="usercf_relaxed_iuf profile is only supported for usercf_method_dataset"):
        build_pool500_method_dataset(
            governance_manifest_path=governance_manifest,
            output_dir=tmp_path / "bad_usercf_profile",
            source_method="itemcf_weak",
            itemcf_coverage_profile="usercf_relaxed_iuf",
            overwrite=True,
            enforce_venv=False,
        )


def test_itemcf_edge_features_score_rank_and_topk_are_method_dataset_features(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    governance_manifest = _write_governance_fixture(tmp_path)
    capped_policy = json.loads(json.dumps(method_dataset_builder.RESOURCE_SCALE_POLICIES["itemcf_weak"]))
    capped_policy["scale_tiers"]["smoke"]["top_k_per_seed"] = 1
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
        ("cf_b", "cf_mid", 1),
    }
    assert all(row["dataset_role"] == "method_dataset_swing_pair_support" for row in rows)
    assert manifest["user_count"] == 3
    assert manifest["item_count"] == 3
    assert manifest["dropped_reason_counts"]["pair_below_min_support"] == 0
    assert manifest["dropped_reason_counts"]["user_bucket_not_allowed"] == 1


def test_usercf_method_dataset_applies_user_and_item_caps(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    governance_manifest = _write_governance_fixture(tmp_path)
    capped_policy = json.loads(json.dumps(method_dataset_builder.RESOURCE_SCALE_POLICIES["usercf_method_dataset"]))
    capped_policy["scale_tiers"]["smoke"]["max_output_users"] = 1
    capped_policy["scale_tiers"]["smoke"]["max_output_user_ratio"] = 0
    capped_policy["scale_tiers"]["smoke"]["max_items_per_user"] = 2
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
    assert policy["max_output_users"] == 0
    assert policy["max_output_user_ratio"] == 0.02
    assert policy["max_items_per_user"] == 80
    assert policy["similar_users_top_k"] == 50
    assert policy["max_output_user_ratio"] != policy["scale_tiers"]["formal"].get("max_output_user_ratio")


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
    assert weak_policy["max_output_users"] == 1_000
    assert weak_policy["max_item_user_freq"] == 5_000
    assert weak_policy["min_pair_support"] == 1
    assert weak_policy["top_k_per_seed"] == 100
    assert weak_policy["score_policy"] == method_dataset_builder.ITEMCF_SCORE_POLICY
    assert weak_policy["active_user_penalty_policy"] == method_dataset_builder.ITEMCF_ACTIVE_USER_PENALTY_POLICY
    assert weak_policy["weighted_cooc_feature"] == "weighted_cooc"
    assert weak_policy["scale_tiers"]["formal"]["max_output_users"] == 0
    assert strong_policy["selection_strategy"]["policy_name"] == "itemcf_strong_edges_v1"
    assert strong_policy["selection_strategy"]["eligible_user_buckets"] == ["collaborative_rich"]
    assert strong_policy["max_output_users"] == 1_000
    assert strong_policy["max_item_user_freq"] == 3_000
    assert strong_policy["min_pair_support"] == 2
    assert strong_policy["top_k_per_seed"] == 100
    assert strong_policy["score_policy"] == method_dataset_builder.ITEMCF_SCORE_POLICY
    assert strong_policy["active_user_penalty_policy"] == method_dataset_builder.ITEMCF_ACTIVE_USER_PENALTY_POLICY
    assert strong_policy["weighted_cooc_feature"] == "weighted_cooc"
    assert strong_policy["scale_tiers"]["formal"]["max_output_users"] == 0
    assert usercf_policy["selection_strategy"]["policy_name"] == "usercf_neighbors_v1"
    assert usercf_policy["max_output_users"] == 0
    assert usercf_policy["similar_users_top_k"] == 50
    assert swing_policy["selection_strategy"]["policy_name"] == "swing_graph_v1"
    assert swing_policy["max_graph_users"] == 2_000
    assert swing_policy["max_item_user_freq"] == 1_000
    for policy in (weak_policy, strong_policy, usercf_policy, swing_policy):
        assert policy["default_tier"] == "formal"
        assert set(policy["scale_tiers"]) == {"smoke", "formal"}
    assert weak_policy["scale_tiers"]["smoke"]["max_output_users"] == 1_000
    assert usercf_policy["scale_tiers"]["smoke"]["similar_users_top_k"] == 50
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
    assert manifest["resource_scale_policy"]["max_output_users"] == 1_000
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


def _write_governance_fixture(tmp_path: Path, *, include_user_v2: bool = True, include_sequence_user: bool = False) -> Path:
    root = tmp_path / "governance"
    root.mkdir()
    user_rows = [
        _user("u_heavy", "heavy_cf_eligible", include_user_v2),
        _user("u_heavy_2", "heavy_cf_eligible", include_user_v2),
        _user("u_medium", "medium_behavior", include_user_v2),
        _user("u_fallback", "fallback_only", include_user_v2),
    ]
    if include_sequence_user:
        user_rows.append(_user("u_sequence", "two_tower_train_eligible", include_user_v2))
    _write_jsonl(root / "user_quality_profile.jsonl", user_rows)
    item_rows = [
        _item("cf_a", cf_ready=True, hotness_bucket="mid", quality_bucket_v2="cf_ready"),
        _item("cf_b", cf_ready=True, hotness_bucket="mid", quality_bucket_v2="cf_ready"),
        _item("cf_mid", cf_ready=True, hotness_bucket="mid", quality_bucket_v2="cf_ready"),
        _item("too_hot", cf_ready=True, hotness_bucket="hot", quality_bucket_v2="embedding_ready"),
        _item("cold", cf_ready=False, hotness_bucket="long_tail", quality_bucket_v2="low_frequency"),
    ]
    if include_sequence_user:
        item_rows.append(_item("cf_hot", cf_ready=True, hotness_bucket="hot", quality_bucket_v2="cf_ready"))
        item_rows.append(_item("embed_seed", cf_ready=False, hotness_bucket="mid", quality_bucket_v2="embedding_ready"))
    _write_jsonl(root / "item_quality_profile.jsonl", item_rows)
    item_frequency_rows = [
        {"parent_asin": "cf_a", "frequency": 3, "user_count": 3},
        {"parent_asin": "cf_b", "frequency": 3, "user_count": 3},
        {"parent_asin": "cf_mid", "frequency": 2, "user_count": 2},
        {"parent_asin": "too_hot", "frequency": 9, "user_count": 3},
        {"parent_asin": "cold", "frequency": 1, "user_count": 1},
    ]
    if include_sequence_user:
        item_frequency_rows.append({"parent_asin": "cf_hot", "frequency": 2, "user_count": 1})
        item_frequency_rows.append({"parent_asin": "embed_seed", "frequency": 1, "user_count": 1})
    _write_jsonl(root / "item_frequency_train.jsonl", item_frequency_rows)
    sequence_rows = [
        _sequence("u_heavy", ["cf_a", "cf_b", "cf_mid", "too_hot", "cold"]),
        _sequence("u_heavy_2", ["cf_a", "cf_b"]),
        _sequence("u_medium", ["cf_a", "cf_mid", "too_hot"]),
        _sequence("u_fallback", ["cf_a", "cf_b"]),
    ]
    if include_sequence_user:
        sequence_rows.append(_sequence("u_sequence", ["embed_seed", "cf_a", "cf_mid", "cf_hot"]))
    _write_jsonl(root / "user_sequences.train.jsonl", sequence_rows)
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


def _sequence(user_id: str, items: list[str]) -> dict[str, object]:
    return {
        "user_id": user_id,
        "recent_positive_item_sequence": items,
        "recent_strong_positive_item_sequence": items,
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
