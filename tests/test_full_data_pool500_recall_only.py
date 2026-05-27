from __future__ import annotations

import json
from pathlib import Path

import pytest

from rs_core.common.io import read_json
from rs_core.workflow.full_data_pool500_route_gate import canonical_manifest_sha256, validate_per_source_readiness
from rs_lab.experiments.recall.run_full_data_pool500_recall_only import (
    DEFAULT_SOURCE_MANIFESTS,
    GENERATION_SOURCE_CONFIG,
    _load_batch_semantic_index,
    run_full_data_pool500_recall_only,
)

pytestmark = pytest.mark.unit


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")



def test_load_batch_sequences_prioritizes_source_target_users(tmp_path: Path) -> None:
    from rs_lab.experiments.recall.run_full_data_pool500_recall_only import _load_batch_sequences

    sequence_path = tmp_path / "sequences.jsonl"
    _write_jsonl(
        sequence_path,
        [
            {"user_id": "filler_1"},
            {"user_id": "target_2"},
            {"user_id": "filler_2"},
            {"user_id": "target_1"},
            {"user_id": "filler_3"},
        ],
    )

    sequences = _load_batch_sequences(sequence_path, limit_users=4, priority_user_ids=["target_1", "target_2"])

    assert [sequence["user_id"] for sequence in sequences] == ["target_1", "target_2", "filler_1", "filler_2"]



def test_load_batch_sequences_caps_priority_users_by_limit(tmp_path: Path) -> None:
    from rs_lab.experiments.recall.run_full_data_pool500_recall_only import _load_batch_sequences

    sequence_path = tmp_path / "sequences.jsonl"
    _write_jsonl(
        sequence_path,
        [
            {"user_id": "target_1"},
            {"user_id": "target_2"},
            {"user_id": "target_3"},
            {"user_id": "filler_1"},
        ],
    )

    sequences = _load_batch_sequences(sequence_path, limit_users=2, priority_user_ids=["target_1", "target_2", "target_3"])

    assert [sequence["user_id"] for sequence in sequences] == ["target_1", "target_2"]



def test_recall_runner_has_no_profile_or_target_user_runtime_overrides() -> None:
    source_path = Path("D:/sinrotic_code/python_project/summer/RS_agent/rs_lab/experiments/recall/run_full_data_pool500_recall_only.py")
    source = source_path.read_text(encoding="utf-8")

    assert "--recall-profile" not in source
    assert "DEFAULT_RECALL_PROFILE" not in source
    assert "POOL500_VNEXT_RECALL_PROFILE" not in source
    assert "target_user_manifest" not in source
    assert "target-user-manifest" not in source



def test_source_budget_contract_uses_default_generation_config_only() -> None:
    from rs_lab.experiments.recall.run_full_data_pool500_recall_only import _source_budget_contract

    config = {"candidate_pool_size": 500, "candidate_fill_order": ["itemcf", "popular"]}

    contract = _source_budget_contract(
        {"train_user_sequences_path": "train_sequences.jsonl", "split_paths": {"train": "train.jsonl"}},
        {"outputs": {"popular_recall": "popular.jsonl"}},
        limit_users=10,
        full_run=False,
        generation_config=config,
    )

    assert "recall_profile" not in contract
    assert contract["candidate_pool_size"] == 500
    assert contract["candidate_fill_order"] == ["itemcf", "popular"]



def test_primary_source_uses_active_fill_order() -> None:
    from rs_lab.experiments.recall.run_full_data_pool500_recall_only import _primary_source

    assert (
        _primary_source(
            ["semantic_title_category_expansion", "co_visit_fallback_repair"],
            ["co_visit_fallback_repair", "semantic_title_category_expansion"],
        )
        == "co_visit_fallback_repair"
    )
    assert _primary_source(["itemcf_weak", "popular"], ["itemcf", "popular"]) == "itemcf_weak"



def test_load_source_itemcf_accepts_sharded_source_manifest_with_allowed_seeds(tmp_path: Path) -> None:
    from rs_lab.experiments.recall.pool500.method_dataset_to_itemcf_source import build_itemcf_source_from_method_dataset
    from rs_lab.experiments.recall.run_full_data_pool500_recall_only import _load_source_itemcf

    input_dir = tmp_path / "formal_method_dataset"
    input_dir.mkdir()
    _write_jsonl(
        input_dir / "method_dataset_rows.jsonl",
        [
            {"src_item_id": "seed-a", "dst_item_id": "cand-a", "itemcf_score": 0.9},
            {"src_item_id": "seed-z", "dst_item_id": "cand-z", "itemcf_score": 0.8},
        ],
    )
    manifest_path = input_dir / "method_dataset_manifest.json"
    manifest_path.write_text(json.dumps({"source": "itemcf_weak", "train_only": True}, ensure_ascii=False), encoding="utf-8")
    manifest = build_itemcf_source_from_method_dataset(
        source="itemcf_weak",
        method_dataset_manifest_path=manifest_path,
        output_root=tmp_path / "sources",
        run_id="sharded_unit",
        shard_count=4,
        enforce_venv=False,
    )
    source_manifest_path = Path(manifest["outputs"]["source_index_manifest"])
    artifact = {"path": source_manifest_path, "manifest": read_json(source_manifest_path)}

    loaded = _load_source_itemcf(artifact, None, "itemcf_weak", {"seed-a"})

    assert sorted(loaded) == ["seed-a"]
    assert loaded["seed-a"][0].item_id == "cand-a"



def test_main_route_defaults_use_local_formal_pool500_source_indexes() -> None:
    expected_suffixes = {
        "semantic": "outputs/recall/pool500_method_sources/semantic/local_formal_semantic_20260525/source_index_manifest.json",
        "semantic_title_category_expansion": "outputs/recall/pool500_method_sources/semantic_title_category_expansion/local_formal_semantic_title_category_20260525/source_index_manifest.json",
        "co_visit_fallback_repair": "outputs/recall/pool500_method_sources/co_visit_fallback_repair/local_formal_co_visit_repair_20260525/source_index_manifest.json",
        "usercf_recall": "outputs/recall/pool500_usercf_method_train/usercf_recall/usercf_v1_formal_route_ready/source_index_manifest.json",
        "swing_recall": "outputs/recall/pool500_method_sources/swing_recall/local_formal_swing_recall_20260525/source_index_manifest.json",
        "itemcf_strong": "outputs/recall/pool500_method_sources/itemcf_strong_relaxed_seedsrc_v3_from_method_dataset/itemcf_strong/formal_sharded/source_index_manifest.json",
        "two_tower": "outputs/recall/pool500_full_sources/two_tower/index/source_index_manifest.json",
    }

    for source, expected_suffix in expected_suffixes.items():
        assert DEFAULT_SOURCE_MANIFESTS[source].as_posix().endswith(expected_suffix)
    assert GENERATION_SOURCE_CONFIG["candidate_fill_order"] == [
        "two_tower",
        "itemcf_strong",
        "swing_recall",
        "usercf_recall",
        "co_visit_fallback_repair",
        "itemcf_weak",
        "semantic_title_category_expansion",
        "semantic",
        "category",
        "popular",
    ]
    assert GENERATION_SOURCE_CONFIG["candidate_source_minimums"] == {
        "two_tower": 80,
        "itemcf_strong": 45,
        "itemcf_weak": 15,
        "swing_recall": 40,
        "co_visit_fallback_repair": 40,
        "semantic_title_category_expansion": 30,
    }
    assert GENERATION_SOURCE_CONFIG["candidate_source_maximums"] == {"category": 150, "popular": 80, "usercf_recall": 10}
    assert "semantic" in GENERATION_SOURCE_CONFIG["candidate_fill_order"]
    assert "semantic" not in GENERATION_SOURCE_CONFIG["candidate_source_minimums"]



def test_load_batch_semantic_index_keeps_seed_and_matching_candidates(tmp_path: Path) -> None:
    semantic_path = tmp_path / "semantic.jsonl"
    _write_jsonl(
        semantic_path,
        [
            {"parent_asin": "candidate_before_seed", "title_clean": "wireless gaming mouse", "main_category": "Electronics"},
            {"parent_asin": "unrelated", "title_clean": "ceramic bowl", "main_category": "Home"},
            {"parent_asin": "seed", "title_clean": "gaming keyboard", "main_category": "Electronics"},
            {"parent_asin": "candidate_after_seed", "title_clean": "keyboard wrist rest", "main_category": "Office"},
        ],
    )
    sequences = [{"user_id": "u1", "recent_positive_item_sequence": ["seed"]}]

    index = _load_batch_semantic_index(semantic_path, sequences, max_rows=10)

    assert set(index) == {"seed", "candidate_before_seed", "candidate_after_seed"}
    assert "semantic_tokens" in index["seed"]


def test_load_batch_semantic_index_respects_candidate_limit(tmp_path: Path) -> None:
    semantic_path = tmp_path / "semantic.jsonl"
    _write_jsonl(
        semantic_path,
        [
            {"parent_asin": "seed", "title_clean": "camera lens", "main_category": "Electronics"},
            {"parent_asin": "candidate_1", "title_clean": "camera tripod", "main_category": "Electronics"},
            {"parent_asin": "candidate_2", "title_clean": "camera bag", "main_category": "Electronics"},
        ],
    )
    sequences = [{"user_id": "u1", "recent_positive_item_sequence": ["seed"]}]

    index = _load_batch_semantic_index(semantic_path, sequences, max_rows=1)

    assert set(index) == {"seed", "candidate_1"}


def test_vector_two_tower_batch_uses_realtime_history_for_all_users(tmp_path: Path) -> None:
    from rs_core.recsys.vector_index import load_vector_index_artifact
    from rs_lab.experiments.recall.run_full_data_pool500_recall_only import _precompute_two_tower_recall

    artifact = _write_two_tower_artifact(tmp_path / "two_tower_artifact")
    index = load_vector_index_artifact(artifact)
    assert index.model_metadata["model_parameters"]["user_tower.0.weight"] == [[1.0, 0.0], [0.0, 1.0]]
    sequences = [
        {"user_id": "known", "recent_item_sequence": ["seed"], "recent_positive_item_sequence": ["seed"]},
        {"user_id": "missing", "recent_item_sequence": ["seed"], "recent_positive_item_sequence": ["seed"]},
    ]

    recall = _precompute_two_tower_recall(sequences, index, {"two_tower_enabled": True, "two_tower_per_user": 1})

    assert {row.item_id for row in recall["known"]} == {"seed_match"}
    assert {row.item_id for row in recall["missing"]} == {"seed_match"}


def test_vector_index_search_many_limits_zero_score_ties() -> None:
    from rs_core.recsys.vector_index import VectorIndex

    index = VectorIndex(
        items={
            f"zero_{idx}": {"embedding": [0.0, 1.0]}
            for idx in range(200)
        }
        | {"match": {"embedding": [1.0, 0.0]}},
    )

    results = index.search_many({"u1": [1.0, 0.0]}, limit=3, item_block_size=50)

    assert [result.item_id for result in results["u1"]] == ["match"]
    assert all(result.score > 0.0 for result in results["u1"])



def test_vector_index_search_many_without_numpy_keeps_empty_query_key(monkeypatch: pytest.MonkeyPatch) -> None:
    import rs_core.recsys.vector_index as vector_index_module
    from rs_core.recsys.vector_index import VectorIndex

    index = VectorIndex(items={"match": {"embedding": [1.0, 0.0]}})
    monkeypatch.setattr(vector_index_module, "np", None)

    results = index.search_many({"empty": [], "u1": [1.0, 0.0]}, limit=1)

    assert results["empty"] == []
    assert [result.item_id for result in results["u1"]] == ["match"]



def test_generation_overrides_from_source_manifests_are_applied(tmp_path: Path) -> None:
    from rs_lab.experiments.recall.run_full_data_pool500_recall_only import _apply_source_generation_overrides

    source_manifests = _write_source_artifacts(tmp_path)
    payload = read_json(source_manifests["usercf_recall"])
    payload["generation_config_overrides"] = {"usercf_per_user": 120, "pool1000_allowed": 1000}
    source_manifests["usercf_recall"].write_text(json.dumps(payload), encoding="utf-8")
    artifacts = {source: {"path": path, "manifest": read_json(path)} for source, path in source_manifests.items()}
    config = {"usercf_per_user": 30}

    _apply_source_generation_overrides(config, artifacts)

    assert config["usercf_per_user"] == 120
    assert "pool1000_allowed" not in config


def test_usercf_sidecar_loader_accepts_flat_candidate_shards(tmp_path: Path) -> None:
    from rs_core.recsys.candidate_merge import load_usercf_recall_sidecar

    empty_shard = tmp_path / "empty_usercf.jsonl"
    empty_shard.write_text("", encoding="utf-8")
    shard = tmp_path / "flat_usercf.jsonl"
    _write_jsonl(
        shard,
        [
            {"user_id": "u1", "item_id": "i1", "score": 1.0, "rank": 1, "source": "usercf_recall"},
            {"user_id": "u1", "parent_asin": "i2", "score": 0.5, "rank": 2, "canonical_source": "usercf_recall"},
            {"user_id": "u2", "item_id": "i3", "score": 0.75, "rank": 1, "source": "usercf_recall"},
        ],
    )
    manifest = {
        "source": "usercf_recall",
        "source_status": "DIAGNOSTIC_ONLY",
        "diagnostic_only": True,
        "index_scope": "FULL_DERIVED_INDEX",
        "train_only": True,
        "candidate_generation_allowed": False,
        "ranking_input_replacement_allowed": False,
        "ranking_replacement_allowed": False,
        "pool1000_allowed": False,
        "promotion_allowed": False,
        "final_pool500_ready_claimed": False,
        "outputs": {"candidate_shards": [str(empty_shard), str(shard)]},
    }
    manifest_path = tmp_path / "source_index_manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    by_user = load_usercf_recall_sidecar(manifest_path)

    assert [candidate.item_id for candidate in by_user["u1"]] == ["i1", "i2"]
    assert [candidate.item_id for candidate in by_user["u2"]] == ["i3"]
    assert all(candidate.source == "usercf_recall" for rows in by_user.values() for candidate in rows)


def test_semantic_no_holdout_audit_blocks_forbidden_scopes(tmp_path: Path) -> None:
    clean_manifest = _write_clean_manifest(tmp_path)
    views_manifest = _write_views_manifest(tmp_path)
    source_manifests = _write_source_artifacts(tmp_path)
    forbidden_semantic = tmp_path / "LOPO" / "semantic_recall_inputs.jsonl"
    forbidden_semantic.parent.mkdir()
    _write_jsonl(forbidden_semantic, [{"parent_asin": "seed", "title_clean": "gaming mouse", "main_category": "Electronics"}])
    payload = read_json(source_manifests["semantic_title_category_expansion"])
    payload["semantic_recall_inputs_path"] = str(forbidden_semantic)
    source_manifests["semantic_title_category_expansion"].write_text(json.dumps(payload), encoding="utf-8")

    manifest = run_full_data_pool500_recall_only(
        clean_manifest_path=clean_manifest,
        lightweight_views_manifest_path=views_manifest,
        output_dir=tmp_path / "out_forbidden",
        usercf_sidecar_manifest_path=source_manifests["usercf_recall"],
        source_manifest_paths=source_manifests,
        limit_users=1,
        enable_semantic=True,
        semantic_max_rows=20,
        overwrite=True,
        enforce_venv=False,
    )

    audit = read_json(Path(manifest["required_artifacts"]["semantic_no_holdout_audit"]))
    assert audit["status"] == "BLOCKED"
    assert audit["promotion_allowed"] is False
    assert audit["ranking_input_replacement_allowed"] is False
    assert audit["pool1000_allowed"] is False
    assert audit["forbidden_inputs"] == [str(forbidden_semantic)]


def test_recall_layer_shadow_audit_covers_sources_without_runtime_ready_claims(tmp_path: Path) -> None:
    from rs_lab.experiments.recall.validate_pool500_recall_layer_shadow_audit import build_recall_layer_shadow_audit

    views_manifest = _write_views_manifest(tmp_path)
    source_manifests = _write_source_artifacts(tmp_path)
    co_visit_dir = tmp_path / "sources" / "co_visit_fallback_repair"
    _write_pair_source(co_visit_dir, "co_visit_fallback_repair", "seed", "covisit_1")
    source_manifests["co_visit_fallback_repair"] = co_visit_dir / "source_index_manifest.json"
    itemcf_payload = read_json(source_manifests["itemcf_weak"])
    itemcf_payload["method_dataset_manifest"] = {
        "input_features": ["recent_positive_item_sequence"],
        "output_path": str(tmp_path / "method_dataset" / "itemcf_weak.jsonl"),
    }
    source_manifests["itemcf_weak"].write_text(json.dumps(itemcf_payload), encoding="utf-8")

    audit = build_recall_layer_shadow_audit(
        lightweight_views_manifest_path=views_manifest,
        source_manifest_paths=source_manifests,
        usercf_sidecar_manifest_path=source_manifests["usercf_recall"],
    )

    assert set(audit["sources"]) == {
        "itemcf_weak",
        "itemcf_strong",
        "usercf_recall",
        "swing_recall",
        "semantic",
        "semantic_title_category_expansion",
        "co_visit_fallback_repair",
        "two_tower",
        "popular",
        "category",
    }
    assert audit["runtime_gate"] is False
    assert audit["candidate_generation_changed"] is False
    assert audit["sources"]["popular"]["qualification"]["fallback_view_source"] is True
    assert audit["sources"]["category"]["manifest_path"] == str(views_manifest)
    assert audit["sources"]["itemcf_weak"]["legacy_state"] == {"legacy_or_custom": True, "allowed": True}
    assert audit["sources"]["itemcf_weak"]["forbidden_scan"]["matches"] == []
    serialized = json.dumps(audit, ensure_ascii=False)
    assert "READY" not in serialized
    assert "promotion" not in serialized.lower()



def test_recall_layer_shadow_audit_blocks_eval_label_leakage(tmp_path: Path) -> None:
    from rs_lab.experiments.recall.validate_pool500_recall_layer_shadow_audit import build_recall_layer_shadow_audit

    views_manifest = _write_views_manifest(tmp_path)
    source_manifests = _write_source_artifacts(tmp_path)
    payload = read_json(source_manifests["itemcf_strong"])
    payload["method_dataset_manifest"] = {
        "label_artifact_path": "eval_diagnostic/labels.json",
        "recent_positive_item_sequence": ["allowed_train_seed"],
    }
    source_manifests["itemcf_strong"].write_text(json.dumps(payload), encoding="utf-8")

    audit = build_recall_layer_shadow_audit(
        lightweight_views_manifest_path=views_manifest,
        source_manifest_paths=source_manifests,
        usercf_sidecar_manifest_path=source_manifests["usercf_recall"],
    )

    source_audit = audit["sources"]["itemcf_strong"]
    assert source_audit["status"] == "AUDIT_BLOCKED"
    assert {blocker["code"] for blocker in source_audit["blockers"]} >= {"FORBIDDEN_EVAL_DIAGNOSTIC_LEAKAGE"}
    assert {match["kind"] for match in source_audit["forbidden_scan"]["matches"]} == {"field", "path"}



def test_recall_layer_shadow_audit_surfaces_two_tower_validator_mismatch(tmp_path: Path) -> None:
    from rs_lab.experiments.recall.validate_pool500_recall_layer_shadow_audit import build_recall_layer_shadow_audit

    views_manifest = _write_views_manifest(tmp_path)
    source_manifests = _write_source_artifacts(tmp_path)
    payload = read_json(source_manifests["two_tower"])
    payload["embedding_row_count"] = 2
    source_manifests["two_tower"].write_text(json.dumps(payload), encoding="utf-8")

    audit = build_recall_layer_shadow_audit(
        lightweight_views_manifest_path=views_manifest,
        source_manifest_paths=source_manifests,
        usercf_sidecar_manifest_path=source_manifests["usercf_recall"],
    )

    two_tower_audit = audit["sources"]["two_tower"]
    assert two_tower_audit["status"] == "AUDIT_BLOCKED"
    assert two_tower_audit["qualification"]["strict_validator"] == "two_tower_source_index_v1"
    assert any(blocker["code"] == "TWO_TOWER_SOURCE_MANIFEST_INVALID" for blocker in two_tower_audit["blockers"])



def test_recall_only_runner_loads_source_artifacts_and_writes_contracts(tmp_path: Path) -> None:
    clean_manifest = _write_clean_manifest(tmp_path)
    views_manifest = _write_views_manifest(tmp_path)
    source_manifests = _write_source_artifacts(tmp_path)
    output_dir = tmp_path / "out"

    manifest = run_full_data_pool500_recall_only(
        clean_manifest_path=clean_manifest,
        lightweight_views_manifest_path=views_manifest,
        output_dir=output_dir,
        usercf_sidecar_manifest_path=source_manifests["usercf_recall"],
        source_manifest_paths=source_manifests,
        limit_users=1,
        enable_semantic=True,
        semantic_max_rows=20,
        overwrite=True,
        enforce_venv=False,
    )

    rows = [json.loads(line) for line in (output_dir / "pool500_candidates.jsonl").read_text(encoding="utf-8").splitlines()]
    row_sources = {source for row in rows for source in row["sources"]}
    assert row_sources >= {
        "semantic",
        "semantic_title_category_expansion",
        "two_tower",
        "co_visit_fallback_repair",
        "usercf_recall",
        "swing_recall",
        "itemcf_weak",
        "itemcf_strong",
        "category",
        "popular",
    }
    readiness = read_json(output_dir / "per_source_readiness_contracts.json")
    index_manifests = read_json(output_dir / "full_derived_index_manifests.json")
    stoploss_audit = read_json(output_dir / "ready_source_stoploss_audit.json")
    diagnostic_contribution = read_json(output_dir / "diagnostic_source_contribution.json")
    semantic_input_manifest = read_json(output_dir / "semantic_input_manifest.json")
    canonical_semantic_source_manifest = read_json(output_dir / "sources" / "semantic" / "manifest.json")
    semantic_source_manifest = read_json(output_dir / "sources" / "semantic_title_category_expansion" / "manifest.json")
    covisit_source_manifest = read_json(output_dir / "sources" / "co_visit_fallback_repair" / "manifest.json")
    diagnostic_candidate_manifest = read_json(output_dir / "diagnostic_candidate_manifest.json")
    semantic_no_holdout_audit = read_json(output_dir / "semantic_no_holdout_audit.json")
    semantic_resource_audit = read_json(output_dir / "semantic_resource_audit.json")
    fallback_completion_audit = read_json(output_dir / "fallback_completion_audit.json")
    fallback_completion_validation = read_json(output_dir / "fallback_completion_validation.json")
    fallback_completion_resource_audit = read_json(output_dir / "fallback_completion_resource_audit.json")
    final_merge_manifest = read_json(output_dir / "final_merge_manifest.json")
    underfill_audit = read_json(output_dir / "underfill_audit.json")
    source_contribution_audit = read_json(output_dir / "source_contribution_audit.json")
    source_overlap_audit = read_json(output_dir / "source_overlap_audit.json")
    final_resource_audit = read_json(output_dir / "final_resource_audit.json")
    final_readiness_contract = read_json(output_dir / "final_readiness_contract.json")
    assert readiness["swing_recall"]["source_index_manifest_path"] == str(source_manifests["swing_recall"])
    assert readiness["two_tower"]["canonical_source"] == "two_tower"
    assert index_manifests["itemcf_weak"]["index_scope"] == "FULL_DERIVED_INDEX"
    assert index_manifests["two_tower"]["source"] == "two_tower"
    assert index_manifests["two_tower"]["index_path"] == read_json(source_manifests["two_tower"])["index_path"]
    assert index_manifests["two_tower"]["ranking_replacement_allowed"] is False
    assert manifest["ranking_input_replacement_allowed"] is False
    assert manifest["ranking_replacement_allowed"] is False
    assert manifest["promotion_allowed"] is False
    assert manifest["pool1000_allowed"] is False
    assert manifest["required_artifacts"]["ready_source_stoploss_audit"] == str(output_dir / "ready_source_stoploss_audit.json")
    assert manifest["required_artifacts"]["diagnostic_source_contribution"] == str(output_dir / "diagnostic_source_contribution.json")
    assert manifest["required_artifacts"]["semantic_input_manifest"] == str(output_dir / "semantic_input_manifest.json")
    assert manifest["required_artifacts"]["diagnostic_candidate_manifest"] == str(output_dir / "diagnostic_candidate_manifest.json")
    assert manifest["required_artifacts"]["semantic_no_holdout_audit"] == str(output_dir / "semantic_no_holdout_audit.json")
    assert manifest["required_artifacts"]["semantic_resource_audit"] == str(output_dir / "semantic_resource_audit.json")
    assert manifest["required_artifacts"]["fallback_completion_audit"] == str(output_dir / "fallback_completion_audit.json")
    assert manifest["required_artifacts"]["fallback_completion_validation"] == str(output_dir / "fallback_completion_validation.json")
    assert manifest["required_artifacts"]["fallback_completion_resource_audit"] == str(output_dir / "fallback_completion_resource_audit.json")
    assert manifest["required_artifacts"]["final_merge_manifest"] == str(output_dir / "final_merge_manifest.json")
    assert manifest["required_artifacts"]["underfill_audit"] == str(output_dir / "underfill_audit.json")
    assert manifest["required_artifacts"]["source_contribution_audit"] == str(output_dir / "source_contribution_audit.json")
    assert manifest["required_artifacts"]["source_overlap_audit"] == str(output_dir / "source_overlap_audit.json")
    assert manifest["required_artifacts"]["final_resource_audit"] == str(output_dir / "final_resource_audit.json")
    assert manifest["required_artifacts"]["final_readiness_contract"] == str(output_dir / "final_readiness_contract.json")
    assert manifest["ready_source_stoploss_audit"]["audit_path"] == str(output_dir / "ready_source_stoploss_audit.json")
    assert manifest["diagnostic_source_contribution"]["audit_path"] == str(output_dir / "diagnostic_source_contribution.json")
    assert set(stoploss_audit["ready_sources"]) == {"category", "popular", "swing_recall", "usercf_recall"}
    assert set(stoploss_audit["sources"]) == {"category", "popular", "swing_recall", "usercf_recall"}
    assert "semantic_title_category_expansion" not in stoploss_audit["ready_sources"]
    assert "two_tower" not in stoploss_audit["ready_sources"]
    assert stoploss_audit["diagnostic_only_promotion_allowed"] is False
    assert stoploss_audit["ranking_input_replacement_allowed"] is False
    assert manifest["ranking_input_replacement_allowed"] is False
    assert stoploss_audit["pool1000_allowed"] is False
    assert readiness["semantic"]["status"] == "BATCH_SCOPED_DIAGNOSTIC"
    assert readiness["semantic"]["canonical_source"] == "semantic"
    assert readiness["semantic_title_category_expansion"]["status"] == "BATCH_SCOPED_DIAGNOSTIC"
    assert readiness["co_visit_fallback_repair"]["status"] == "BATCH_SCOPED_DIAGNOSTIC"
    assert readiness["co_visit_fallback_repair"]["status"] != "READY"
    assert readiness["co_visit_fallback_repair"]["algorithm_scope"] == "train_transition_metadata_repair_v0"
    assert readiness["co_visit_fallback_repair"]["complete_co_visit_graph_claimed"] is False
    assert index_manifests["semantic"]["status"] == "BATCH_SCOPED_DIAGNOSTIC"
    assert index_manifests["semantic"]["canonical_source"] == "semantic"
    assert index_manifests["semantic_title_category_expansion"]["status"] == "BATCH_SCOPED_DIAGNOSTIC"
    assert index_manifests["co_visit_fallback_repair"]["status"] == "BATCH_SCOPED_DIAGNOSTIC"
    assert index_manifests["co_visit_fallback_repair"]["algorithm_scope"] == "train_transition_metadata_repair_v0"
    assert index_manifests["co_visit_fallback_repair"]["complete_co_visit_graph_claimed"] is False
    assert canonical_semantic_source_manifest["status"] == "BATCH_SCOPED_DIAGNOSTIC"
    assert canonical_semantic_source_manifest["final_sources"] == []
    assert canonical_semantic_source_manifest["batch_scoped_evidence_only"] is True
    assert canonical_semantic_source_manifest["manifest_sha256"] == canonical_manifest_sha256({"source": "semantic", "ready": False})
    assert semantic_source_manifest["status"] == "BATCH_SCOPED_DIAGNOSTIC"
    assert semantic_source_manifest["final_sources"] == []
    assert semantic_source_manifest["batch_scoped_evidence_only"] is True
    assert semantic_source_manifest["manifest_sha256"] == canonical_manifest_sha256({"source": "semantic_title_category_expansion", "ready": False})
    assert covisit_source_manifest["status"] == "BATCH_SCOPED_DIAGNOSTIC"
    assert covisit_source_manifest["final_sources"] == []
    assert covisit_source_manifest["batch_scoped_evidence_only"] is True
    assert covisit_source_manifest["manifest_sha256"] == canonical_manifest_sha256({"source": "co_visit_fallback_repair", "ready": False})
    assert semantic_input_manifest["status"] == "BATCH_SCOPED_DIAGNOSTIC"
    assert semantic_input_manifest["readiness_status"] == "DEFERRED"
    assert semantic_input_manifest["title_coverage"] == {"count": 3, "total": 3, "ratio": 1.0}
    assert semantic_input_manifest["category_coverage"] == {"count": 3, "total": 3, "ratio": 1.0}
    assert semantic_input_manifest["clean_title_token_coverage"] == {"count": 3, "total": 3, "ratio": 1.0}
    assert semantic_input_manifest["item_universe_coverage"] == {"count": 1, "total": 1, "ratio": 1.0}
    assert diagnostic_candidate_manifest["candidate_generation_count"] > 0
    assert diagnostic_candidate_manifest["unique_generated_candidate_count"] > 0
    assert diagnostic_candidate_manifest["duplicate_removal_count"] >= 0
    assert diagnostic_candidate_manifest["underfill_improved_user_count"] >= 0
    assert diagnostic_candidate_manifest["marginal_contribution_count"] > 0
    assert diagnostic_candidate_manifest["promotion_allowed"] is False
    assert diagnostic_candidate_manifest["ranking_input_replacement_allowed"] is False
    assert diagnostic_candidate_manifest["pool1000_allowed"] is False
    assert semantic_no_holdout_audit["status"] == "PASS"
    assert semantic_no_holdout_audit["forbidden_inputs"] == []
    assert semantic_resource_audit["mode"] == "small_batch_diagnostic"
    assert semantic_resource_audit["heavy_job"] is False
    assert semantic_resource_audit["full_run_claimed"] is False
    assert fallback_completion_validation["valid"] is True
    assert fallback_completion_resource_audit["heavy_job"] is False
    assert manifest["fallback_completion"]["enabled"] is True
    assert manifest["fallback_completion"]["promotion_allowed"] is False
    assert manifest["fallback_completion"]["ranking_input_replacement_allowed"] is False
    assert manifest["fallback_completion"]["pool1000_allowed"] is False
    assert manifest["fallback_completion"]["full_pool500_ready_declared"] is False
    assert fallback_completion_audit["config"]["promotion_allowed"] is False
    assert fallback_completion_audit["global"]["users_with_target_candidates"] == 1
    assert fallback_completion_audit["global"]["underfilled_user_count"] == 0
    assert {diagnostic["code"] for diagnostic in manifest["diagnostics"]} >= {"POOL500_FALLBACK_COMPLETION_SHADOW_ONLY"}
    assert not any(source.startswith("fallback_") for source in row_sources)
    assert final_merge_manifest["final_pool500_ready_claimed"] is False
    assert final_merge_manifest["ranking_input_replacement_allowed"] is False
    assert underfill_audit["target_user_count"] == 1
    assert underfill_audit["remaining_underfilled_user_count"] >= 0
    assert underfill_audit["ranking_input_replacement_allowed"] is False
    assert set(source_contribution_audit["ready_sources"]) == {"category", "popular", "swing_recall", "usercf_recall"}
    assert set(source_contribution_audit["diagnostic_sources"]) == {"itemcf_weak", "itemcf_strong"}
    assert source_contribution_audit["sources"]["usercf_recall"]["readiness_status"] == "READY"
    assert source_contribution_audit["promotion_allowed"] is False
    assert source_overlap_audit["status"] == "DIAGNOSTIC_ONLY_AUDIT"
    assert source_overlap_audit["ranking_input_replacement_allowed"] is False
    assert final_resource_audit["status"] == "PASS"
    assert final_resource_audit["resource_guard_required"] is True
    assert final_readiness_contract["final_pool500_ready_claimed"] is False
    registry_audit = validate_per_source_readiness(readiness, {"required_sources": sorted(readiness)})
    assert all(blocker["code"] != "UNKNOWN_READINESS_STATUS" for blocker in registry_audit["blockers"])
    assert "semantic" not in registry_audit["ready_sources"]
    assert "semantic_title_category_expansion" not in registry_audit["ready_sources"]
    assert "co_visit_fallback_repair" not in registry_audit["ready_sources"]
    assert final_readiness_contract["ranking_input_replacement_allowed"] is False
    assert final_readiness_contract["pool1000_allowed"] is False
    assert diagnostic_contribution["status"] == "DIAGNOSTIC_ONLY_AUDIT"
    assert set(diagnostic_contribution["diagnostic_sources"]) == {"itemcf_weak", "itemcf_strong"}
    assert diagnostic_contribution["promotion_allowed"] is False
    assert diagnostic_contribution["ranking_input_replacement_allowed"] is False
    assert diagnostic_contribution["pool1000_allowed"] is False
    assert diagnostic_contribution["diagnostic_row_total"] > 0
    assert "usercf_recall" not in diagnostic_contribution["sources"]
    assert diagnostic_contribution["sources"]["itemcf_weak"]["marginal_candidate_share"] > 0
    assert diagnostic_contribution["sources"]["itemcf_strong"]["marginal_candidate_share"] > 0
    assert stoploss_audit["candidate_row_count"] < 1000
    assert stoploss_audit["sources"]["category"]["underfilled_user_coverage_count"] >= 0
    assert stoploss_audit["sources"]["popular"]["unique_item_count"] >= 0
    assert stoploss_audit["sources"]["swing_recall"]["marginal_candidate_share"] > 0


def _write_clean_manifest(tmp_path: Path) -> Path:
    clean_dir = tmp_path / "clean"
    clean_dir.mkdir()
    sequences = clean_dir / "user_sequences.train.jsonl"
    _write_jsonl(
        sequences,
        [
            {"user_id": "u1", "recent_item_sequence": ["seed"], "recent_positive_item_sequence": ["seed"], "recent_strong_positive_item_sequence": ["strong_seed"]},
            {"user_id": "u2", "recent_item_sequence": ["seed2"], "recent_positive_item_sequence": ["seed2"], "recent_strong_positive_item_sequence": ["strong_seed2"]},
        ],
    )
    train = clean_dir / "canonical_interactions.train.jsonl"
    _write_jsonl(train, [{"user_id": "u1", "parent_asin": "seed"}, {"user_id": "u2", "parent_asin": "seed2"}])
    items = clean_dir / "canonical_items.jsonl"
    _write_jsonl(
        items,
        [
            {"parent_asin": "seed", "title_clean": "gaming mouse", "main_category": "Electronics", "brand": "Acme"},
            {"parent_asin": "seed2", "title_clean": "office keyboard", "main_category": "Office", "brand": "Acme"},
        ],
    )
    manifest = clean_dir / "manifest.json"
    manifest.write_text(
        json.dumps({"schema_version": "test", "train_user_sequences_path": str(sequences), "canonical_items_path": str(items), "split_paths": {"train": str(train)}}),
        encoding="utf-8",
    )
    return manifest


def _write_views_manifest(tmp_path: Path) -> Path:
    views = tmp_path / "views"
    views.mkdir()
    popular = views / "popular_recall.jsonl"
    _write_jsonl(
        popular,
        [{"parent_asin": f"popular_{idx}", "pop_score": 1.0 / (idx + 1), "category": f"Popular{idx % 8}"} for idx in range(560)],
    )
    category_items = views / "category_recall_items.jsonl"
    _write_jsonl(
        category_items,
        [
            {"parent_asin": "seed", "main_category": "Electronics", "brand": "Acme"},
            {"parent_asin": "strong_seed", "main_category": "Electronics", "brand": "Acme"},
            *[{"parent_asin": f"category_{idx}", "main_category": "Electronics", "brand": "Acme", "score": 1.0 / (idx + 1)} for idx in range(260)],
        ],
    )
    category_top = views / "category_top_items.jsonl"
    _write_jsonl(
        category_top,
        [{"bucket": "main::Electronics", "top_items": [{"parent_asin": f"category_top_{idx}", "score": 1.0 / (idx + 1)} for idx in range(220)]}],
    )
    semantic = views / "semantic_recall_inputs.jsonl"
    _write_jsonl(
        semantic,
        [
            {"parent_asin": "seed", "title_clean": "gaming mouse", "main_category": "Electronics"},
            *[{"parent_asin": f"semantic_{idx}", "title_clean": "gaming keyboard", "main_category": "Electronics"} for idx in range(220)],
            {"parent_asin": "covisit_1", "title_clean": "ergonomic mouse pad", "main_category": "Electronics"},
        ],
    )
    manifest = views / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "source_clean_dir": str(tmp_path / "clean"),
                "outputs": {
                    "popular_recall": str(popular),
                    "category_recall_items": str(category_items),
                    "category_top_items": str(category_top),
                    "semantic_recall_inputs": str(semantic),
                },
            }
        ),
        encoding="utf-8",
    )
    return manifest


def _write_source_artifacts(tmp_path: Path) -> dict[str, Path]:
    root = tmp_path / "sources"
    root.mkdir()
    paths = {}
    _write_pair_source(root / "itemcf_weak", "itemcf_weak", "seed", "weak_1")
    _write_pair_source(root / "itemcf_strong", "itemcf_strong", "strong_seed", "strong_1")
    _write_pair_source(root / "swing_recall", "swing_recall", "seed", "swing_1", edge_key="swing_recall_edges")
    paths["itemcf_weak"] = root / "itemcf_weak" / "source_index_manifest.json"
    paths["itemcf_strong"] = root / "itemcf_strong" / "source_index_manifest.json"
    paths["swing_recall"] = root / "swing_recall" / "source_index_manifest.json"
    paths["semantic"] = _write_pregenerated_source(root / "semantic", "semantic", "semantic_manifest_1", score=6.0)
    paths["semantic_title_category_expansion"] = _write_semantic_source(root / "semantic_title_category_expansion")
    paths["co_visit_fallback_repair"] = _write_pregenerated_source(
        root / "co_visit_fallback_repair",
        "co_visit_fallback_repair",
        "covisit_manifest_1",
        score=5.5,
        extra_manifest={"algorithm_scope": "train_transition_metadata_repair_v0", "complete_co_visit_graph_claimed": False},
    )
    paths["usercf_recall"] = _write_usercf_source(root / "usercf_recall")
    paths["two_tower"] = _write_two_tower_source(root / "two_tower")
    return paths


def _write_pair_source(path: Path, source: str, src_item: str, dst_item: str, edge_key: str = "edges") -> None:
    path.mkdir(exist_ok=True)
    edges = path / f"{source}_edges.jsonl"
    _write_jsonl(edges, [{"src_item": src_item, "dst_item": dst_item, "score": 5.0, "source": source}])
    manifest = {"status": "PASS", "source": source, "index_scope": "FULL_DERIVED_INDEX", "train_only": True, "edges_path": str(edges), "required_artifacts": {edge_key: str(edges)}}
    (path / "source_index_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


def _write_pregenerated_source(path: Path, source: str, item_id: str, *, score: float, extra_manifest: dict[str, object] | None = None) -> Path:
    path.mkdir()
    candidates = path / "candidates.jsonl"
    _write_jsonl(candidates, [{"user_id": "u1", "item_id": item_id, "score": score, "source": source, "category": "Electronics"}])
    manifest = {
        "status": "PASS",
        "source": source,
        "canonical_source": source,
        "source_status": "TARGET_SLICE_DIAGNOSTIC",
        "index_scope": "TARGET_SLICE_DERIVED_INDEX",
        "train_only": True,
        "candidates_path": str(candidates),
        "candidate_generation_allowed": False,
        "ranking_input_replacement_allowed": False,
        "ranking_replacement_allowed": False,
        "pool1000_allowed": False,
        "promotion_allowed": False,
    }
    if extra_manifest:
        manifest.update(extra_manifest)
    manifest_path = path / "source_index_manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return manifest_path



def _write_semantic_source(path: Path) -> Path:
    path.mkdir()
    semantic = path / "semantic_recall_inputs.jsonl"
    _write_jsonl(
        semantic,
        [
            {"parent_asin": "seed", "title_clean": "gaming mouse", "main_category": "Electronics"},
            {"parent_asin": "semantic_manifest_1", "title_clean": "gaming mat", "main_category": "Electronics"},
            {"parent_asin": "covisit_manifest_1", "title_clean": "ergonomic mouse pad", "main_category": "Electronics"},
        ],
    )
    manifest = {"status": "PASS", "source": "semantic_title_category_expansion", "index_scope": "FULL_DERIVED_INDEX", "semantic_recall_inputs_path": str(semantic)}
    manifest_path = path / "source_index_manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return manifest_path


def _write_usercf_source(path: Path) -> Path:
    path.mkdir()
    shard = path / "shard.jsonl"
    _write_jsonl(shard, [{"user_id": "u1", "candidates": [{"item_id": "usercf_1", "score": 4.0, "rank": 1, "source": "usercf_recall"}]}])
    readiness = {
        "status": "READY",
        "index_status": "INDEX_READY",
        "full_output_status": "FULL_OUTPUT_READY",
        "candidate_generation_allowed": False,
        "ranking_input_replacement_allowed": False,
        "ranking_replacement_allowed": False,
        "pool1000_allowed": False,
        "promotion_allowed": False,
        "output_manifest_sha256": "usercf-output",
        "index_manifest_sha256": "usercf-index",
        "manifest_path": str(path / "readiness_contract.json"),
    }
    (path / "readiness_contract.json").write_text(json.dumps(readiness), encoding="utf-8")
    manifest = {
        "status": "PASS",
        "source_status": "READY",
        "diagnostic_only": False,
        "source": "usercf_recall",
        "index_scope": "FULL_DERIVED_INDEX",
        "train_only": True,
        "candidate_generation_allowed": False,
        "ranking_input_replacement_allowed": False,
        "ranking_replacement_allowed": False,
        "pool1000_allowed": False,
        "promotion_allowed": False,
        "final_pool500_ready_claimed": False,
        "outputs": {"candidate_shards": [str(shard)], "readiness_contract": str(path / "readiness_contract.json")},
    }
    manifest_path = path / "source_index_manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return manifest_path


def _write_two_tower_source(path: Path) -> Path:
    artifact_manifest_path = _write_two_tower_artifact(path)
    artifact_manifest = json.loads(artifact_manifest_path.read_text(encoding="utf-8"))
    recall_index_path = artifact_manifest["contract"]["recall_index"]
    user_embeddings_path = artifact_manifest["contract"]["user_embeddings"]
    source_manifest = {
        "schema_version": "two_tower_source_index_v1",
        "status": "PASS",
        "source": "two_tower",
        "canonical_source": "two_tower",
        "source_name": "two_tower_youtube_dnn",
        "variant": "youtube_dnn",
        "model_type": "youtube_dnn_two_tower_v1",
        "index_scope": "FULL_DERIVED_INDEX",
        "source_status": "FULL_DERIVED_INDEX_DIAGNOSTIC",
        "train_only": True,
        "candidate_generation_allowed": False,
        "ranking_input_replacement_allowed": False,
        "ranking_replacement_allowed": False,
        "pool1000_allowed": False,
        "promotion_allowed": False,
        "final_pool500_ready_claimed": False,
        "row_count": 3,
        "embedding_row_count": 3,
        "index_row_count": 3,
        "embedding_path": recall_index_path,
        "index_path": recall_index_path,
        "user_embedding_path": user_embeddings_path,
        "clean_manifest_sha256": "clean",
        "train_sequence_sha256": "train",
        "item_universe_sha256": "items",
        "model_config_sha256": "model",
        "user_embedding_row_count": 1,
        "model_parameters": {
            "user_tower.0.weight": [[1.0, 0.0], [0.0, 1.0]],
            "user_tower.0.bias": [0.0, 0.0],
            "user_tower.2.weight": [[1.0, 0.0], [0.0, 1.0]],
            "user_tower.2.bias": [0.0, 0.0],
        },
    }
    source_manifest_path = path / "source_index_manifest.json"
    source_manifest_path.write_text(json.dumps(source_manifest), encoding="utf-8")
    return source_manifest_path


def _write_two_tower_artifact(path: Path) -> Path:
    path.mkdir()
    index = path / "recall_index.jsonl"
    users = path / "user_embeddings.jsonl"
    model = path / "model.json"
    _write_jsonl(
        index,
        [
            {"parent_asin": "seed", "embedding": [1.0, 0.0]},
            {"parent_asin": "seed_match", "embedding": [1.0, 0.0]},
            {"parent_asin": "known_match", "embedding": [0.0, 1.0]},
        ],
    )
    _write_jsonl(users, [{"user_id": "known", "embedding": [0.0, 1.0]}])
    model.write_text(
        json.dumps(
            {
                "model_type": "test",
                "source_name": "two_tower",
                "model_parameters": {
                    "user_tower.0.weight": [[1.0, 0.0], [0.0, 1.0]],
                    "user_tower.0.bias": [0.0, 0.0],
                    "user_tower.2.weight": [[1.0, 0.0], [0.0, 1.0]],
                    "user_tower.2.bias": [0.0, 0.0],
                },
            }
        ),
        encoding="utf-8",
    )
    manifest = {
        "artifact_type": "two_tower_recall_index",
        "source_name": "two_tower",
        "contract": {
            "recall_index": str(index),
            "user_embeddings": str(users),
            "model": str(model),
        },
    }
    manifest_path = path / "artifact_manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return manifest_path
