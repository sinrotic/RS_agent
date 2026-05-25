from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rs_core.common.io import read_json, write_json
from rs_core.recsys.two_tower_source_manifest import validate_two_tower_source_index_manifest
from rs_lab.experiments.recall.run_full_data_pool500_recall_only import (
    DEFAULT_LIGHTWEIGHT_VIEWS_MANIFEST,
    DEFAULT_SOURCE_MANIFESTS,
    DEFAULT_USERCF_SIDECAR_MANIFEST,
    _resolve_view_outputs,
)

RECALL_LAYER_SHADOW_AUDIT_SCHEMA_VERSION = "recall_layer_shadow_audit_v1"
RECALL_LAYER_SOURCE_REGISTRY = {
    "itemcf_weak": {"layer": "source_artifact", "upstream_layer": "method_dataset", "legacy_custom_manifest_allowed": True},
    "itemcf_strong": {"layer": "source_artifact", "upstream_layer": "method_dataset", "legacy_custom_manifest_allowed": True},
    "usercf_recall": {"layer": "source_artifact", "upstream_layer": "method_dataset"},
    "swing_recall": {"layer": "source_artifact", "upstream_layer": "method_dataset"},
    "semantic_title_category_expansion": {"layer": "source_artifact", "upstream_layer": "method_dataset"},
    "co_visit_fallback_repair": {"layer": "source_artifact", "upstream_layer": "method_dataset"},
    "two_tower": {"layer": "source_artifact", "upstream_layer": "method_dataset", "strict_validator": "two_tower_source_index_v1"},
    "popular": {"layer": "source_artifact", "upstream_layer": "governance_train_only", "fallback_view_source": True, "view_output_keys": ("popular_recall",)},
    "category": {"layer": "source_artifact", "upstream_layer": "governance_train_only", "fallback_view_source": True, "view_output_keys": ("category_recall_items", "category_top_items")},
}


def run_recall_layer_shadow_audit(
    *,
    lightweight_views_manifest_path: Path = DEFAULT_LIGHTWEIGHT_VIEWS_MANIFEST,
    source_manifest_paths: dict[str, Path] | None = None,
    usercf_sidecar_manifest_path: Path = DEFAULT_USERCF_SIDECAR_MANIFEST,
    output_path: Path | None = None,
) -> dict[str, Any]:
    audit = build_recall_layer_shadow_audit(
        lightweight_views_manifest_path=lightweight_views_manifest_path,
        source_manifest_paths=source_manifest_paths,
        usercf_sidecar_manifest_path=usercf_sidecar_manifest_path,
    )
    if output_path is not None:
        write_json(output_path, audit)
    return audit


def build_recall_layer_shadow_audit(
    *,
    lightweight_views_manifest_path: Path = DEFAULT_LIGHTWEIGHT_VIEWS_MANIFEST,
    source_manifest_paths: dict[str, Path] | None = None,
    usercf_sidecar_manifest_path: Path = DEFAULT_USERCF_SIDECAR_MANIFEST,
) -> dict[str, Any]:
    manifest_paths = _source_manifest_paths(source_manifest_paths, usercf_sidecar_manifest_path)
    views_manifest_path = _resolve_repo_path(lightweight_views_manifest_path)
    views_manifest = read_json(views_manifest_path) if views_manifest_path.is_file() else {}
    view_outputs = _resolve_view_outputs(views_manifest) if views_manifest else {}
    sources = {}
    blocked_sources = []
    for source, registry in sorted(RECALL_LAYER_SOURCE_REGISTRY.items()):
        entry = _recall_layer_source_audit_entry(source, registry, manifest_paths, views_manifest_path, views_manifest, view_outputs)
        sources[source] = entry
        if entry["status"] == "AUDIT_BLOCKED":
            blocked_sources.append(source)
    return {
        "schema_version": RECALL_LAYER_SHADOW_AUDIT_SCHEMA_VERSION,
        "status": "AUDIT_BLOCKED" if blocked_sources else "PASS",
        "scope": "shadow_audit_only",
        "runtime_gate": False,
        "candidate_generation_changed": False,
        "sources": sources,
        "blocked_sources": blocked_sources,
    }


def _source_manifest_paths(overrides: dict[str, Path] | None, usercf_sidecar_manifest_path: Path) -> dict[str, Path]:
    paths = dict(DEFAULT_SOURCE_MANIFESTS)
    paths["usercf_recall"] = usercf_sidecar_manifest_path
    for source, path in (overrides or {}).items():
        paths[str(source)] = Path(path)
    return paths


def _resolve_repo_path(value: Any) -> Path:
    path = Path(str(value))
    return path if path.is_absolute() else ROOT / path


def _recall_layer_source_audit_entry(
    source: str,
    registry: dict[str, Any],
    manifest_paths: dict[str, Path],
    views_manifest_path: Path,
    views_manifest: dict[str, Any],
    view_outputs: dict[str, Path],
) -> dict[str, Any]:
    is_view_source = bool(registry.get("fallback_view_source"))
    manifest_path = views_manifest_path if is_view_source else _resolve_repo_path(manifest_paths[source])
    manifest_exists = manifest_path.is_file()
    manifest: dict[str, Any] = {}
    blockers = []
    if manifest_exists:
        if is_view_source:
            manifest = _view_source_manifest_fragment(source, registry, views_manifest, view_outputs)
        elif source == "two_tower":
            try:
                manifest = validate_two_tower_source_index_manifest(manifest_path)
            except Exception as exc:
                blockers.append({"code": "TWO_TOWER_SOURCE_MANIFEST_INVALID", "message": str(exc)})
                try:
                    manifest = read_json(manifest_path)
                except Exception:
                    manifest = {}
        else:
            manifest = read_json(manifest_path)
    else:
        blockers.append({"code": "MISSING_MANIFEST", "path": str(manifest_path)})
    if manifest and not is_view_source:
        manifest_source = str(manifest.get("source") or manifest.get("canonical_source") or source)
        if manifest_source != source:
            blockers.append({"code": "SOURCE_MANIFEST_MISMATCH", "expected": source, "actual": manifest_source})
    artifact_paths = _recall_layer_artifact_paths(manifest, manifest_path) if manifest else []
    if is_view_source:
        missing_outputs = [str(path) for path in artifact_paths if not path.is_file()]
        if missing_outputs:
            blockers.append({"code": "MISSING_VIEW_OUTPUT", "paths": missing_outputs})
    forbidden_scan = _recall_layer_forbidden_scan(source, registry["layer"], manifest, manifest_path, artifact_paths)
    if forbidden_scan["matches"]:
        blockers.append({"code": "FORBIDDEN_EVAL_DIAGNOSTIC_LEAKAGE", "matches": forbidden_scan["matches"]})
    diagnostic_state = _recall_layer_diagnostic_state(manifest, artifact_paths)
    legacy_state = _recall_layer_legacy_state(source, manifest_path, registry)
    if diagnostic_state["diagnostic_only"]:
        blockers.append({"code": "DIAGNOSTIC_SOURCE_ARTIFACT", "evidence": diagnostic_state["evidence"]})
    return {
        "source": source,
        "layer": registry["layer"],
        "upstream_layer": registry["upstream_layer"],
        "manifest_path": str(manifest_path),
        "existing_status": "EXISTS" if manifest_exists else "MISSING",
        "qualification": _recall_layer_qualification(registry, manifest, is_view_source),
        "diagnostic_state": diagnostic_state,
        "legacy_state": legacy_state,
        "forbidden_scan": forbidden_scan,
        "status": "AUDIT_BLOCKED" if blockers else "PASS",
        "blockers": blockers,
    }


def _view_source_manifest_fragment(source: str, registry: dict[str, Any], views_manifest: dict[str, Any], view_outputs: dict[str, Path]) -> dict[str, Any]:
    output_keys = tuple(registry.get("view_output_keys") or ())
    return {
        "source": source,
        "source_type": "fallback_view_source",
        "outputs": {key: str(view_outputs[key]) for key in output_keys if key in view_outputs},
        "source_clean_dir": views_manifest.get("source_clean_dir"),
    }


def _recall_layer_artifact_paths(manifest: dict[str, Any], manifest_path: Path) -> list[Path]:
    paths = []
    for value in _walk_json_values(manifest):
        if not isinstance(value, str) or not _looks_like_artifact_path(value):
            continue
        path = Path(value)
        if not path.is_absolute():
            path = manifest_path.parent / path
        paths.append(path)
    return paths


def _recall_layer_forbidden_scan(source: str, layer: str, manifest: dict[str, Any], manifest_path: Path, artifact_paths: list[Path]) -> dict[str, Any]:
    matches = []
    if layer in {"method_dataset", "source_artifact"}:
        for key_path, value in _walk_json_items(manifest):
            key = key_path[-1].lower() if key_path else ""
            if _forbidden_recall_layer_field(key):
                matches.append({"kind": "field", "path": ".".join(key_path), "value": key_path[-1]})
            if isinstance(value, str) and _looks_like_artifact_path(value) and _forbidden_recall_layer_path(Path(value)):
                matches.append({"kind": "path", "path": ".".join(key_path), "value": value})
    for path in [manifest_path, *artifact_paths]:
        if _forbidden_recall_layer_path(path):
            matches.append({"kind": "path", "path": "artifact_path", "value": str(path)})
    return {
        "source": source,
        "policy": "block eval/diagnostic label/hit/oracle leakage in method_dataset or source_artifact references",
        "allowed_train_only_fields": ["recent_positive_item_sequence", "recent_strong_positive_item_sequence"],
        "matches": matches,
    }


def _forbidden_recall_layer_field(key: str) -> bool:
    if key in {"recent_positive_item_sequence", "recent_strong_positive_item_sequence"}:
        return False
    return any(token in key for token in ("eval_label", "label_artifact", "label_derived", "oracle", "hit"))


def _forbidden_recall_layer_path(path: Path) -> bool:
    parts = [part.lower() for part in path.parts]
    joined = "/".join(parts)
    return any(token in parts or token in joined for token in ("eval_diagnostic", "diagnostic", "oracle", "label_artifact", "hit_artifact"))


def _recall_layer_diagnostic_state(manifest: dict[str, Any], artifact_paths: list[Path]) -> dict[str, Any]:
    evidence = []
    for key in ("diagnostic_only", "source_status", "status", "index_scope"):
        value = manifest.get(key)
        if value is True or "diagnostic" in str(value).lower():
            evidence.append({"field": key, "value": value})
    for path in artifact_paths:
        if "diagnostic" in str(path).replace("\\", "/").lower():
            evidence.append({"field": "artifact_path", "value": str(path)})
    return {"diagnostic_only": bool(evidence), "evidence": evidence}


def _recall_layer_legacy_state(source: str, manifest_path: Path, registry: dict[str, Any]) -> dict[str, Any]:
    lowered = str(manifest_path).replace("\\", "/").lower()
    legacy = bool(registry.get("legacy_custom_manifest_allowed")) or "custom_dataset" in lowered or "legacy" in lowered
    return {"legacy_or_custom": legacy, "allowed": bool(registry.get("legacy_custom_manifest_allowed"))}


def _recall_layer_qualification(registry: dict[str, Any], manifest: dict[str, Any], is_view_source: bool) -> dict[str, Any]:
    return {
        "train_only_declared": True if is_view_source else manifest.get("train_only") is True,
        "fallback_view_source": is_view_source,
        "legacy_custom_manifest_allowed": bool(registry.get("legacy_custom_manifest_allowed")),
        "strict_validator": registry.get("strict_validator"),
    }


def _walk_json_items(value: Any, prefix: tuple[str, ...] = ()):
    if isinstance(value, dict):
        for key, item in value.items():
            key_path = (*prefix, str(key))
            yield key_path, item
            yield from _walk_json_items(item, key_path)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _walk_json_items(item, (*prefix, str(index)))


def _walk_json_values(value: Any):
    if isinstance(value, dict):
        for key, item in value.items():
            yield str(key)
            yield from _walk_json_values(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_json_values(item)
    else:
        yield value


def _looks_like_artifact_path(value: str) -> bool:
    normalized = value.replace("\\", "/")
    return "/" in normalized or normalized.endswith((".json", ".jsonl", ".parquet", ".npy", ".faiss", ".yaml", ".yml"))
