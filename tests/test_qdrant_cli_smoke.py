from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


def test_build_qdrant_rag_index_cli_dry_run(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    items_path = tmp_path / "canonical_items.jsonl"
    items_path.write_text('{"parent_asin":"i1","title":"soft sofa"}\n', encoding="utf-8")
    manifest_path = tmp_path / "rag_manifest.json"

    from scripts.recall import build_qdrant_rag_index

    manifest = build_qdrant_rag_index.main(
        [
            "--items",
            str(items_path),
            "--collection-name",
            "cli_rag_dry_run",
            "--manifest",
            str(manifest_path),
            "--fields",
            "title",
            "--limit-items",
            "1",
            "--dry-run",
        ]
    )

    assert manifest["dry_run"] is True
    assert manifest["chunk_count"] == 1
    assert manifest_path.is_file()


def test_build_qdrant_two_tower_index_cli_dry_run(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    from tests.test_qdrant_two_tower_build import _write_youtube_source_manifest

    manifest_path = _write_youtube_source_manifest(tmp_path)
    output_manifest = tmp_path / "two_tower_qdrant_manifest.json"

    from scripts.recall import build_qdrant_two_tower_index

    manifest = build_qdrant_two_tower_index.main(
        [
            "--source-index-manifest",
            str(manifest_path),
            "--collection-name",
            "cli_two_tower_dry_run",
            "--manifest",
            str(output_manifest),
            "--limit-items",
            "1",
            "--dry-run",
        ]
    )

    assert manifest["dry_run"] is True
    assert manifest["selected_item_count"] == 1
    assert output_manifest.is_file()
