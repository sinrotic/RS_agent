from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Iterable, Iterator

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.data.download_and_clean_amazon import DATASET_BASE_URL, SCHEMA_VERSION, iter_remote_jsonl


DEFAULT_MANIFEST = "data/processed/amazon_2023_base/manifest.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backfill Amazon Reviews 2023 metadata.base.jsonl with upstream images.")
    parser.add_argument("--manifest", default=DEFAULT_MANIFEST)
    parser.add_argument("--categories", nargs="+", default=None, help="Optional category filter, e.g. Electronics Office_Products.")
    parser.add_argument("--limit", type=int, default=None, help="Limit rows per selected metadata file for dry-run smoke checks.")
    parser.add_argument("--dry-run", action="store_true", help="Report image coverage without rewriting files.")
    return parser.parse_args()


def metadata_data_url(category: str) -> str:
    return f"{DATASET_BASE_URL}/raw/meta_categories/meta_{category}.jsonl"


def load_manifest(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"manifest not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def selected_outputs(manifest: dict[str, Any], manifest_path: Path, categories: list[str] | None) -> list[dict[str, Any]]:
    wanted = set(categories or [])
    outputs: list[dict[str, Any]] = []
    for output in manifest.get("outputs", []):
        category = str(output.get("category") or "")
        if wanted and category not in wanted:
            continue
        metadata_path = resolve_manifest_path(manifest_path, output.get("metadata_path"))
        outputs.append({"category": category, "metadata_path": metadata_path})
    if wanted and {output["category"] for output in outputs} != wanted:
        found = {output["category"] for output in outputs}
        missing = sorted(wanted - found)
        raise ValueError(f"categories not found in manifest: {missing}")
    return outputs


def resolve_manifest_path(manifest_path: Path, value: Any) -> Path:
    path = Path(str(value))
    if path.is_absolute():
        return path
    return (manifest_path.parent / path).resolve()


def iter_jsonl(path: Path, limit: int | None = None) -> Iterable[tuple[int, dict[str, Any]]]:
    with path.open("r", encoding="utf-8") as f:
        seen = 0
        for line_number, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            if limit is not None and seen >= limit:
                break
            seen += 1
            yield line_number, json.loads(line)


def iter_upstream_metadata(category: str) -> Iterator[dict[str, Any]]:
    yield from iter_remote_jsonl(metadata_data_url(category))


def parent_asins_in_metadata(path: Path, *, limit: int | None) -> set[str]:
    return {str(record.get("parent_asin") or "") for _, record in iter_jsonl(path, limit=limit) if record.get("parent_asin")}


def image_lookup_for_category(category: str, wanted_parent_asins: set[str]) -> tuple[dict[str, list[dict[str, Any]]], int]:
    remaining = set(wanted_parent_asins)
    images_by_parent: dict[str, list[dict[str, Any]]] = {}
    upstream_rows_seen = 0
    if not remaining:
        return images_by_parent, upstream_rows_seen

    for record in iter_upstream_metadata(category):
        upstream_rows_seen += 1
        parent_asin = str(record.get("parent_asin") or "")
        if parent_asin in remaining:
            images_by_parent[parent_asin] = record.get("images") or []
            remaining.remove(parent_asin)
            if not remaining:
                break
    return images_by_parent, upstream_rows_seen


def backfill_metadata_images(category: str, path: Path, *, limit: int | None, dry_run: bool) -> dict[str, Any]:
    if limit is not None and not dry_run:
        raise ValueError("--limit is only allowed with --dry-run to avoid truncating metadata files")

    total_rows = 0
    rows_with_images = 0
    rows_missing_upstream = 0
    rows_changed = 0
    wanted_parent_asins = parent_asins_in_metadata(path, limit=limit if dry_run else None)
    images_by_parent, upstream_rows_seen = image_lookup_for_category(category, wanted_parent_asins)

    def merged_images(record: dict[str, Any]) -> tuple[bool, list[dict[str, Any]]]:
        parent_asin = str(record.get("parent_asin") or "")
        if parent_asin in images_by_parent:
            return True, images_by_parent[parent_asin]
        return False, record.get("images") or []

    if dry_run:
        for _, record in iter_jsonl(path, limit=limit):
            total_rows += 1
            found, images = merged_images(record)
            if not found:
                rows_missing_upstream += 1
            if images:
                rows_with_images += 1
            if record.get("images") != images:
                rows_changed += 1
    else:
        tmp_path: Path | None = None
        try:
            with NamedTemporaryFile("w", encoding="utf-8", delete=False, dir=path.parent, newline="\n") as tmp:
                tmp_path = Path(tmp.name)
                for _, record in iter_jsonl(path):
                    total_rows += 1
                    found, images = merged_images(record)
                    if not found:
                        rows_missing_upstream += 1
                    if images:
                        rows_with_images += 1
                    if record.get("images") != images:
                        rows_changed += 1
                    record["images"] = images
                    tmp.write(json.dumps(record, ensure_ascii=False) + "\n")
            tmp_path.replace(path)
        except Exception:
            if tmp_path is not None:
                tmp_path.unlink(missing_ok=True)
            raise

    return {
        "metadata_path": str(path),
        "total_rows": total_rows,
        "upstream_rows_seen": upstream_rows_seen,
        "rows_with_images": rows_with_images,
        "rows_missing_upstream": rows_missing_upstream,
        "rows_changed": rows_changed,
        "dry_run": dry_run,
    }


def update_json_schema_version(path: Path, *, dry_run: bool) -> None:
    if dry_run or not path.exists():
        return
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["schema_version"] = SCHEMA_VERSION
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()
    manifest_path = Path(args.manifest)
    manifest = load_manifest(manifest_path)
    outputs = selected_outputs(manifest, manifest_path, list(args.categories) if args.categories else None)

    reports = []
    for output in outputs:
        reports.append(
            {
                "category": output["category"],
                **backfill_metadata_images(
                    output["category"],
                    output["metadata_path"],
                    limit=args.limit,
                    dry_run=bool(args.dry_run),
                ),
            }
        )
    update_json_schema_version(manifest_path, dry_run=bool(args.dry_run))
    update_json_schema_version(manifest_path.parent / "stats.json", dry_run=bool(args.dry_run))
    print(json.dumps({"schema_version": SCHEMA_VERSION, "reports": reports}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
