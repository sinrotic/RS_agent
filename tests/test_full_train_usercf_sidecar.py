from __future__ import annotations

import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

from rs_core.online.recall.candidate_merge import load_usercf_recall_sidecar, merge_for_user
from rs_lab.experiments.recall.build_full_train_usercf_sidecar import build_full_train_usercf_sidecar


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def make_clean_manifest(tmp_path: Path, rows: list[dict], manifest_patch: dict | None = None) -> Path:
    clean_dir = tmp_path / "amazon_2023_recall_clean_full"
    sequence_path = clean_dir / "user_sequences.train.jsonl"
    write_jsonl(sequence_path, rows)
    write_jsonl(clean_dir / "user_sequences.valid.jsonl", [{"must_not_be_read": True}])
    write_jsonl(clean_dir / "user_sequences.test.jsonl", [{"must_not_be_read": True}])
    write_jsonl(clean_dir / "holdout.jsonl", [{"must_not_be_read": True}])
    manifest = {"train_user_sequences_path": str(sequence_path)}
    if manifest_patch:
        manifest.update(manifest_patch)
    manifest_path = clean_dir / "manifest.json"
    write_json(manifest_path, manifest)
    return manifest_path


def make_user_quality_manifest(tmp_path: Path, profiles: list[dict], scope: str = "diagnostic_limited_train_users") -> Path:
    path = tmp_path / "eligible_user_quality_manifest.json"
    write_json(
        path,
        {
            "schema_version": "pool500_user_quality_profile_v1",
            "status": "PASS",
            "scope": scope,
            "policy_role": "eligibility_policy_not_recall_source",
            "train_only": True,
            "candidate_generation_allowed": False,
            "ranking_input_replacement_allowed": False,
            "pool1000_allowed": False,
            "final_pool500_ready_claimed": False,
            "profiles": profiles,
        },
    )
    return path


def make_rpa_like_method_dataset_manifest(tmp_path: Path, rows: list[dict], manifest_patch: dict | None = None) -> Path:
    method_dir = tmp_path / "rpa_like_method_dataset"
    rows_path = method_dir / "method_dataset_rows.jsonl"
    write_jsonl(rows_path, rows)
    manifest = {
        "schema_version": "rpa_like_recent2y_method_dataset_v1",
        "row_schema_version": "rpa_like_eligible_sequence_v1",
        "status": "PASS",
        "dataset_tier": "smoke",
        "source_method": "rpa_like_recursive_cf",
        "source_variant": "recursive_cf_lite_zhang_pu_2007_dataset_v1",
        "source_status": "DIAGNOSTIC_ONLY",
        "diagnostic_only": True,
        "train_only": True,
        "candidate_generation_allowed": False,
        "ranking_input_replacement_allowed": False,
        "pool1000_allowed": False,
        "promotion_allowed": False,
        "final_pool500_ready_claimed": False,
        "ready_source_artifact": False,
        "label_backflow_allowed": False,
        "row_count": len(rows),
        "outputs": {
            "method_dataset_rows": str(rows_path),
            "method_dataset_manifest": str(method_dir / "method_dataset_manifest.json"),
        },
        "labels_role": "none_in_dataset_build_or_candidate_generation",
    }
    if manifest_patch:
        manifest.update(manifest_patch)
    manifest_path = method_dir / "method_dataset_manifest.json"
    write_json(manifest_path, manifest)
    return manifest_path


def profile(user_id: str, bucket: str = "heavy_cf_eligible") -> dict:
    return {
        "user_id": user_id,
        "positive_count": 20 if bucket == "heavy_cf_eligible" else 6,
        "unique_item_count": 10 if bucket == "heavy_cf_eligible" else 3,
        "category_count": 2,
        "shared_item_neighbor_count": 3 if bucket == "heavy_cf_eligible" else 0,
        "quality_bucket": bucket,
        "eligible_for_usercf": bucket == "heavy_cf_eligible",
        "eligible_for_itemcf": bucket in {"heavy_cf_eligible", "medium_behavior"},
        "eligible_for_swing": bucket in {"heavy_cf_eligible", "medium_behavior"},
        "fallback_only": bucket == "fallback_only",
    }


def build_for_test(manifest_path: Path, output_dir: Path, **kwargs) -> dict:
    return build_full_train_usercf_sidecar(
        clean_manifest=manifest_path,
        output_dir=output_dir,
        eligible_user_quality_manifest=kwargs.pop("eligible_user_quality_manifest", None),
        method_dataset_manifest=kwargs.pop("method_dataset_manifest", None),
        target_users_path=kwargs.pop("target_users_path", None),
        max_items_per_user=kwargs.pop("max_items_per_user", 10),
        max_item_user_freq=kwargs.pop("max_item_user_freq", 10),
        src_min_positive_user_count=kwargs.pop("src_min_positive_user_count", 1),
        dst_min_positive_user_count=kwargs.pop("dst_min_positive_user_count", 1),
        min_src_filtered_items_per_user=kwargs.pop("min_src_filtered_items_per_user", 1),
        keep_hot=kwargs.pop("keep_hot", False),
        similar_users_top_k=kwargs.pop("similar_users_top_k", 2),
        candidate_top_k_per_user=kwargs.pop("candidate_top_k_per_user", 3),
        shard_count=kwargs.pop("shard_count", 3),
        target_batch_size=kwargs.pop("target_batch_size", 2),
        min_free_bytes=kwargs.pop("min_free_bytes", 0),
        max_rss_mb=kwargs.pop("max_rss_mb", 4096),
        enforce_venv=kwargs.pop("enforce_venv", False),
        **kwargs,
    )


def collect_shard_rows(manifest: dict) -> list[dict]:
    rows = []
    for shard_path in manifest["outputs"]["candidate_shards"]:
        rows.extend(read_jsonl(Path(shard_path)))
    return rows


def test_usercf_sidecar_builds_heavy_user_candidates_and_shards(tmp_path: Path) -> None:
    manifest_path = make_clean_manifest(
        tmp_path,
        [
            {"user_id": "u1", "recent_positive_item_sequence": ["a", "b"]},
            {"user_id": "u2", "recent_positive_item_sequence": ["a", "b", "c"]},
            {"user_id": "u3", "recent_positive_item_sequence": ["a", "d"]},
            {"user_id": "u4", "recent_positive_item_sequence": ["x"]},
        ],
    )
    eligible = make_user_quality_manifest(tmp_path, [profile("u1"), profile("u2"), profile("u3", "medium_behavior"), profile("u4", "fallback_only")])

    manifest = build_for_test(manifest_path, tmp_path / "usercf_sidecar", eligible_user_quality_manifest=eligible)

    persisted = read_json(tmp_path / "usercf_sidecar" / "source_index_manifest.json")
    assert persisted == manifest
    assert manifest["source"] == "usercf_recall"
    assert manifest["source_status"] == "DIAGNOSTIC_ONLY"
    assert manifest["index_scope"] == "FULL_DERIVED_INDEX"
    assert manifest["train_only"] is True
    assert manifest["candidate_generation_allowed"] is False
    assert manifest["ranking_input_replacement_allowed"] is False
    assert manifest["pool1000_allowed"] is False
    assert manifest["target_user_count"] == 2
    assert manifest["candidate_user_count"] == 2
    assert manifest["row_count"] == 2
    assert manifest["candidate_total_count"] == 3
    assert manifest["underfilled_user_coverage"] == 1.0
    assert manifest["marginal_candidate_share"] == 0.003
    assert manifest["outputs"]["per_source_candidate_manifest"] == str(tmp_path / "usercf_sidecar" / "per_source_candidate_manifest.json")
    assert len(manifest["outputs"]["candidate_shards"]) == 3
    assert {path.name for path in (tmp_path / "usercf_sidecar" / "shards").iterdir()} == {
        "usercf_recall_shard_00000.jsonl",
        "usercf_recall_shard_00001.jsonl",
        "usercf_recall_shard_00002.jsonl",
    }

    rows_by_user = {row["user_id"]: row for row in collect_shard_rows(manifest)}
    assert set(rows_by_user) == {"u1", "u2"}
    assert rows_by_user["u1"]["candidates"][0] == {"item_id": "c", "score": 0.816497, "rank": 1, "source": "usercf_recall"}
    assert rows_by_user["u2"]["candidates"][0]["item_id"] == "d"
    assert all(candidate["source"] == "usercf_recall" for row in rows_by_user.values() for candidate in row["candidates"])


def test_usercf_sidecar_can_include_medium_behavior_only_when_requested(tmp_path: Path) -> None:
    manifest_path = make_clean_manifest(
        tmp_path,
        [
            {"user_id": "u1", "recent_positive_item_sequence": ["a", "b"]},
            {"user_id": "u2", "recent_positive_item_sequence": ["a", "c"]},
        ],
    )
    eligible = make_user_quality_manifest(tmp_path, [profile("u1"), profile("u2", "medium_behavior")])

    heavy_only = build_for_test(manifest_path, tmp_path / "heavy", eligible_user_quality_manifest=eligible)
    with_medium = build_for_test(manifest_path, tmp_path / "medium", eligible_user_quality_manifest=eligible, include_medium_behavior=True)

    assert heavy_only["target_user_count"] == 1
    assert heavy_only["candidate_user_count"] == 1
    assert with_medium["target_user_count"] == 2
    assert with_medium["eligible_user_policy"] == "heavy_cf_eligible_or_medium_behavior"


def test_usercf_sidecar_accepts_target500_slice_policy_without_heavy_label(tmp_path: Path) -> None:
    manifest_path = make_clean_manifest(
        tmp_path,
        [
            {"user_id": "u1", "recent_positive_item_sequence": ["a", "b"]},
            {"user_id": "u2", "recent_positive_item_sequence": ["a", "c"]},
        ],
    )
    eligible = make_user_quality_manifest(
        tmp_path,
        [
            {"user_id": "u1", "quality_bucket": "target500_high_cost_slice", "eligible_for_usercf_slice": True, "eligible_for_usercf": False},
            {"user_id": "u2", "quality_bucket": "target500_high_cost_slice", "eligible_for_usercf_slice": True, "eligible_for_usercf": False},
        ],
        scope="target500_train_only_high_cost_slice_users",
    )

    manifest = build_for_test(manifest_path, tmp_path / "slice", eligible_user_quality_manifest=eligible)

    assert manifest["eligible_user_policy"] == "target500_train_only_high_cost_slice"
    assert manifest["target_user_count"] == 2
    assert manifest["candidate_user_count"] == 2



def test_usercf_sidecar_accepts_rpa_like_manifest_seed_sequence_and_target_users(tmp_path: Path) -> None:
    clean_manifest = make_clean_manifest(tmp_path / "clean", [{"user_id": "unused", "recent_positive_item_sequence": ["z"]}])
    method_manifest = make_rpa_like_method_dataset_manifest(
        tmp_path,
        [
            {"user_id": "target", "seed_item_sequence": ["a", "b"], "candidate_generation_allowed": False},
            {"user_id": "neighbor", "seed_item_sequence": ["a", "c"], "candidate_generation_allowed": False},
            {"user_id": "other", "seed_item_sequence": ["x", "y"], "candidate_generation_allowed": False},
        ],
    )
    target_users_path = tmp_path / "target_users.jsonl"
    write_jsonl(target_users_path, [{"user_id": "target"}, {"user_id": "missing"}])

    manifest = build_for_test(
        clean_manifest,
        tmp_path / "out",
        method_dataset_manifest=method_manifest,
        target_users_path=target_users_path,
    )

    rows = collect_shard_rows(manifest)
    resource = read_json(tmp_path / "out" / "resource_audit.json")
    no_holdout = read_json(tmp_path / "out" / "no_holdout_audit.json")
    selection = read_json(tmp_path / "out" / "custom_index_selection_manifest.json")
    assert manifest["resolved_paths"]["method_dataset_manifest"] == str(method_manifest.resolve())
    assert manifest["resolved_paths"]["target_users_path"] == str(target_users_path.resolve())
    assert manifest["source_status"] == "DIAGNOSTIC_ONLY"
    assert manifest["candidate_generation_allowed"] is False
    assert manifest["promotion_allowed"] is False
    assert manifest["target_user_count"] == 1
    assert rows == [{"user_id": "target", "candidates": [{"item_id": "c", "score": 0.5, "rank": 1, "source": "usercf_recall"}]}]
    assert resource["source_signature"]["field"] == "seed_item_sequence"
    assert resource["source_signature"]["dataset_schema"] == "rpa_like_eligible_sequence_v1"
    assert resource["explicit_target_user_count"] == 2
    assert resource["missing_explicit_target_user_count"] == 1
    assert no_holdout["target_users_role"] == "materialization_targets_only"
    assert no_holdout["train_sequence_field"] == "seed_item_sequence"
    assert "method_dataset_rows.seed_item_sequence" in selection["allowed_inputs"]


def test_usercf_sidecar_empty_heavy_manifest_does_not_fall_back_to_full_matrix(tmp_path: Path) -> None:
    manifest_path = make_clean_manifest(
        tmp_path,
        [
            {"user_id": "u1", "recent_positive_item_sequence": ["a", "b"]},
            {"user_id": "u2", "recent_positive_item_sequence": ["a", "c"]},
        ],
    )
    eligible = make_user_quality_manifest(tmp_path, [profile("u1", "medium_behavior"), profile("u2", "fallback_only")])

    manifest = build_for_test(manifest_path, tmp_path / "out", eligible_user_quality_manifest=eligible)
    resource = read_json(tmp_path / "out" / "resource_audit.json")

    assert manifest["target_user_count"] == 0
    assert manifest["indexed_user_count"] == 0
    assert manifest["candidate_user_count"] == 0
    assert manifest["candidate_total_count"] == 0
    assert collect_shard_rows(manifest) == []
    assert resource["train_rows_scanned"] == 0


def test_usercf_sidecar_writes_batch_checkpoints_for_resume(tmp_path: Path) -> None:
    manifest_path = make_clean_manifest(
        tmp_path,
        [
            {"user_id": "u1", "recent_positive_item_sequence": ["a", "b"]},
            {"user_id": "u2", "recent_positive_item_sequence": ["a", "c"]},
            {"user_id": "u3", "recent_positive_item_sequence": ["b", "d"]},
        ],
    )
    eligible = make_user_quality_manifest(tmp_path, [profile("u1"), profile("u2"), profile("u3")])

    manifest = build_for_test(manifest_path, tmp_path / "out", eligible_user_quality_manifest=eligible, target_batch_size=1)

    checkpoints = sorted((tmp_path / "out" / "batch_checkpoints").glob("usercf_batch_*.json"))
    assert len(checkpoints) == 3
    assert [read_json(path)["target_user_count"] for path in checkpoints] == [1, 1, 1]
    resource = read_json(tmp_path / "out" / "resource_audit.json")
    assert len(resource["batches"]) == 3
    assert resource["config_caps"]["target_batch_size"] == 1
    assert resource["peak_rss_mb"] >= 0
    assert manifest["peak_rss_mb"] == resource["peak_rss_mb"]


def test_usercf_sidecar_iuf_cosine_downweights_common_overlap_and_records_policy(tmp_path: Path) -> None:
    manifest_path = make_clean_manifest(
        tmp_path,
        [
            {"user_id": "u1", "recent_positive_item_sequence": ["common", "common_2", "rare_a"]},
            {"user_id": "u2", "recent_positive_item_sequence": ["common", "common_2", "hot_candidate"]},
            {"user_id": "u3", "recent_positive_item_sequence": ["rare_a", "rare_candidate"]},
            {"user_id": "u4", "recent_positive_item_sequence": ["common", "filler_1"]},
            {"user_id": "u5", "recent_positive_item_sequence": ["common", "filler_2"]},
            {"user_id": "u6", "recent_positive_item_sequence": ["common_2", "filler_3"]},
        ],
    )
    eligible = make_user_quality_manifest(tmp_path, [profile("u1")])

    cosine = build_for_test(
        manifest_path,
        tmp_path / "cosine",
        eligible_user_quality_manifest=eligible,
        scoring_policy="cosine_overlap",
        target_user_limit=1,
    )
    iuf = build_for_test(
        manifest_path,
        tmp_path / "iuf",
        eligible_user_quality_manifest=eligible,
        scoring_policy="iuf_cosine",
        target_user_limit=1,
    )

    cosine_rows = collect_shard_rows(cosine)
    iuf_rows = collect_shard_rows(iuf)
    assert cosine_rows[0]["candidates"][0]["item_id"] == "hot_candidate"
    assert iuf_rows[0]["candidates"][0]["item_id"] == "rare_candidate"
    assert iuf["scoring_policy"] == "iuf_cosine"
    assert iuf["config_caps"]["scoring_policy"] == "iuf_cosine"
    assert read_json(tmp_path / "iuf" / "resource_audit.json")["config_caps"]["scoring_policy"] == "iuf_cosine"
    assert read_json(tmp_path / "iuf" / "per_source_candidate_manifest.json")["scoring_policy"] == "iuf_cosine"



def test_usercf_sidecar_drops_hot_items_from_similarity_graph_when_keep_hot_false(tmp_path: Path) -> None:
    manifest_path = make_clean_manifest(
        tmp_path,
        [
            {"user_id": "u1", "recent_positive_item_sequence": ["hot", "a"]},
            {"user_id": "u2", "recent_positive_item_sequence": ["hot", "b"]},
            {"user_id": "u3", "recent_positive_item_sequence": ["hot", "c"]},
        ],
    )
    eligible = make_user_quality_manifest(tmp_path, [profile("u1"), profile("u2"), profile("u3")])

    manifest = build_for_test(manifest_path, tmp_path / "out", eligible_user_quality_manifest=eligible, max_item_user_freq=2)

    dropped = read_json(tmp_path / "out" / "dropped_hot_items.json")
    assert dropped["dropped_item_count"] == 1
    assert dropped["items"] == [{"item_id": "hot", "user_freq": 3}]
    assert collect_shard_rows(manifest) == []
    resource_audit = read_json(tmp_path / "out" / "resource_audit.json")
    assert resource_audit["dropped_hot_item_count"] == 1
    assert resource_audit["candidate_total_count"] == 0


def test_usercf_sidecar_item_first_filters_src_users_dst_candidates_and_keeps_hot(tmp_path: Path) -> None:
    manifest_path = make_clean_manifest(
        tmp_path,
        [
            {"user_id": "target", "recent_positive_item_sequence": ["hot", "src", "seen", "rare"]},
            {"user_id": "n1", "recent_positive_item_sequence": ["hot", "src", "seen", "dst"]},
            {"user_id": "n2", "recent_positive_item_sequence": ["hot", "src", "dst", "filler"]},
            {"user_id": "weak", "recent_positive_item_sequence": ["rare", "dst"]},
        ],
    )
    eligible = make_user_quality_manifest(tmp_path, [profile("target"), profile("weak")])

    manifest = build_full_train_usercf_sidecar(
        clean_manifest=manifest_path,
        output_dir=tmp_path / "item_first",
        eligible_user_quality_manifest=eligible,
        max_items_per_user=10,
        max_item_user_freq=2,
        src_min_positive_user_count=2,
        dst_min_positive_user_count=3,
        min_src_filtered_items_per_user=2,
        keep_hot=True,
        similar_users_top_k=3,
        candidate_top_k_per_user=5,
        shard_count=2,
        target_batch_size=2,
        min_free_bytes=0,
        max_rss_mb=4096,
        enforce_venv=False,
    )

    rows_by_user = {row["user_id"]: row for row in collect_shard_rows(manifest)}
    resource = read_json(tmp_path / "item_first" / "resource_audit.json")
    dropped = read_json(tmp_path / "item_first" / "dropped_hot_items.json")
    assert set(rows_by_user) == {"target", "weak"}
    assert [candidate["item_id"] for candidate in rows_by_user["target"]["candidates"]] == ["dst"]
    assert all(candidate["item_id"] != "seen" for candidate in rows_by_user["weak"]["candidates"])
    assert manifest["target_user_count"] == 2
    assert resource["src_min_positive_user_count"] == 2
    assert resource["dst_min_positive_user_count"] == 3
    assert resource["min_src_filtered_items_per_user"] == 2
    assert resource["keep_hot"] is True
    assert resource["hot_item_hard_drop_enabled"] is False
    assert resource["dropped_hot_item_count"] == 0
    assert resource["observed_over_freq_item_count"] == 3
    assert dropped["keep_hot"] is True
    assert dropped["hot_item_hard_drop_enabled"] is False
    assert dropped["dropped_item_count"] == 0
    assert dropped["observed_over_freq_item_count"] == 3


def test_usercf_sidecar_target_user_limit_keeps_diagnostic_scope_bounded(tmp_path: Path) -> None:
    manifest_path = make_clean_manifest(
        tmp_path,
        [
            {"user_id": "target", "recent_positive_item_sequence": ["a", "b"]},
            {"user_id": "neighbor", "recent_positive_item_sequence": ["a", "c"]},
            {"user_id": "unrelated", "recent_positive_item_sequence": ["x", "y"]},
        ],
    )
    eligible = make_user_quality_manifest(tmp_path, [profile("target"), profile("neighbor")])

    manifest = build_for_test(manifest_path, tmp_path / "out", eligible_user_quality_manifest=eligible, target_user_limit=1)

    rows = collect_shard_rows(manifest)
    assert {row["user_id"] for row in rows} == {"target"}
    assert rows[0]["candidates"][0]["item_id"] == "c"
    resource_audit = read_json(tmp_path / "out" / "resource_audit.json")
    assert resource_audit["target_user_limit"] == 1
    assert resource_audit["target_user_count"] == 1
    assert resource_audit["indexed_user_count"] == 2
    readiness = read_json(tmp_path / "out" / "readiness_contract.json")
    assert readiness["status"] == "DIAGNOSTIC_ONLY"
    assert readiness["diagnostic_output_status"] == "DIAGNOSTIC_OUTPUT_READY"
    assert readiness["full_output_status"] == "DIAGNOSTIC_OUTPUT_READY"


def test_usercf_sidecar_writes_deterministic_readiness_contract_without_ready_promotion(tmp_path: Path) -> None:
    manifest_path = make_clean_manifest(
        tmp_path,
        [
            {"user_id": "u1", "recent_positive_item_sequence": ["a", "b"]},
            {"user_id": "u2", "recent_positive_item_sequence": ["a", "c"]},
        ],
    )
    eligible = make_user_quality_manifest(tmp_path, [profile("u1"), profile("u2")])

    manifest = build_for_test(manifest_path, tmp_path / "out", eligible_user_quality_manifest=eligible)
    readiness = read_json(tmp_path / "out" / "readiness_contract.json")
    per_source = read_json(tmp_path / "out" / "per_source_candidate_manifest.json")

    assert readiness["source"] == "usercf_recall"
    assert readiness["status"] == "DIAGNOSTIC_ONLY"
    assert readiness["index_status"] == "INDEX_READY"
    assert readiness["full_output_status"] == "DIAGNOSTIC_OUTPUT_READY"
    assert readiness["promotion_allowed"] is False
    assert readiness["ranking_input_replacement_allowed"] is False
    assert readiness["pool1000_allowed"] is False
    assert readiness["final_pool500_ready_claimed"] is False
    assert readiness["index_manifest_sha256"]
    assert readiness["output_manifest_sha256"]
    assert readiness["per_source_candidate_manifest_sha256"]
    assert readiness["candidate_shards_sha256"]
    assert len(readiness["candidate_shard_signatures"]) == 3
    assert all(signature["sha256"] for signature in readiness["candidate_shard_signatures"])
    assert readiness["runtime_metadata"]["generated_at"] == manifest["generated_at"]
    assert readiness["runtime_metadata"]["runtime_seconds"] == manifest["runtime_seconds"]
    assert per_source["status"] == "DIAGNOSTIC_ONLY"
    assert per_source["alignment_with_ready_source_stoploss_audit"]["ready_sources_reference"] == ["category", "popular", "swing_recall"]


def test_usercf_sidecar_loader_feeds_merge_without_replacing_ranking_input(tmp_path: Path) -> None:
    manifest_path = make_clean_manifest(
        tmp_path,
        [
            {"user_id": "u1", "recent_item_sequence": ["a", "b"], "recent_positive_item_sequence": ["a", "b"]},
            {"user_id": "u2", "recent_item_sequence": ["a", "c"], "recent_positive_item_sequence": ["a", "c"]},
        ],
    )
    eligible = make_user_quality_manifest(tmp_path, [profile("u1"), profile("u2")])

    build_for_test(manifest_path, tmp_path / "out", eligible_user_quality_manifest=eligible)
    usercf = load_usercf_recall_sidecar(tmp_path / "out" / "source_index_manifest.json")
    candidates, fallback_used = merge_for_user(
        {"user_id": "u1", "recent_item_sequence": ["a", "b"], "recent_positive_item_sequence": ["a", "b"]},
        [],
        {},
        {},
        {},
        {},
        {"candidate_pool_size": 5, "usercf_enabled": True, "usercf_per_user": 5},
        usercf_recall=usercf,
    )

    assert fallback_used is False
    assert candidates[0].item_id == "c"
    assert candidates[0].sources == ["usercf_recall"]


@pytest.mark.parametrize(
    ("field", "bad_value", "match"),
    [
        ("source_status", "READY", "DIAGNOSTIC_ONLY"),
        ("candidate_generation_allowed", True, "candidate generation"),
        ("ranking_input_replacement_allowed", True, "ranking input replacement"),
        ("pool1000_allowed", True, "pool1000"),
    ],
)
def test_usercf_sidecar_loader_rejects_manifest_that_violates_runtime_guardrails(tmp_path: Path, field: str, bad_value: object, match: str) -> None:
    manifest_path = make_clean_manifest(
        tmp_path,
        [
            {"user_id": "u1", "recent_positive_item_sequence": ["a", "b"]},
            {"user_id": "u2", "recent_positive_item_sequence": ["a", "c"]},
        ],
    )
    eligible = make_user_quality_manifest(tmp_path, [profile("u1"), profile("u2")])
    build_for_test(manifest_path, tmp_path / "out", eligible_user_quality_manifest=eligible)
    source_manifest_path = tmp_path / "out" / "source_index_manifest.json"
    source_manifest = read_json(source_manifest_path)
    source_manifest[field] = bad_value
    write_json(source_manifest_path, source_manifest)

    with pytest.raises(ValueError, match=match):
        load_usercf_recall_sidecar(source_manifest_path)


def test_usercf_sidecar_loader_accepts_legacy_manifest_without_diagnostic_status_field(tmp_path: Path) -> None:
    manifest_path = make_clean_manifest(
        tmp_path,
        [
            {"user_id": "u1", "recent_positive_item_sequence": ["a", "b"]},
            {"user_id": "u2", "recent_positive_item_sequence": ["a", "c"]},
        ],
    )
    eligible = make_user_quality_manifest(tmp_path, [profile("u1"), profile("u2")])
    build_for_test(manifest_path, tmp_path / "out", eligible_user_quality_manifest=eligible)
    source_manifest_path = tmp_path / "out" / "source_index_manifest.json"
    source_manifest = read_json(source_manifest_path)
    source_manifest.pop("source_status")
    source_manifest.pop("diagnostic_only", None)
    write_json(source_manifest_path, source_manifest)

    usercf = load_usercf_recall_sidecar(source_manifest_path)

    assert set(usercf) == {"u1", "u2"}


def test_usercf_sidecar_writes_contract_manifests_without_holdout_10k_pool1000_or_ranking_replacement(tmp_path: Path) -> None:
    manifest_path = make_clean_manifest(
        tmp_path,
        [
            {"user_id": "u1", "recent_positive_item_sequence": ["a", "b"]},
            {"user_id": "u2", "recent_positive_item_sequence": ["a", "c"]},
        ],
    )
    eligible = make_user_quality_manifest(tmp_path, [profile("u1"), profile("u2")])

    build_for_test(manifest_path, tmp_path / "out", eligible_user_quality_manifest=eligible)

    no_holdout = read_json(tmp_path / "out" / "no_holdout_audit.json")
    selection = read_json(tmp_path / "out" / "custom_index_selection_manifest.json")
    resource = read_json(tmp_path / "out" / "resource_audit.json")
    per_source = read_json(tmp_path / "out" / "per_source_candidate_manifest.json")
    for payload in (no_holdout, selection, resource, per_source):
        assert payload["source"] == "usercf_recall"
        assert payload["index_scope"] == "FULL_DERIVED_INDEX"
        assert payload["train_only"] is True
        assert payload["candidate_generation_allowed"] is False
        assert payload["ranking_input_replacement_allowed"] is False
        assert payload["pool1000_allowed"] is False
    assert no_holdout["read_files"] == [str((manifest_path.parent / "user_sequences.train.jsonl").resolve()), str(eligible.resolve())]
    assert no_holdout["uses_valid"] is False
    assert no_holdout["uses_test"] is False
    assert no_holdout["uses_holdout"] is False
    assert no_holdout["uses_10k"] is False
    assert no_holdout["uses_pool1000"] is False
    assert no_holdout["ranking_input_modified"] is False
    forbidden_names = {Path(path).name for path in no_holdout["forbidden_inputs"]}
    assert {"user_sequences.valid.jsonl", "user_sequences.test.jsonl", "holdout.jsonl"}.issubset(forbidden_names)
    assert selection["eligible_user_policy"] == "heavy_cf_eligible"
    assert selection["eligible_user_quality_summary"]["bucket_counts"] == {"heavy_cf_eligible": 2}


def test_usercf_sidecar_rejects_forbidden_10k_pool1000_and_non_train_paths(tmp_path: Path) -> None:
    clean_10k = tmp_path / "amazon_2023_recall_clean_10000"
    sequence_path = clean_10k / "user_sequences.train.jsonl"
    write_jsonl(sequence_path, [{"user_id": "u1", "recent_positive_item_sequence": ["a"]}])
    manifest_path = clean_10k / "manifest.json"
    write_json(manifest_path, {"train_user_sequences_path": str(sequence_path)})
    with pytest.raises(ValueError, match="Forbidden holdout/10k/pool1000 path"):
        build_for_test(manifest_path, tmp_path / "out_10k")

    clean_dir = tmp_path / "amazon_2023_recall_clean_full"
    bad_train_path = clean_dir / "user_sequences.valid.jsonl"
    write_jsonl(bad_train_path, [{"user_id": "u1", "recent_positive_item_sequence": ["a"]}])
    bad_manifest = clean_dir / "manifest.json"
    write_json(bad_manifest, {"train_user_sequences_path": str(bad_train_path)})
    with pytest.raises(ValueError, match="Forbidden non-train input"):
        build_for_test(bad_manifest, tmp_path / "out_valid")

    good_manifest = make_clean_manifest(tmp_path / "good", [{"user_id": "u1", "recent_positive_item_sequence": ["a"]}])
    with pytest.raises(ValueError, match="Forbidden holdout/10k/pool1000 path"):
        build_for_test(good_manifest, tmp_path / "pool1000" / "out")


def test_usercf_sidecar_rejects_forbidden_target_users_path(tmp_path: Path) -> None:
    clean_manifest = make_clean_manifest(tmp_path / "clean", [{"user_id": "unused", "recent_positive_item_sequence": ["z"]}])
    method_manifest = make_rpa_like_method_dataset_manifest(
        tmp_path,
        [{"user_id": "target", "seed_item_sequence": ["a", "b"], "candidate_generation_allowed": False}],
    )
    target_users_path = tmp_path / "valid" / "target_users.jsonl"
    write_jsonl(target_users_path, [{"user_id": "target"}])

    with pytest.raises(ValueError, match="Forbidden holdout/valid/test/LOPO/oracle/eval path"):
        build_for_test(
            clean_manifest,
            tmp_path / "out",
            method_dataset_manifest=method_manifest,
            target_users_path=target_users_path,
        )


def test_usercf_sidecar_rejects_user_quality_manifest_that_authorizes_generation(tmp_path: Path) -> None:
    manifest_path = make_clean_manifest(tmp_path, [{"user_id": "u1", "recent_positive_item_sequence": ["a", "b"]}])
    eligible = make_user_quality_manifest(tmp_path, [profile("u1")])
    payload = read_json(eligible)
    payload["candidate_generation_allowed"] = True
    write_json(eligible, payload)

    with pytest.raises(ValueError, match="must not authorize candidate generation"):
        build_for_test(manifest_path, tmp_path / "out", eligible_user_quality_manifest=eligible)


def test_usercf_sidecar_supports_overwrite_flag(tmp_path: Path) -> None:
    manifest_path = make_clean_manifest(
        tmp_path,
        [
            {"user_id": "u1", "recent_positive_item_sequence": ["a", "b"]},
            {"user_id": "u2", "recent_positive_item_sequence": ["a", "c"]},
        ],
    )
    eligible = make_user_quality_manifest(tmp_path, [profile("u1"), profile("u2")])
    output_dir = tmp_path / "out"
    build_for_test(manifest_path, output_dir, eligible_user_quality_manifest=eligible)

    with pytest.raises(FileExistsError, match="Output directory already exists"):
        build_for_test(manifest_path, output_dir, eligible_user_quality_manifest=eligible)

    manifest = build_for_test(manifest_path, output_dir, eligible_user_quality_manifest=eligible, overwrite=True)
    assert read_json(output_dir / "source_index_manifest.json") == manifest
