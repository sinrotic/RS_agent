from __future__ import annotations

import pytest

pytestmark = pytest.mark.experiment

from rs_core.workflow.full_data_pool500_route_gate import (
    CANONICAL_SOURCES,
    DIAGNOSTIC_ONLY,
    DIAGNOSTIC_ONLY_PARTIAL,
    FULL_POOL500_READY,
    POOL500_RECALL_READY,
    READINESS_BUNDLE_SCHEMA_VERSION,
    READY,
    STOP,
    build_pool500_shadow_evidence,
    canonical_manifest_sha256,
    canonical_user_set_hash,
    canonicalize_source_label,
    full_data_pool500_artifact_gate,
    full_data_pool500_route_gate,
    no_holdout_leakage_audit,
    validate_method_contract,
    validate_pool500_shadow_evidence,
    validate_readiness_bundle,
)


def _clean_manifest() -> dict[str, object]:
    return {
        "schema_version": "test_clean_full_v1",
        "canonical_items_path": "data/processed/full/canonical_items.parquet",
        "train_user_sequences_path": "data/processed/full/user_sequences.train.jsonl",
        "split_paths": {
            "train": "data/processed/full/canonical_interactions.train.jsonl",
            "valid": "data/processed/full/canonical_interactions.valid.jsonl",
            "test": "data/processed/full/canonical_interactions.test.jsonl",
        },
    }


def _lightweight_views_manifest() -> dict[str, object]:
    return {
        "mode": "full_lightweight",
        "outputs": {
            "popular_recall": "outputs/lightweight/popular.jsonl",
            "category_recall_items": "outputs/lightweight/category_items.jsonl",
            "category_top_items": "outputs/lightweight/category_top.jsonl",
            "semantic_recall_inputs": "outputs/lightweight/semantic_inputs.jsonl",
            "semantic_inverted_index": "outputs/lightweight/semantic_index.jsonl",
        },
        "skipped_outputs": [],
    }


def _method_contract(**overrides: object) -> dict[str, object]:
    contract: dict[str, object] = {
        "candidate_pool_size": 500,
        "sources": sorted(CANONICAL_SOURCES),
        "inputs": ["data/processed/full/user_sequences.train.jsonl"],
    }
    contract.update(overrides)
    return contract


def _index_manifest(**overrides: object) -> dict[str, object]:
    manifest: dict[str, object] = {
        "index_scope": "FULL_DERIVED_INDEX",
        "inputs": ["data/processed/full/canonical_interactions.train.jsonl"],
    }
    manifest.update(overrides)
    return manifest


def _gate(
    *,
    method_contract: dict[str, object] | None = None,
    index_manifest: dict[str, object] | None = None,
    observed_outputs: dict[str, object] | None = None,
) -> dict[str, object]:
    return full_data_pool500_route_gate(
        method_contract=method_contract or _method_contract(),
        index_manifest=index_manifest or _index_manifest(),
        clean_manifest=_clean_manifest(),
        lightweight_views_manifest=_lightweight_views_manifest(),
        observed_outputs=observed_outputs,
    )


def _blocker_codes(result: dict[str, object]) -> set[str]:
    return {blocker["code"] for blocker in result["blockers"]}  # type: ignore[index]


def _diagnostic_codes(result: dict[str, object]) -> set[str]:
    return {diagnostic["code"] for diagnostic in result["diagnostics"]}  # type: ignore[index]


def _artifact_ready_hash(source: str) -> str:
    return canonical_manifest_sha256({"source": source, "ready": True})


def _artifact_readiness(**overrides: dict[str, object]) -> dict[str, dict[str, object]]:
    contracts = {
        source: {
            "source": source,
            "status": READY,
            "index_status": "INDEX_READY",
            "diagnostic_output_status": "DIAGNOSTIC_OUTPUT_READY",
            "full_output_status": "FULL_OUTPUT_READY",
            "manifest_path": f"outputs/pool500/{source}/manifest.json",
            "index_manifest_sha256": _artifact_ready_hash(f"{source}:index"),
            "output_manifest_sha256": _artifact_ready_hash(source),
        }
        for source in sorted(CANONICAL_SOURCES)
    }
    contracts["two_tower"].update(
        {
            "source_name": "two_tower",
            "canonical_source": "two_tower",
            "clean_manifest_sha256": "clean-full-sha",
            "train_sequence_sha256": "train-seq-sha",
            "item_universe_sha256": "item-universe-sha",
            "model_config_sha256": "model-config-sha",
            "item_embedding_row_count": 10,
            "recall_index_row_count": 10,
            "index_scope": "FULL_DERIVED_INDEX",
            "user_embedding_row_count_note": "not required for item index readiness",
        }
    )
    for source, override in overrides.items():
        if source in contracts and isinstance(override, dict):
            contracts[source].update(override)
        else:
            contracts[source] = override
    return contracts


def _artifact_outputs(**overrides: dict[str, object]) -> dict[str, dict[str, object]]:
    manifests = {
        source: {
            "manifest_sha256": _artifact_ready_hash(source),
            "final_sources": [source],
            "output_path": f"outputs/pool500/{source}/candidates.jsonl",
        }
        for source in sorted(CANONICAL_SOURCES)
    }
    manifests.update(overrides)
    return manifests


def _artifact_rows(*, omit_sources: set[str] | None = None) -> list[dict[str, object]]:
    omit_sources = omit_sources or set()
    return [
        {
            "user_id": "u1",
            "item_id": f"i{index}",
            "source": source,
            "score": 1.0 / index,
            "rank": index,
            "metadata": {"source_rank": index},
        }
        for index, source in enumerate(sorted(CANONICAL_SOURCES - omit_sources), start=1)
    ]


def _artifact_gate_defaults_index_manifests() -> dict[str, dict[str, object]]:
    two_tower_full_clean = dict(_artifact_readiness()["two_tower"])
    return {
        source: {
            "source": source,
            "index_status": "INDEX_READY",
            "manifest_sha256": _artifact_ready_hash(f"{source}:index"),
            "index_scope": "FULL_DERIVED_INDEX",
            "index_path": f"outputs/pool500/{source}/full_index.json",
            **(two_tower_full_clean if source == "two_tower" else {}),
        }
        for source in sorted(CANONICAL_SOURCES)
    }


def _artifact_gate(**overrides: object) -> dict[str, object]:
    kwargs: dict[str, object] = {
        "eligible_user_manifest": {"eligible_user_ids": ["u2", "u1", "u1"]},
        "source_budget_contract": {
            "budget_frozen": True,
            "train_only": True,
            "input_path": "data/processed/full/user_sequences.train.jsonl",
        },
        "per_source_readiness_contracts": _artifact_readiness(),
        "per_source_output_manifests": _artifact_outputs(),
        "full_derived_index_manifests": _artifact_gate_defaults_index_manifests(),
        "merged_pool500_manifest": {
            "user_ids": ["u1", "u2"],
            "underfilled_user_count": 0,
            "lineage": {"source_manifests": [f"outputs/pool500/{source}/manifest.json" for source in sorted(CANONICAL_SOURCES)]},
            "output_path": "outputs/pool500/final/merged_pool500.jsonl",
        },
        "merged_rows": _artifact_rows(),
        "route_input_manifest": {
            "declared_inputs": ["data/processed/full/user_sequences.train.jsonl"],
            "source_manifests": [f"outputs/pool500/{source}/manifest.json" for source in sorted(CANONICAL_SOURCES)],
        },
    }
    kwargs.update(overrides)
    return full_data_pool500_artifact_gate(**kwargs)  # type: ignore[arg-type]


def test_full_data_gate_accepts_exact_canonical_source_set() -> None:
    audit = validate_method_contract(_method_contract())

    assert audit["status"] == "PASS"
    assert set(audit["canonical_sources"]) == CANONICAL_SOURCES
    assert audit["blockers"] == []

    result = _gate()
    assert result["decision"] == POOL500_RECALL_READY
    assert result["candidate_generation_allowed"] is True
    assert result["ranking_input_replacement_allowed"] is False


def test_source_alias_mapping_normalizes_to_canonical_sources() -> None:
    alias_sources = [
        "popular_recall",
        "category_top_items",
        "semantic_recall",
        "semantic_title_category_expansion",
        "itemcf_weak",
        "itemcf_strong",
        "co_visit_repair",
        "usercf",
        "swing",
        "two_tower_recall",
    ]
    audit = validate_method_contract(_method_contract(sources=alias_sources))

    assert audit["status"] == "PASS"
    assert set(audit["canonical_sources"]) == CANONICAL_SOURCES
    assert canonicalize_source_label("two-tower-recall") == "two_tower"


def test_user_set_hash_is_order_and_duplicate_stable() -> None:
    left = canonical_user_set_hash(["u3", "u1", "u2", "u1"])
    right = canonical_user_set_hash(["u2", "u3", "u1"])
    different = canonical_user_set_hash(["u1", "u2"])

    assert left == right
    assert left != different


def test_no_holdout_forbidden_input_blocks_generation_audit() -> None:
    audit = no_holdout_leakage_audit(
        ["data/processed/full/canonical_interactions.valid.jsonl", "data/processed/full/user_sequences.train.jsonl"],
        {"candidate_generation"},
    )

    assert audit["status"] == "BLOCKED"
    assert audit["candidate_generation_uses_holdout"] is True
    assert {blocker["code"] for blocker in audit["blockers"]} == {"HOLDOUT_LEAKAGE_FORBIDDEN"}


def test_index_scope_is_diagnostic_only_without_blocking_readiness_audits() -> None:
    result = _gate(index_manifest=_index_manifest(index_scope="REPRESENTATIVE_DERIVED_INDEX"))

    assert result["decision"] == DIAGNOSTIC_ONLY
    assert result["candidate_generation_allowed"] is False
    assert result["index_manifest_audit"]["index_scope_diagnostic_only"] is True  # type: ignore[index]
    assert result["blockers"] == []


def test_pool1000_contract_or_outputs_force_stop() -> None:
    contract_result = _gate(method_contract=_method_contract(pool1000_ready=True))
    output_result = _gate(observed_outputs={"candidate_generation_executed": False, "output_paths": ["outputs/pool1000.jsonl"]})

    assert contract_result["decision"] == STOP
    assert "POOL1000_OUTPUT_FORBIDDEN" in _blocker_codes(contract_result)
    assert output_result["decision"] == STOP
    assert "POOL1000_OUTPUT_FORBIDDEN" in _blocker_codes(output_result)


def test_old_p7_representative_and_probe_markers_are_diagnostic_only_not_ready() -> None:
    result = _gate(
        method_contract=_method_contract(
            legacy_reference_signature=True,
            representative_sample_size=500,
            feasibility_only=True,
        ),
        index_manifest=_index_manifest(
            custom_index_scope_only=True,
            candidate_generation_executed=False,
            no_model_training_executed=True,
        ),
    )

    assert result["decision"] == DIAGNOSTIC_ONLY
    assert result["legacy_reference_signature_pass_authority"] is False
    assert result["candidate_generation_allowed"] is False
    assert result["representative_probe_audit"]["diagnostic_only"] is True  # type: ignore[index]
    assert result["blockers"] == []


def test_partial_output_rejection_for_executed_generation_without_outputs() -> None:
    result = _gate(observed_outputs={"candidate_generation_executed": True, "output_paths": []})

    assert result["decision"] == STOP
    assert result["candidate_generation_allowed"] is False
    assert "PARTIAL_OUTPUT_REJECTED" in _blocker_codes(result)
    assert result["partial_output_audit"]["status"] == "BLOCKED"  # type: ignore[index]


def test_legacy_route_gate_ready_is_not_full_pool500_artifact_ready() -> None:
    route_result = _gate()

    assert route_result["decision"] == POOL500_RECALL_READY
    assert route_result["decision"] != FULL_POOL500_READY


def test_artifact_gate_accepts_complete_v5_artifact_contract() -> None:
    result = _artifact_gate()

    assert result["decision"] == FULL_POOL500_READY
    assert result["status"] == "PASS"
    assert result["candidate_generation_allowed"] is False
    assert result["ranking_input_replacement_allowed"] is False
    assert result["blockers"] == []
    assert result["diagnostics"] == []


def test_diagnostic_output_cannot_be_promoted_to_full_ready() -> None:
    popular_contract = dict(_artifact_readiness()["popular"])
    popular_contract["full_output_status"] = "OUTPUT_MISSING"
    result = _artifact_gate(per_source_readiness_contracts=_artifact_readiness(popular=popular_contract))

    assert result["decision"] == STOP
    assert "DIAGNOSTIC_OUTPUT_NOT_FULL_READY" in _blocker_codes(result)


def test_full_ready_requires_source_output_manifest() -> None:
    outputs = _artifact_outputs()
    del outputs["popular"]
    result = _artifact_gate(per_source_output_manifests=outputs)

    assert result["decision"] == STOP
    assert "READY_MANIFEST_MISSING" in _blocker_codes(result)


def test_unknown_source_readiness_label_blocks_artifact_gate() -> None:
    result = _artifact_gate(per_source_readiness_contracts={**_artifact_readiness(), "legacy_source": {"status": READY}})

    assert result["decision"] == STOP
    assert "UNKNOWN_SOURCE_LABEL" in _blocker_codes(result)


def test_full_ready_requires_index_manifest_sha_and_source_consistency() -> None:
    index_manifests = _artifact_gate_defaults_index_manifests()
    index_manifests["popular"] = {
        "source": "semantic",
        "index_status": "INDEX_READY",
        "manifest_sha256": "wrong-sha",
        "index_scope": "REPRESENTATIVE_DERIVED_INDEX",
        "index_path": "outputs/pool500/popular/full_index.json",
    }
    result = _artifact_gate(full_derived_index_manifests=index_manifests)

    blocker_codes = _blocker_codes(result)
    assert result["decision"] == STOP
    assert "FULL_INDEX_SOURCE_MISMATCH" in blocker_codes
    assert "FULL_INDEX_SCOPE_MISMATCH" in blocker_codes
    assert "SOURCE_INDEX_SHA_MISMATCH" in blocker_codes


@pytest.mark.parametrize(
    ("overrides", "blocker_code"),
    [
        ({"per_source_readiness_contracts": _artifact_readiness(two_tower={"manifest_missing": True})}, "READY_MANIFEST_MISSING"),
        ({"per_source_readiness_contracts": _artifact_readiness(two_tower={**_artifact_readiness()["two_tower"], "status": READY, "manifest_path": "outputs/training/two_tower/two_tower_training/youtube_dnn/artifact_manifest.json"})}, "TWO_TOWER_FORBIDDEN_ARTIFACT_SCOPE"),
        ({"per_source_readiness_contracts": _artifact_readiness(two_tower={**_artifact_readiness()["two_tower"], "status": READY, "source_name": "youtube_dnn"})}, "TWO_TOWER_CANONICAL_SOURCE_REQUIRED"),
        ({"per_source_readiness_contracts": _artifact_readiness(two_tower={**_artifact_readiness()["two_tower"], "status": READY, "canonical_source": "youtube_dnn"})}, "TWO_TOWER_CANONICAL_SOURCE_REQUIRED"),
        ({"per_source_readiness_contracts": _artifact_readiness(youtube_dnn={**_artifact_readiness()["two_tower"], "source": "youtube_dnn", "source_name": "two_tower", "canonical_source": "two_tower"})}, "TWO_TOWER_CANONICAL_SOURCE_REQUIRED"),
        ({"full_derived_index_manifests": {**_artifact_gate_defaults_index_manifests(), "two_tower": {**_artifact_gate_defaults_index_manifests()["two_tower"], "index_path": "outputs/pool500/youtube_dnn/full_index.json"}}}, "TWO_TOWER_FORBIDDEN_ARTIFACT_SCOPE"),
        ({"per_source_readiness_contracts": _artifact_readiness(two_tower={**_artifact_readiness()["two_tower"], "clean_manifest_sha256": None})}, "TWO_TOWER_FULL_CLEAN_FIELD_MISSING"),
        ({"per_source_readiness_contracts": _artifact_readiness(two_tower={**_artifact_readiness()["two_tower"], "status": READY, "manifest_path": "outputs/pool500/two_tower/amazon_2023_recall_clean_10000/manifest.json"})}, "TWO_TOWER_FORBIDDEN_ARTIFACT_SCOPE"),
        ({"per_source_readiness_contracts": _artifact_readiness(two_tower={**_artifact_readiness()["two_tower"], "status": READY, "manifest_path": "outputs/pool500/two_tower/leave_one_positive_out/manifest.json"})}, "TWO_TOWER_FORBIDDEN_ARTIFACT_SCOPE"),
        ({"per_source_readiness_contracts": _artifact_readiness(two_tower={"status": READY, "train_path": "data/processed/full/canonical_interactions.valid.jsonl", **_artifact_readiness()["two_tower"]})}, "HOLDOUT_LEAKAGE_FORBIDDEN"),
        ({"merged_pool500_manifest": {"user_ids": ["u9"], "lineage": {"source_manifests": ["outputs/pool500/popular/manifest.json"]}}}, "USER_HASH_MISMATCH"),
        ({"route_input_manifest": {"input_strategy": "latest glob", "declared_inputs": ["data/processed/full/user_sequences.train.jsonl"]}}, "ROUTE_INPUT_INFERENCE_FORBIDDEN"),
        ({"route_input_manifest": {"declared_inputs": ["outputs/pool1000/candidates.jsonl"]}}, "POOL1000_OUTPUT_FORBIDDEN"),
        ({"route_input_manifest": {"ranking_input_replacement": True, "declared_inputs": ["data/processed/full/user_sequences.train.jsonl"]}}, "RANKING_INPUT_REPLACEMENT_FORBIDDEN"),
        ({"source_budget_contract": {"budget_frozen": True, "train_only": True, "input_path": "data/processed/full/canonical_interactions.valid.jsonl"}}, "HOLDOUT_LEAKAGE_FORBIDDEN"),
        ({"per_source_readiness_contracts": _artifact_readiness(popular={"status": READY, "manifest_missing": True})}, "READY_MANIFEST_MISSING"),
        ({"per_source_output_manifests": _artifact_outputs(popular={"manifest_sha256": "bad", "final_sources": ["popular"]})}, "SOURCE_OUTPUT_SHA_MISMATCH"),
        ({"merged_rows": [{"user_id": "u1", "item_id": "i1", "source": "popular", "rank": 1, "metadata": {}}]}, "JSONL_SCHEMA_CORRUPT"),
        ({"per_source_output_manifests": _artifact_outputs(popular={"manifest_sha256": _artifact_ready_hash("popular"), "final_sources": ["legacy"]})}, "FINAL_SOURCE_NOT_WHITELISTED"),
        ({"merged_pool500_manifest": {"user_ids": ["u1", "u2"], "underfilled_user_count": 0, "lineage": {"source_manifests": ["outputs/pool500/legacy_probe_manifest.json"]}}}, "FINAL_ARTIFACT_MARKER_FORBIDDEN"),
    ],
)
def test_artifact_gate_stop_conditions(overrides: dict[str, object], blocker_code: str) -> None:
    result = _artifact_gate(**overrides)

    assert result["decision"] == STOP
    assert blocker_code in _blocker_codes(result)


@pytest.mark.parametrize(
    ("overrides", "diagnostic_code"),
    [
        (
            {
                "per_source_readiness_contracts": _artifact_readiness(popular={"status": "DEFERRED", "manifest_path": "outputs/pool500/popular/manifest.json"}),
                "merged_rows": _artifact_rows(omit_sources={"popular"}),
            },
            "REQUIRED_SOURCE_NOT_READY",
        ),
        (
            {
                "per_source_readiness_contracts": _artifact_readiness(two_tower={"status": "DEFERRED", "manifest_path": "outputs/pool500/two_tower/manifest.json"}),
                "merged_rows": _artifact_rows(omit_sources={"two_tower"}),
            },
            "TWO_TOWER_INDEX_READY_SOURCE_NOT_READY",
        ),
        ({"source_budget_contract": {"budget_frozen": False, "train_only": True, "input_path": "data/processed/full/user_sequences.train.jsonl"}}, "BUDGET_NOT_FROZEN_TRAIN_ONLY"),
        ({"merged_pool500_manifest": {"user_ids": ["u1", "u2"], "underfilled_user_count": 1, "lineage": {"source_manifests": ["outputs/pool500/popular/manifest.json"]}}}, "UNDERFILLED_THRESHOLD_EXCEEDED"),
        ({"merged_pool500_manifest": {"user_ids": ["u1", "u2"], "underfilled_user_count": 0}}, "LINEAGE_INCOMPLETE"),
    ],
)
def test_artifact_gate_diagnostic_only_partial_conditions(overrides: dict[str, object], diagnostic_code: str) -> None:
    result = _artifact_gate(**overrides)

    assert result["decision"] == DIAGNOSTIC_ONLY_PARTIAL
    assert result["blockers"] == []
    assert diagnostic_code in _diagnostic_codes(result)


def test_route_input_false_pool1000_flag_is_not_forbidden_output() -> None:
    result = _artifact_gate(route_input_manifest={"declared_inputs": ["data/processed/full/user_sequences.train.jsonl"], "pool1000_ready": False})

    assert result["decision"] == FULL_POOL500_READY
    assert "POOL1000_OUTPUT_FORBIDDEN" not in _blocker_codes(result)


def _readiness_bundle(**overrides: object) -> dict[str, object]:
    bundle: dict[str, object] = {
        "schema_version": READINESS_BUNDLE_SCHEMA_VERSION,
        "artifact_gate_result": {"decision": FULL_POOL500_READY, "status": "PASS"},
        "quality_audit": {"status": "PASS"},
        "source_budget_audit": {"status": "PASS"},
        "source_output_manifest_audit": {"status": "PASS"},
        "index_manifest_audit": {"status": "PASS"},
        "no_holdout_audit": {"status": "PASS"},
        "ranking_registry_check": {"status": "PASS"},
        "final_merged_candidate_manifest": {"path": "outputs/pool500/final/merged_pool500_manifest.json"},
        "eligible_user_manifest": {"eligible_user_hash": canonical_user_set_hash(["u1", "u2"])},
        "canonical_source_registry_sha256": canonical_manifest_sha256({"sources": sorted(CANONICAL_SOURCES)}),
    }
    bundle.update(overrides)
    return bundle


def test_pool500_shadow_evidence_is_independent_read_only_schema() -> None:
    artifact_gate_result = _artifact_gate()

    evidence = build_pool500_shadow_evidence(
        evidence_id="test-shadow",
        artifact_gate_result=artifact_gate_result,
        readiness_bundle_result={"decision": FULL_POOL500_READY, "status": "PASS"},
        readiness_bundle_path="outputs/pool500/readiness_bundle.json",
        artifact_paths={"merged_pool500_manifest": "outputs/pool500/final/merged_pool500_manifest.json"},
    )
    validation = validate_pool500_shadow_evidence(evidence)

    assert evidence["schema_version"] == "pool500_shadow_evidence_v1"
    assert evidence["shadow_mode"] == "read_only_shadow_evidence"
    assert evidence["full_pool500_ready_semantics"] == "recall_artifact_readiness_only"
    assert evidence["promotion_allowed"] is False
    assert evidence["ranking_replacement_allowed"] is False
    assert evidence["ranking_input_replacement_allowed"] is False
    assert evidence["candidate_generation_allowed"] is False
    assert "current_ranking_route" not in evidence
    assert validation["status"] == "PASS"
    assert validation["blockers"] == []


def test_pool500_shadow_evidence_rejects_promotion_generation_and_ranking_route_write() -> None:
    evidence = build_pool500_shadow_evidence(evidence_id="test-shadow", artifact_gate_result=_artifact_gate())
    evidence.update(
        {
            "promotion_allowed": True,
            "ranking_replacement_allowed": True,
            "ranking_input_replacement_allowed": True,
            "candidate_generation_allowed": True,
            "current_ranking_route": {"required_output_paths": ["outputs/recall/pool500/manifest.json"]},
        }
    )

    validation = validate_pool500_shadow_evidence(evidence)

    assert validation["decision"] == STOP
    blocker_codes = _blocker_codes(validation)
    assert "PROMOTION_FORBIDDEN_BY_SHADOW_EVIDENCE" in blocker_codes
    assert "RANKING_REPLACEMENT_FORBIDDEN_BY_SHADOW_EVIDENCE" in blocker_codes
    assert "CANDIDATE_GENERATION_NOT_AUTHORIZED_BY_SHADOW_EVIDENCE" in blocker_codes
    assert "CURRENT_RANKING_ROUTE_WRITE_FORBIDDEN" in blocker_codes
    assert validation["promotion_allowed"] is False
    assert validation["ranking_replacement_allowed"] is False
    assert validation["candidate_generation_allowed"] is False


def test_readiness_bundle_is_final_full_pool500_ready_authority() -> None:
    result = validate_readiness_bundle(_readiness_bundle())

    assert result["decision"] == FULL_POOL500_READY
    assert result["status"] == "PASS"
    assert result["candidate_generation_allowed"] is False
    assert result["ranking_input_replacement_allowed"] is False
    assert result["pool1000_allowed"] is False
    assert result["blockers"] == []
    assert result["diagnostics"] == []


def test_readiness_bundle_requires_artifact_gate_full_ready() -> None:
    result = validate_readiness_bundle(_readiness_bundle(artifact_gate_result={"decision": DIAGNOSTIC_ONLY_PARTIAL}))

    assert result["decision"] == DIAGNOSTIC_ONLY_PARTIAL
    assert "ARTIFACT_GATE_NOT_FULL_READY" in _diagnostic_codes(result)


def test_readiness_bundle_treats_quality_failures_as_diagnostic_partial() -> None:
    result = validate_readiness_bundle(_readiness_bundle(quality_audit={"status": "FAIL"}))

    assert result["decision"] == DIAGNOSTIC_ONLY_PARTIAL
    assert "READINESS_AUDIT_NOT_PASS" in _diagnostic_codes(result)


def test_readiness_bundle_treats_no_holdout_failure_as_stop() -> None:
    result = validate_readiness_bundle(_readiness_bundle(no_holdout_audit={"status": "FAIL"}))

    assert result["decision"] == STOP
    assert "READINESS_AUDIT_NOT_PASS" in _blocker_codes(result)


def test_readiness_bundle_does_not_authorize_ranking_or_pool1000() -> None:
    result = validate_readiness_bundle(
        _readiness_bundle(
            ranking_input_replacement_allowed=True,
            pool1000_allowed=True,
        )
    )

    assert result["decision"] == STOP
    assert "RANKING_INPUT_REPLACEMENT_FORBIDDEN" in _blocker_codes(result)
    assert "POOL1000_OUTPUT_FORBIDDEN" in _blocker_codes(result)


def test_phase_a_readiness_bundle_skeleton_is_not_full_ready() -> None:
    result = validate_readiness_bundle(
        {
            "schema_version": READINESS_BUNDLE_SCHEMA_VERSION,
            "artifact_gate_result": {"decision": DIAGNOSTIC_ONLY_PARTIAL},
            "quality_audit": {"status": "NOT_PROVIDED"},
            "source_budget_audit": {"status": "NOT_PROVIDED"},
            "source_output_manifest_audit": {"status": "NOT_PROVIDED"},
            "index_manifest_audit": {"status": "NOT_PROVIDED"},
            "no_holdout_audit": {"status": "PASS"},
            "ranking_registry_check": {"status": "PASS"},
        }
    )

    assert result["decision"] == DIAGNOSTIC_ONLY_PARTIAL
    assert "ARTIFACT_GATE_NOT_FULL_READY" in _diagnostic_codes(result)
    assert "READINESS_BUNDLE_FIELD_MISSING" in _diagnostic_codes(result)


def test_manifest_hash_is_key_order_and_path_slash_stable() -> None:
    left = canonical_manifest_sha256({"b": {"path": "outputs\\pool500\\popular.jsonl"}, "a": ["x", "y"]})
    right = canonical_manifest_sha256({"a": ["x", "y"], "b": {"path": "outputs/pool500/popular.jsonl"}})
    different = canonical_manifest_sha256({"a": ["x", "z"], "b": {"path": "outputs/pool500/popular.jsonl"}})

    assert left == right
    assert left != different
