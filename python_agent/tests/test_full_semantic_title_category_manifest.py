from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from rs_lab.experiments.recall.build_full_semantic_title_category_manifest import build_full_semantic_title_category_manifest

pytestmark = pytest.mark.experiment


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fixture_manifests(tmp_path: Path) -> tuple[Path, Path, Path, dict[str, Path]]:
    data_dir = tmp_path / "data" / "processed" / "amazon_2023_recall_clean_full"
    views_dir = tmp_path / "outputs" / "full_lightweight"
    canonical_items = data_dir / "canonical_items.parquet"
    semantic_inputs = views_dir / "semantic_inputs.jsonl"
    semantic_index = views_dir / "semantic_index.jsonl"
    _write_text(canonical_items, "canonical-items\n")
    _write_text(semantic_inputs, '{"item_id":"i1","tokens":["phone"]}\n')
    _write_text(semantic_index, '{"token":"phone","item_ids":["i1"]}\n')

    clean_manifest = tmp_path / "clean_manifest.json"
    views_manifest = tmp_path / "views_manifest.json"
    _write_json(
        clean_manifest,
        {
            "schema_version": "test_clean_full_v1",
            "canonical_items_path": str(canonical_items),
            "train_user_sequences_path": str(data_dir / "user_sequences.train.jsonl"),
            "split_paths": {"train": str(data_dir / "canonical_interactions.train.jsonl")},
        },
    )
    _write_json(
        views_manifest,
        {
            "mode": "full_lightweight",
            "outputs": {
                "semantic_recall_inputs": str(semantic_inputs),
                "semantic_inverted_index": str(semantic_index),
            },
        },
    )
    return clean_manifest, views_manifest, tmp_path / "out", {
        "canonical_items": canonical_items,
        "semantic_inputs": semantic_inputs,
        "semantic_index": semantic_index,
    }


def test_builds_source_manifest_with_bound_sha_and_guards(tmp_path: Path) -> None:
    clean_manifest, views_manifest, output_dir, paths = _fixture_manifests(tmp_path)

    manifest = build_full_semantic_title_category_manifest(
        clean_manifest_path=clean_manifest,
        lightweight_views_manifest_path=views_manifest,
        output_dir=output_dir,
        enforce_venv=False,
    )

    source_index_manifest = json.loads((output_dir / "source_index_manifest.json").read_text(encoding="utf-8"))
    resource_audit = json.loads((output_dir / "resource_audit.json").read_text(encoding="utf-8"))
    no_holdout_audit = json.loads((output_dir / "no_holdout_audit.json").read_text(encoding="utf-8"))

    assert manifest == source_index_manifest
    assert source_index_manifest["source"] == "semantic_title_category_expansion"
    assert source_index_manifest["index_scope"] == "FULL_DERIVED_INDEX"
    assert source_index_manifest["canonical_items_sha256"] == _sha256(paths["canonical_items"])
    assert source_index_manifest["semantic_recall_inputs_sha256"] == _sha256(paths["semantic_inputs"])
    assert source_index_manifest["semantic_inverted_index_sha256"] == _sha256(paths["semantic_index"])
    assert source_index_manifest["loader_mode"] == "full_manifest_declared"
    assert source_index_manifest["diagnostic_only"] is False
    assert source_index_manifest["candidate_generation_allowed"] is False
    assert source_index_manifest["ranking_input_replacement_allowed"] is False
    assert source_index_manifest["pool1000_allowed"] is False
    assert source_index_manifest["full_ready_declared"] is False
    assert resource_audit["source_signatures"]["semantic_inverted_index"]["sha256"] == _sha256(paths["semantic_index"])
    assert no_holdout_audit["status"] == "PASS"


def test_missing_semantic_inverted_index_fails(tmp_path: Path) -> None:
    clean_manifest, views_manifest, output_dir, _paths = _fixture_manifests(tmp_path)
    payload = json.loads(views_manifest.read_text(encoding="utf-8"))
    del payload["outputs"]["semantic_inverted_index"]
    _write_json(views_manifest, payload)

    with pytest.raises(ValueError, match="semantic_inverted_index"):
        build_full_semantic_title_category_manifest(
            clean_manifest_path=clean_manifest,
            lightweight_views_manifest_path=views_manifest,
            output_dir=output_dir,
            enforce_venv=False,
        )


@pytest.mark.parametrize(
    ("path_part", "expected"),
    [
        ("holdout", "Forbidden semantic manifest input"),
        ("amazon_2023_recall_views_10000", "Forbidden semantic manifest input"),
        ("pool1000", "Forbidden semantic manifest input"),
        ("diagnostic_batch", "Forbidden semantic manifest input"),
    ],
)
def test_forbidden_holdout_10k_pool1000_and_diagnostic_batch_paths_fail(tmp_path: Path, path_part: str, expected: str) -> None:
    clean_manifest, views_manifest, output_dir, _paths = _fixture_manifests(tmp_path)
    forbidden_index = tmp_path / path_part / "semantic_index.jsonl"
    _write_text(forbidden_index, '{"token":"phone","item_ids":["i1"]}\n')
    payload = json.loads(views_manifest.read_text(encoding="utf-8"))
    payload["outputs"]["semantic_inverted_index"] = str(forbidden_index)
    _write_json(views_manifest, payload)

    with pytest.raises(ValueError, match=expected):
        build_full_semantic_title_category_manifest(
            clean_manifest_path=clean_manifest,
            lightweight_views_manifest_path=views_manifest,
            output_dir=output_dir,
            enforce_venv=False,
        )


def test_ranking_replacement_marker_fails(tmp_path: Path) -> None:
    clean_manifest, views_manifest, output_dir, _paths = _fixture_manifests(tmp_path)
    payload = json.loads(views_manifest.read_text(encoding="utf-8"))
    payload["ranking_input_replacement_allowed"] = True
    _write_json(views_manifest, payload)

    with pytest.raises(ValueError, match="Ranking replacement marker"):
        build_full_semantic_title_category_manifest(
            clean_manifest_path=clean_manifest,
            lightweight_views_manifest_path=views_manifest,
            output_dir=output_dir,
            enforce_venv=False,
        )
