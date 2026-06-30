from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.artifacts.upload_to_minio import build_planned_patch, process_inputs, read_inventory

pytestmark = pytest.mark.unit


def test_dry_run_patch_includes_hash_and_minio_uri(tmp_path: Path) -> None:
    artifact = tmp_path / "artifact.jsonl"
    artifact.write_text("{}\n", encoding="utf-8")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": "test_v1",
                "artifact_id": "artifact-1",
                "artifact_type": "candidate_pool",
                "path": str(artifact),
            }
        ),
        encoding="utf-8",
    )

    patch = build_planned_patch(manifest, bucket="local-bucket")

    store = patch["artifact_store"]
    assert store["storage_backend"] == "minio"
    assert store["local_path"] == str(artifact)
    assert store["minio_uri"] == "minio://local-bucket/artifact-1/artifact.jsonl"
    assert store["artifact_uri"] == store["minio_uri"]
    assert store["sha256"]
    assert store["size_bytes"] == 4
    assert store["uploaded_at"] is None


def test_inventory_supports_mapping_and_list(tmp_path: Path) -> None:
    first = tmp_path / "a.json"
    second = tmp_path / "b.yaml"
    mapping_inventory = tmp_path / "inventory.json"
    list_inventory = tmp_path / "inventory.yaml"
    mapping_inventory.write_text(json.dumps({"artifacts": [str(first), {"manifest": str(second)}]}), encoding="utf-8")
    list_inventory.write_text(f"- {first}\n- manifest: {second}\n", encoding="utf-8")

    assert read_inventory(mapping_inventory) == [first, second]
    assert read_inventory(list_inventory) == [first, second]


def test_process_inputs_dry_run_inventory(tmp_path: Path) -> None:
    artifact = tmp_path / "artifact.bin"
    artifact.write_bytes(b"abc")
    manifest = tmp_path / "manifest.yaml"
    manifest.write_text(
        "schema_version: test_v1\nartifact_id: artifact-2\nartifact_type: model\npath: " + str(artifact).replace("\\", "/") + "\n",
        encoding="utf-8",
    )
    inventory = tmp_path / "inventory.json"
    inventory.write_text(json.dumps({"artifacts": [str(manifest)]}), encoding="utf-8")

    args = type(
        "Args",
        (),
        {
            "manifest": None,
            "inventory": str(inventory),
            "endpoint": None,
            "bucket": "bucket",
            "access_key_env": "RS_MINIO_ACCESS_KEY",
            "secret_key_env": "RS_MINIO_SECRET_KEY",
            "secure": False,
            "dry_run": True,
            "upload": False,
            "verify": False,
        },
    )()

    result = process_inputs(args)

    assert len(result) == 1
    assert result[0]["manifest"] == str(manifest)
    assert result[0]["patch"]["artifact_store"]["minio_uri"] == "minio://bucket/artifact-2/artifact.bin"
