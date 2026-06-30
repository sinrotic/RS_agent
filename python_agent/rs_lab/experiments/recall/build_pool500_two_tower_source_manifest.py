from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from rs_core.common.config import load_config
from rs_core.common.io import iter_jsonl, read_json, write_json
from rs_core.online.recall.candidate_merge import load_two_tower_index
from rs_core.online.recall.vector_index import VectorIndex
from rs_core.workflow.two_tower_training import _load_item_records

ROOT = Path(__file__).resolve().parents[3]
SCHEMA_VERSION = "pool500_two_tower_source_index_manifest_v1"
EXPECTED_VARIANT = "youtube_dnn"
EXPECTED_MODEL_TYPE = "youtube_dnn_two_tower_v1"
EXPECTED_SOURCE_NAME = "two_tower_youtube_dnn"
EXPECTED_INDEX_SCOPE = "FULL_DERIVED_INDEX"
FORBIDDEN_OLD_ARTIFACT = "outputs/training/two_tower/two_tower_training/youtube_dnn/artifact_manifest.json"
FORBIDDEN_SEGMENTS = {
    "holdout",
    "valid",
    "test",
    "lopo",
    "leave_one_positive_out",
    "clean_10000",
    "pool1000",
    "training_smoke",
}
GATE_FIELDS = (
    "candidate_generation_allowed",
    "ranking_input_replacement_allowed",
    "pool1000_allowed",
    "auto_promotion_allowed",
    "promotion_allowed",
    "final_pool500_ready_claimed",
)


def build_pool500_two_tower_source_manifest(
    artifact_manifest: str | Path,
    config: str | Path,
    clean_manifest: str | Path,
    lightweight_views_manifest: str | Path,
    output_path: str | Path,
    user_quality_manifest: str | Path | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    artifact_manifest_path = _resolve_existing_path(artifact_manifest)
    config_path = _resolve_existing_path(config)
    clean_manifest_path = _resolve_existing_path(clean_manifest)
    views_manifest_path = _resolve_existing_path(lightweight_views_manifest)
    user_quality_manifest_path = _resolve_existing_path(user_quality_manifest) if user_quality_manifest else None
    final_path = _resolve_output_path(output_path)

    if final_path.exists() and not overwrite:
        raise ValueError(f"output already exists; pass --overwrite to replace: {final_path}")

    tmp_path = final_path.with_name(f"{final_path.name}.tmp")
    if tmp_path.exists():
        tmp_path.unlink()

    try:
        manifest = _build_manifest_payload(
            artifact_manifest_path=artifact_manifest_path,
            config_path=config_path,
            clean_manifest_path=clean_manifest_path,
            views_manifest_path=views_manifest_path,
            user_quality_manifest_path=user_quality_manifest_path,
        )
        _validate_manifest_payload(manifest)
        write_json(tmp_path, manifest)
        saved_manifest = read_json(tmp_path)
        _validate_manifest_payload(saved_manifest)
        final_path.parent.mkdir(parents=True, exist_ok=True)
        os.replace(tmp_path, final_path)
        return saved_manifest
    except Exception:
        if tmp_path.exists():
            tmp_path.unlink()
        raise


def _build_manifest_payload(
    artifact_manifest_path: Path,
    config_path: Path,
    clean_manifest_path: Path,
    views_manifest_path: Path,
    user_quality_manifest_path: Path | None,
) -> dict[str, Any]:
    artifact = read_json(artifact_manifest_path)
    config = load_config(config_path)
    clean_manifest = read_json(clean_manifest_path)
    views_manifest = read_json(views_manifest_path)
    contract = artifact.get("contract") or {}
    if not isinstance(contract, dict):
        raise ValueError("artifact manifest contract must be a mapping")
    contract_forbidden_matches = _forbidden_matches(contract)
    if contract_forbidden_matches:
        raise ValueError(f"forbidden artifact contract references found: {contract_forbidden_matches}")

    model_path = _resolve_contract_path(artifact_manifest_path, contract.get("model"))
    train_config_path = _resolve_contract_path(artifact_manifest_path, contract.get("train_config"))
    train_metrics_path = _resolve_contract_path(artifact_manifest_path, contract.get("train_metrics"))
    item_embeddings_path = _resolve_contract_path(artifact_manifest_path, contract.get("item_embeddings"))
    user_embeddings_path = _resolve_contract_path(artifact_manifest_path, contract.get("user_embeddings"))
    recall_index_artifact_path = _resolve_contract_path(artifact_manifest_path, contract.get("recall_index"))

    model = read_json(model_path)
    train_metrics = read_json(train_metrics_path)
    train_config = read_json(train_config_path)
    _assert_artifact_contract(artifact, model)

    train_sequence_path = _resolve_manifest_declared_path(clean_manifest_path, clean_manifest, ("train_user_sequences_path", "user_sequences_train_path"), "user_sequences.train.jsonl")
    category_recall_items_path = _resolve_views_output_path(views_manifest_path, views_manifest, "category_recall_items")
    popular_recall_path = _resolve_views_output_path(views_manifest_path, views_manifest, "popular_recall")

    item_embedding_row_count = _jsonl_row_count(item_embeddings_path)
    user_embedding_row_count = _jsonl_row_count(user_embeddings_path)
    recall_index_row_count = _jsonl_row_count(recall_index_artifact_path)
    if user_embedding_row_count <= 0:
        raise ValueError("user_embedding_row_count must be > 0")
    if item_embedding_row_count <= 0 or recall_index_row_count <= 0:
        raise ValueError("item and recall index row counts must be > 0")
    if item_embedding_row_count != recall_index_row_count:
        raise ValueError("item_embedding_row_count must equal recall_index_row_count")

    vector_index = load_two_tower_index(artifact_manifest_path)
    if not isinstance(vector_index, VectorIndex):
        raise ValueError("artifact_manifest must load as VectorIndex")
    if len(vector_index.items) != recall_index_row_count:
        raise ValueError("VectorIndex item count must equal recall_index_row_count")
    if len(vector_index.user_embeddings) != user_embedding_row_count:
        raise ValueError("VectorIndex user embedding count must equal user_embedding_row_count")

    forbidden_scan_targets = {
        "artifact_manifest_path": str(artifact_manifest_path),
        "config_path": str(config_path),
        "clean_manifest_path": str(clean_manifest_path),
        "views_manifest_path": str(views_manifest_path),
        "contract": contract,
        "train_sequence_path": str(train_sequence_path),
        "category_recall_items_path": str(category_recall_items_path),
        "popular_recall_path": str(popular_recall_path),
    }
    if user_quality_manifest_path is not None:
        forbidden_scan_targets["user_quality_manifest_path"] = str(user_quality_manifest_path)
    forbidden_matches = _forbidden_matches(forbidden_scan_targets)
    if forbidden_matches:
        raise ValueError(f"forbidden input references found: {forbidden_matches}")

    manifest: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS",
        "created_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "source": "two_tower",
        "canonical_source": "two_tower",
        "source_name": EXPECTED_SOURCE_NAME,
        "variant": artifact.get("variant"),
        "model_type": model.get("model_type"),
        "index_scope": config.get("index_scope", EXPECTED_INDEX_SCOPE),
        "train_only": True,
        "readiness_status": "MAIN_ROUTE_ARTIFACT_ONLY",
        "main_route_artifact_only": True,
        "recall_index_path": str(artifact_manifest_path),
        "artifact_manifest_path": str(artifact_manifest_path),
        "model_path": str(model_path),
        "train_config_path": str(train_config_path),
        "train_metrics_path": str(train_metrics_path),
        "item_embeddings_path": str(item_embeddings_path),
        "user_embeddings_path": str(user_embeddings_path),
        "raw_recall_index_path": str(recall_index_artifact_path),
        "clean_manifest_path": str(clean_manifest_path),
        "views_manifest_path": str(views_manifest_path),
        "train_sequence_path": str(train_sequence_path),
        "category_recall_items_path": str(category_recall_items_path),
        "popular_recall_path": str(popular_recall_path),
        "clean_manifest_sha256": _sha256_file(clean_manifest_path),
        "train_sequence_sha256": _sha256_file(train_sequence_path),
        "item_universe_sha256": _item_universe_sha256(category_recall_items_path, popular_recall_path),
        "model_config_sha256": _sha256_file(config_path),
        "artifact_manifest_sha256": _sha256_file(artifact_manifest_path),
        "item_embedding_row_count": item_embedding_row_count,
        "user_embedding_row_count": user_embedding_row_count,
        "recall_index_row_count": recall_index_row_count,
        "vector_index_item_count": len(vector_index.items),
        "training_metrics": {
            "training_backend": train_metrics.get("training_backend"),
            "variant": train_metrics.get("variant"),
            "users_with_training_rows": train_metrics.get("users_with_training_rows"),
        },
        "train_config": {
            "variant": train_config.get("variant"),
            "source_name": train_config.get("source_name"),
        },
        "forbidden_inputs_scan": {
            "status": "PASS",
            "forbidden_matches": [],
            "forbidden_segments": sorted(FORBIDDEN_SEGMENTS),
            "forbidden_ready_artifact_paths": [FORBIDDEN_OLD_ARTIFACT],
        },
    }
    manifest.update({field: False for field in GATE_FIELDS})

    if user_quality_manifest_path is not None:
        manifest.update(
            {
                "user_quality_manifest_path": str(user_quality_manifest_path),
                "user_quality_policy_role": "eligibility_policy_not_recall_source",
                "user_quality_included_in_sources": False,
                "user_quality_ready_evidence": False,
            }
        )

    _assert_config_boundaries(config, manifest)
    return manifest


def _assert_artifact_contract(artifact: dict[str, Any], model: dict[str, Any]) -> None:
    if artifact.get("variant") != EXPECTED_VARIANT:
        raise ValueError(f"artifact variant must be {EXPECTED_VARIANT}")
    if artifact.get("source_name") != EXPECTED_SOURCE_NAME:
        raise ValueError(f"artifact source_name must be {EXPECTED_SOURCE_NAME}")
    if model.get("model_type") != EXPECTED_MODEL_TYPE:
        raise ValueError(f"model_type must be {EXPECTED_MODEL_TYPE}")


def _assert_config_boundaries(config: dict[str, Any], manifest: dict[str, Any]) -> None:
    if config.get("source_name") != EXPECTED_SOURCE_NAME:
        raise ValueError(f"config source_name must be {EXPECTED_SOURCE_NAME}")
    if config.get("canonical_source") != "two_tower":
        raise ValueError("config canonical_source must be two_tower")
    if config.get("evaluation_mode") != "train_only":
        raise ValueError("config evaluation_mode must be train_only")
    if manifest.get("index_scope") != EXPECTED_INDEX_SCOPE:
        raise ValueError(f"index_scope must be {EXPECTED_INDEX_SCOPE}")


def _validate_manifest_payload(manifest: dict[str, Any]) -> None:
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("invalid source manifest schema_version")
    if manifest.get("recall_index_path") != manifest.get("artifact_manifest_path"):
        raise ValueError("recall_index_path must point to artifact_manifest_path")
    if manifest.get("variant") != EXPECTED_VARIANT:
        raise ValueError(f"variant must be {EXPECTED_VARIANT}")
    if manifest.get("model_type") != EXPECTED_MODEL_TYPE:
        raise ValueError(f"model_type must be {EXPECTED_MODEL_TYPE}")
    if manifest.get("source_name") != EXPECTED_SOURCE_NAME:
        raise ValueError(f"source_name must be {EXPECTED_SOURCE_NAME}")
    if manifest.get("user_embedding_row_count", 0) <= 0:
        raise ValueError("user_embedding_row_count must be > 0")
    if manifest.get("item_embedding_row_count") != manifest.get("recall_index_row_count"):
        raise ValueError("item_embedding_row_count must equal recall_index_row_count")
    if any(manifest.get(field) is not False for field in GATE_FIELDS):
        raise ValueError("all promotion gate fields must be false")
    scan_payload = {key: value for key, value in manifest.items() if key != "forbidden_inputs_scan"}
    forbidden_matches = _forbidden_matches(scan_payload)
    if forbidden_matches:
        raise ValueError(f"forbidden final manifest references found: {forbidden_matches}")
    if "source_index_manifest_sha256" in manifest:
        raise ValueError("source_index_manifest_sha256 must not be self-referenced in manifest")


def _resolve_existing_path(path: str | Path | None) -> Path:
    if path is None:
        raise ValueError("missing required path")
    resolved = _resolve_path(path)
    if not resolved.exists():
        raise ValueError(f"missing path: {resolved}")
    return resolved


def _resolve_output_path(path: str | Path) -> Path:
    return _resolve_path(path)


def _resolve_path(path: str | Path) -> Path:
    value = Path(path)
    if value.is_absolute():
        return value.resolve()
    return (ROOT / value).resolve()


def _resolve_contract_path(manifest_path: Path, value: Any) -> Path:
    if value is None:
        raise ValueError("artifact contract is missing a required path")
    path = Path(str(value))
    if path.is_absolute():
        resolved = path.resolve()
    elif (manifest_path.parent / path).exists():
        resolved = (manifest_path.parent / path).resolve()
    else:
        resolved = (ROOT / path).resolve()
    if not resolved.exists():
        raise ValueError(f"missing artifact contract path: {resolved}")
    return resolved


def _resolve_manifest_declared_path(manifest_path: Path, manifest: dict[str, Any], keys: tuple[str, ...], fallback_name: str) -> Path:
    for key in keys:
        if manifest.get(key):
            return _resolve_existing_declared_path(manifest_path, manifest[key])
    split_paths = manifest.get("split_paths")
    if isinstance(split_paths, dict) and split_paths.get("train") and fallback_name in str(split_paths["train"]):
        return _resolve_existing_declared_path(manifest_path, split_paths["train"])
    return _resolve_existing_declared_path(manifest_path, manifest_path.parent / fallback_name)


def _resolve_views_output_path(manifest_path: Path, manifest: dict[str, Any], output_key: str) -> Path:
    outputs = manifest.get("outputs") or {}
    if not isinstance(outputs, dict) or not outputs.get(output_key):
        return _resolve_existing_declared_path(manifest_path, manifest_path.parent / f"{output_key}.jsonl")
    return _resolve_existing_declared_path(manifest_path, outputs[output_key])


def _resolve_existing_declared_path(manifest_path: Path, value: Any) -> Path:
    path = Path(str(value))
    candidates = [path] if path.is_absolute() else [manifest_path.parent / path, ROOT / path]
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    raise ValueError(f"declared path does not exist: {value}")


def _jsonl_row_count(path: Path) -> int:
    return sum(1 for _ in iter_jsonl(path))


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _item_universe_sha256(category_recall_items_path: Path, popular_recall_path: Path) -> str:
    records = _load_item_records(category_recall_items_path, popular_recall_path)
    digest = hashlib.sha256()
    for record in sorted(records, key=lambda row: str(row.get("parent_asin") or "")):
        digest.update(json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def _declared_path_values(value: Any) -> list[str]:
    paths: list[str] = []
    for text in _walk_strings(value):
        normalized = text.replace("\\", "/")
        if "/" in normalized or normalized.endswith((".json", ".jsonl", ".parquet")):
            paths.append(text)
    return paths


def _forbidden_matches(payload: Any) -> list[str]:
    matches: list[str] = []
    for value in _walk_strings(payload):
        normalized = value.replace("\\", "/").lower()
        if FORBIDDEN_OLD_ARTIFACT in normalized:
            matches.append(FORBIDDEN_OLD_ARTIFACT)
        parts = [part for part in normalized.split("/") if part]
        for token in FORBIDDEN_SEGMENTS:
            if token in parts or f".{token}." in normalized or f"_{token}_" in normalized:
                matches.append(token)
    return sorted(set(matches))


def _walk_strings(value: Any):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from _walk_strings(str(key))
            yield from _walk_strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_strings(item)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Build pool500 two_tower YouTubeDNN source manifest")
    parser.add_argument("--artifact-manifest", required=True)
    parser.add_argument("--config", required=True)
    parser.add_argument("--clean-manifest", required=True)
    parser.add_argument("--lightweight-views-manifest", required=True)
    parser.add_argument("--output-path", required=True)
    parser.add_argument("--user-quality-manifest")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args(argv)
    manifest = build_pool500_two_tower_source_manifest(
        artifact_manifest=args.artifact_manifest,
        config=args.config,
        clean_manifest=args.clean_manifest,
        lightweight_views_manifest=args.lightweight_views_manifest,
        output_path=args.output_path,
        user_quality_manifest=args.user_quality_manifest,
        overwrite=args.overwrite,
    )
    print(json.dumps({"output_path": str(_resolve_output_path(args.output_path)), "status": manifest["status"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
