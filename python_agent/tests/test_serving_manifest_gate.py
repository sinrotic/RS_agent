from __future__ import annotations

from pathlib import Path

import pytest

from rs_core.serving.governance.manifest_gate import ManifestGate, evaluate_manifest, evaluate_route_registry_entry

pytestmark = [pytest.mark.unit, pytest.mark.serving]


def test_manifest_gate_admits_manifest_with_required_schema_and_paths(tmp_path: Path) -> None:
    artifact = tmp_path / "artifact.jsonl"
    config = tmp_path / "serving.yaml"
    artifact.write_text("{}\n", encoding="utf-8")
    config.write_text("schema_version: serving_v1\n", encoding="utf-8")

    status = evaluate_manifest(
        {
            "schema_version": "rs_agent_artifact_manifest_v1",
            "artifact_id": "pool500",
            "artifact_type": "candidate_pool",
            "path": "artifact.jsonl",
            "serving_config_path": "serving.yaml",
            "serving_allowed": True,
            "production_ready_claimed": False,
            "governance": {
                "candidate_generation_allowed": False,
                "ranking_input_replacement_allowed": False,
                "promotion_allowed": False,
            },
        },
        base_dir=tmp_path,
    )

    assert status.admitted is True
    assert status.artifact_id == "pool500"
    assert status.artifact_type == "candidate_pool"
    assert set(status.checked_paths) == {str(artifact), str(config)}
    assert "serving_allowed=True" in status.governance_tags
    assert "ranking_input_replacement_allowed=False" in status.governance_tags
    assert "promotion_allowed=False" in status.governance_tags


def test_manifest_gate_rejects_invalid_schema_without_raising(tmp_path: Path) -> None:
    status = evaluate_manifest({"artifact_id": "pool500", "artifact_type": "candidate_pool", "path": "missing.jsonl"}, base_dir=tmp_path)

    assert status.admitted is False
    assert "schema_version is required" in status.errors
    assert any("path does not exist" in error for error in status.errors)


def test_manifest_gate_rejects_unknown_schema_even_when_paths_exist(tmp_path: Path) -> None:
    artifact = tmp_path / "artifact.jsonl"
    artifact.write_text("{}\n", encoding="utf-8")

    status = evaluate_manifest(
        {
            "schema_version": "unknown_manifest_v999",
            "artifact_id": "pool500",
            "artifact_type": "candidate_pool",
            "path": "artifact.jsonl",
        },
        base_dir=tmp_path,
    )

    assert status.admitted is False
    assert "unsupported schema_version: unknown_manifest_v999" in status.errors


def test_manifest_gate_rejects_absolute_and_escaping_paths(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside.jsonl"
    outside.write_text("{}\n", encoding="utf-8")
    inside = tmp_path / "inside.jsonl"
    inside.write_text("{}\n", encoding="utf-8")

    absolute_status = evaluate_manifest(
        {
            "schema_version": "rs_agent_artifact_manifest_v1",
            "artifact_id": "pool500",
            "artifact_type": "candidate_pool",
            "path": str(inside),
        },
        base_dir=tmp_path,
    )
    escaping_status = evaluate_manifest(
        {
            "schema_version": "rs_agent_artifact_manifest_v1",
            "artifact_id": "pool500",
            "artifact_type": "candidate_pool",
            "path": "../outside.jsonl",
        },
        base_dir=tmp_path,
    )

    assert absolute_status.admitted is False
    assert any("path must be relative to base_dir" in error for error in absolute_status.errors)
    assert escaping_status.admitted is False
    assert any("path escapes base_dir" in error for error in escaping_status.errors)


def test_manifest_gate_loads_manifest_path_with_common_config_loader(tmp_path: Path) -> None:
    artifact = tmp_path / "artifact.jsonl"
    manifest = tmp_path / "manifest.yaml"
    artifact.write_text("{}\n", encoding="utf-8")
    manifest.write_text(
        "\n".join(
            [
                "schema_version: rs_agent_artifact_manifest_v1",
                "artifact_id: pool500",
                "artifact_type: candidate_pool",
                "path: artifact.jsonl",
            ]
        ),
        encoding="utf-8",
    )

    status = ManifestGate(tmp_path).evaluate_manifest(manifest)

    assert status.admitted is True
    assert status.schema_version == "rs_agent_artifact_manifest_v1"


def test_manifest_gate_checks_artifact_store_local_path(tmp_path: Path) -> None:
    local = tmp_path / "local.json"
    local.write_text("{}", encoding="utf-8")

    status = evaluate_manifest(
        {
            "schema_version": "rs_agent_artifact_manifest_v1",
            "artifact_id": "deepfm",
            "artifact_type": "ranking_model_shadow_diagnostic",
            "artifact_store": {"local_path": "local.json"},
        },
        base_dir=tmp_path,
    )

    assert status.admitted is True
    assert status.checked_paths == (str(local),)


def test_route_registry_entry_checks_config_and_required_outputs(tmp_path: Path) -> None:
    config = tmp_path / "configs" / "serving.yaml"
    output = tmp_path / "outputs" / "pool500.jsonl"
    config.parent.mkdir()
    output.parent.mkdir()
    config.write_text("schema_version: serving_v1\n", encoding="utf-8")
    output.write_text("{}\n", encoding="utf-8")

    status = evaluate_route_registry_entry(
        "current_online_service_route",
        {
            "status": "provisional_current",
            "config_paths": ["configs/serving.yaml"],
            "required_output_paths": ["outputs/pool500.jsonl"],
            "candidate_generation_allowed": True,
            "ranking_input_replacement_allowed": False,
            "promotion_allowed": False,
            "full_pool500_ready_semantics": "recall_artifact_readiness_only",
        },
        base_dir=tmp_path,
    )

    assert status.admitted is True
    assert set(status.checked_paths) == {str(config), str(output)}
    assert "status=provisional_current" in status.governance_tags
    assert "ranking_input_replacement_allowed=False" in status.governance_tags
    assert "full_pool500_ready_semantics=recall_artifact_readiness_only" in status.governance_tags


def test_route_registry_entry_rejects_missing_paths_without_throwing(tmp_path: Path) -> None:
    status = evaluate_route_registry_entry(
        "current_online_service_route",
        {"config_paths": ["missing.yaml"], "required_output_paths": ["missing.jsonl"]},
        base_dir=tmp_path,
    )

    assert status.admitted is False
    assert any("config_paths path does not exist" in error for error in status.errors)
    assert any("required_output_paths path does not exist" in error for error in status.errors)


def test_route_registry_rejects_non_mapping_entry(tmp_path: Path) -> None:
    status = ManifestGate(tmp_path).evaluate_route_registry(
        {"routes": {"current_online_service_route": "not-a-mapping"}}
    )["current_online_service_route"]

    assert status.admitted is False
    assert "route entry must be a mapping" in status.errors


def test_route_registry_entry_rejects_absolute_and_escaping_paths(tmp_path: Path) -> None:
    inside = tmp_path / "serving.yaml"
    inside.write_text("schema_version: serving_v1\n", encoding="utf-8")

    absolute_status = evaluate_route_registry_entry(
        "current_online_service_route",
        {"config_paths": [str(inside)]},
        base_dir=tmp_path,
    )
    escaping_status = evaluate_route_registry_entry(
        "current_online_service_route",
        {"config_paths": ["../serving.yaml"]},
        base_dir=tmp_path,
    )

    assert absolute_status.admitted is False
    assert any("path must be relative to base_dir" in error for error in absolute_status.errors)
    assert escaping_status.admitted is False
    assert any("path escapes base_dir" in error for error in escaping_status.errors)
