from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rs_core.common.io import iter_jsonl, read_json, write_json
from rs_core.recsys.two_tower_source_manifest import EXPECTED_FIELDS, SCHEMA_VERSION, validate_two_tower_source_index_manifest


def build_two_tower_source_index(
    *,
    training_run_dir: str | Path,
    item_vocab_manifest: str | Path,
    output_dir: str | Path,
    output_source_manifest: str | Path,
    overwrite: bool = False,
) -> dict[str, Any]:
    training_run_dir = _resolve_path(training_run_dir)
    item_vocab_manifest_path = _resolve_path(item_vocab_manifest)
    output_dir = _resolve_path(output_dir)
    output_source_manifest = _resolve_path(output_source_manifest)
    if output_source_manifest.exists() and not overwrite:
        raise FileExistsError(f"output source manifest already exists: {output_source_manifest}")
    artifact_manifest_path = training_run_dir / "artifact_manifest.json"
    artifact = read_json(artifact_manifest_path)
    contract = artifact.get("contract") if isinstance(artifact.get("contract"), dict) else {}
    model_path = _contract_path(artifact_manifest_path, contract.get("model"))
    embedding_path = _contract_path(artifact_manifest_path, contract.get("item_embeddings"))
    index_path = _contract_path(artifact_manifest_path, contract.get("recall_index"))
    user_embedding_path = _contract_path(artifact_manifest_path, contract.get("user_embeddings")) if contract.get("user_embeddings") else None
    model = read_json(model_path)
    item_vocab = read_json(item_vocab_manifest_path)

    _assert_expected("variant", artifact.get("variant"))
    _assert_expected("source_name", artifact.get("source_name"))
    _assert_expected("model_type", model.get("model_type"))
    row_count = int(item_vocab.get("item_count") or 0)
    embedding_row_count = _jsonl_row_count(embedding_path)
    index_row_count = _jsonl_row_count(index_path)
    if row_count <= 0:
        raise ValueError("item_vocab_manifest item_count must be positive")
    if row_count != embedding_row_count or row_count != index_row_count:
        raise ValueError("item vocab, embedding, and index row counts must match")

    output_dir.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "created_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        **EXPECTED_FIELDS,
        "embedding_path": str(embedding_path),
        "index_path": str(index_path),
        "item_vocab_manifest": str(item_vocab_manifest_path),
        "row_count": row_count,
        "embedding_row_count": embedding_row_count,
        "index_row_count": index_row_count,
        "artifact_size_gib": round((embedding_path.stat().st_size + index_path.stat().st_size) / 1024**3, 9),
        "content_hash": _content_hash([embedding_path, index_path, item_vocab_manifest_path]),
    }
    if user_embedding_path is not None:
        manifest["user_embedding_path"] = str(user_embedding_path)
        manifest["user_embedding_row_count"] = _jsonl_row_count(user_embedding_path)
    tmp_path = output_source_manifest.with_name(f"{output_source_manifest.name}.tmp")
    write_json(tmp_path, manifest)
    validate_two_tower_source_index_manifest(tmp_path)
    tmp_path.replace(output_source_manifest)
    return read_json(output_source_manifest)


def _assert_expected(field: str, actual: Any) -> None:
    expected = EXPECTED_FIELDS[field]
    if actual != expected:
        raise ValueError(f"{field} must be {expected}")


def _resolve_path(path: str | Path) -> Path:
    value = Path(path)
    return value.resolve() if value.is_absolute() else (ROOT / value).resolve()


def _contract_path(manifest_path: Path, value: Any) -> Path:
    if not value:
        raise ValueError("artifact manifest contract is missing a required path")
    path = Path(str(value))
    if path.is_absolute():
        resolved = path.resolve()
    elif (manifest_path.parent / path).exists():
        resolved = (manifest_path.parent / path).resolve()
    else:
        resolved = (ROOT / path).resolve()
    if not resolved.is_file():
        raise FileNotFoundError(str(resolved))
    return resolved


def _jsonl_row_count(path: Path) -> int:
    return sum(1 for _ in iter_jsonl(path))


def _content_hash(paths: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in paths:
        digest.update(str(path).encode("utf-8"))
        digest.update(b"\0")
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build guarded two_tower source_index_manifest.json")
    parser.add_argument("--training-run-dir", required=True)
    parser.add_argument("--item-vocab-manifest", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--output-source-manifest", required=True)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    manifest = build_two_tower_source_index(
        training_run_dir=args.training_run_dir,
        item_vocab_manifest=args.item_vocab_manifest,
        output_dir=args.output_dir,
        output_source_manifest=args.output_source_manifest,
        overwrite=args.overwrite,
    )
    print(json.dumps({"source_index_manifest": args.output_source_manifest, "row_count": manifest["row_count"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
