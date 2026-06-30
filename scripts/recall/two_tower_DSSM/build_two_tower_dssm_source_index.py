from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rs_core.common.io import iter_jsonl, read_json, write_json
from rs_core.offline.training.two_tower_DSSM.source_manifest import GOVERNANCE_FIELDS, SCHEMA_VERSION, SOURCE_STATUS, validate_two_tower_dssm_source_index_manifest

EXPECTED_ARTIFACT = {
    "source": "two_tower_dssm",
    "canonical_source": "two_tower_dssm",
    "source_name": "two_tower_dssm",
    "variant": "dssm",
    "model_type": "dssm_two_tower_v1",
}
DEFAULT_INDEX_SCOPE = "RECENT_2Y_DERIVED_INDEX"


def build_two_tower_dssm_source_index(
    *,
    training_run_dir: str | Path,
    item_vocab_manifest: str | Path,
    output_dir: str | Path,
    output_source_manifest: str | Path,
    config: str | Path | None = None,
    clean_manifest: str | Path | None = None,
    train_sequence: str | Path | None = None,
    index_scope: str = DEFAULT_INDEX_SCOPE,
    overwrite: bool = False,
) -> dict[str, Any]:
    training_run_dir = _resolve_path(training_run_dir)
    item_vocab_manifest_path = _resolve_path(item_vocab_manifest)
    output_dir = _resolve_path(output_dir)
    output_source_manifest = _resolve_path(output_source_manifest)
    config_path = _resolve_path(config) if config else None
    clean_manifest_path = _resolve_path(clean_manifest) if clean_manifest else None
    train_sequence_path = _resolve_path(train_sequence) if train_sequence else None
    for optional_path in (config_path, clean_manifest_path, train_sequence_path):
        if optional_path is not None and not optional_path.is_file():
            raise FileNotFoundError(str(optional_path))
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
        "source": EXPECTED_ARTIFACT["source"],
        "canonical_source": EXPECTED_ARTIFACT["canonical_source"],
        "source_name": EXPECTED_ARTIFACT["source_name"],
        "variant": EXPECTED_ARTIFACT["variant"],
        "model_type": EXPECTED_ARTIFACT["model_type"],
        "index_scope": index_scope,
        "source_status": SOURCE_STATUS,
        **GOVERNANCE_FIELDS,
        "embedding_path": str(embedding_path),
        "index_path": str(index_path),
        "item_vocab_manifest": str(item_vocab_manifest_path),
        "row_count": row_count,
        "embedding_row_count": embedding_row_count,
        "index_row_count": index_row_count,
        "item_embedding_row_count": embedding_row_count,
        "recall_index_row_count": index_row_count,
        "model_parameters": model.get("model_parameters", {}),
        "artifact_size_gib": round((embedding_path.stat().st_size + index_path.stat().st_size) / 1024**3, 9),
        "content_hash": _content_hash([embedding_path, index_path, item_vocab_manifest_path]),
    }
    if config_path is not None:
        manifest["model_config_sha256"] = _sha256_file(config_path)
    if clean_manifest_path is not None:
        manifest["clean_manifest_sha256"] = _sha256_file(clean_manifest_path)
    if train_sequence_path is not None:
        manifest["train_sequence_sha256"] = _sha256_file(train_sequence_path)
    manifest["item_universe_sha256"] = _sha256_file(item_vocab_manifest_path)
    if user_embedding_path is not None:
        manifest["user_embedding_path"] = str(user_embedding_path)
        manifest["user_embedding_row_count"] = _jsonl_row_count(user_embedding_path)

    tmp_path = output_source_manifest.with_name(f"{output_source_manifest.name}.tmp")
    write_json(tmp_path, manifest)
    validate_two_tower_dssm_source_index_manifest(tmp_path)
    tmp_path.replace(output_source_manifest)
    return read_json(output_source_manifest)


def _assert_expected(field: str, actual: Any) -> None:
    expected = EXPECTED_ARTIFACT[field]
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


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build guarded two_tower_DSSM source_index_manifest.json")
    parser.add_argument("--training-run-dir", required=True)
    parser.add_argument("--item-vocab-manifest", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--output-source-manifest", required=True)
    parser.add_argument("--config")
    parser.add_argument("--clean-manifest")
    parser.add_argument("--train-sequence")
    parser.add_argument("--index-scope", default=DEFAULT_INDEX_SCOPE)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    manifest = build_two_tower_dssm_source_index(
        training_run_dir=args.training_run_dir,
        item_vocab_manifest=args.item_vocab_manifest,
        output_dir=args.output_dir,
        output_source_manifest=args.output_source_manifest,
        config=args.config,
        clean_manifest=args.clean_manifest,
        train_sequence=args.train_sequence,
        index_scope=args.index_scope,
        overwrite=args.overwrite,
    )
    print(json.dumps({"source_index_manifest": args.output_source_manifest, "row_count": manifest["row_count"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
