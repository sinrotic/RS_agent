from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.data import backfill_amazon_base_images as backfill


def write_jsonl(path: Path, records: list[dict[str, object]]) -> None:
    path.write_text("".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records), encoding="utf-8")


def read_jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def test_backfill_rejects_limit_in_write_mode(tmp_path: Path) -> None:
    metadata_path = tmp_path / "metadata.base.jsonl"
    write_jsonl(metadata_path, [{"parent_asin": "B001", "title": "Desk lamp"}, {"parent_asin": "B002", "title": "Pen"}])

    with pytest.raises(ValueError, match="--limit is only allowed with --dry-run"):
        backfill.backfill_metadata_images("Office_Products", metadata_path, limit=1, dry_run=False)

    assert len(read_jsonl(metadata_path)) == 2


def test_backfill_preserves_existing_images_when_upstream_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    metadata_path = tmp_path / "metadata.base.jsonl"
    existing_images = [{"variant": "MAIN", "large": "https://example.test/existing.jpg"}]
    write_jsonl(metadata_path, [{"parent_asin": "B001", "title": "Desk lamp", "images": existing_images}])

    monkeypatch.setattr(backfill, "iter_upstream_metadata", lambda category: iter([]))

    report = backfill.backfill_metadata_images("Office_Products", metadata_path, limit=None, dry_run=False)

    assert report["rows_missing_upstream"] == 1
    assert read_jsonl(metadata_path)[0]["images"] == existing_images


def test_backfill_streams_upstream_images_into_metadata(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    metadata_path = tmp_path / "metadata.base.jsonl"
    write_jsonl(metadata_path, [{"parent_asin": "B001", "title": "Desk lamp"}, {"parent_asin": "B003", "title": "Pen"}])
    upstream = [
        {"parent_asin": "B001", "images": [{"variant": "MAIN", "large": "https://example.test/1.jpg"}]},
        {"parent_asin": "B002", "images": [{"variant": "MAIN", "large": "https://example.test/2.jpg"}]},
        {"parent_asin": "B003", "images": []},
    ]
    monkeypatch.setattr(backfill, "iter_upstream_metadata", lambda category: iter(upstream))

    report = backfill.backfill_metadata_images("Office_Products", metadata_path, limit=None, dry_run=False)

    records = read_jsonl(metadata_path)
    assert report["total_rows"] == 2
    assert report["rows_with_images"] == 1
    assert records[0]["images"] == [{"variant": "MAIN", "large": "https://example.test/1.jpg"}]
    assert records[1]["images"] == []


def test_update_json_schema_version_updates_existing_file(tmp_path: Path) -> None:
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps({"schema_version": "1.0", "outputs": []}), encoding="utf-8")

    backfill.update_json_schema_version(path, dry_run=False)

    assert json.loads(path.read_text(encoding="utf-8"))["schema_version"] == backfill.SCHEMA_VERSION
