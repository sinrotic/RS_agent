from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from rs_core.common.config import load_config

ALLOWED_ARTIFACT_SCHEMA_VERSIONS: Final[frozenset[str]] = frozenset(
    {
        "rs_agent_artifact_manifest_v1",
        "rs_agent_rag_qdrant_manifest_v1",
        "rs_agent_deepfm_shadow_manifest_v1",
    }
)


@dataclass(frozen=True)
class ManifestAdmissionStatus:
    admitted: bool
    artifact_id: str | None = None
    artifact_type: str | None = None
    schema_version: str | None = None
    errors: tuple[str, ...] = ()
    checked_paths: tuple[str, ...] = ()
    governance_tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class RouteRegistryAdmissionStatus:
    admitted: bool
    route_name: str
    errors: tuple[str, ...] = ()
    checked_paths: tuple[str, ...] = ()
    governance_tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class ManifestGate:
    base_dir: Path = field(default_factory=lambda: Path.cwd())

    def evaluate_manifest(self, manifest: dict[str, Any] | str | Path) -> ManifestAdmissionStatus:
        try:
            payload = _load_manifest(manifest)
        except Exception as exc:
            return ManifestAdmissionStatus(admitted=False, errors=(f"manifest load failed: {exc}",))

        errors: list[str] = []
        checked_paths: list[str] = []
        schema_version = _string_or_none(payload.get("schema_version"))
        artifact_id = _string_or_none(payload.get("artifact_id"))
        artifact_type = _string_or_none(payload.get("artifact_type"))
        if not schema_version:
            errors.append("schema_version is required")
        elif schema_version not in ALLOWED_ARTIFACT_SCHEMA_VERSIONS:
            errors.append(f"unsupported schema_version: {schema_version}")
        if not artifact_id:
            errors.append("artifact_id is required")
        if not artifact_type:
            errors.append("artifact_type is required")

        for path_value in _manifest_path_values(payload):
            path = self._resolve(path_value)
            checked_paths.append(str(path))
            path_error = self._path_error(path_value, path)
            if path_error:
                errors.append(path_error)
            elif not path.exists():
                errors.append(f"path does not exist: {path_value}")

        return ManifestAdmissionStatus(
            admitted=not errors,
            artifact_id=artifact_id,
            artifact_type=artifact_type,
            schema_version=schema_version,
            errors=tuple(errors),
            checked_paths=tuple(checked_paths),
            governance_tags=_manifest_governance_tags(payload),
        )

    def evaluate_route_registry_entry(self, route_name: str, entry: dict[str, Any]) -> RouteRegistryAdmissionStatus:
        errors: list[str] = []
        checked_paths: list[str] = []
        for field_name in ("config_paths", "required_output_paths"):
            values = entry.get(field_name, [])
            if values is None:
                values = []
            if not isinstance(values, list):
                errors.append(f"{field_name} must be a list")
                continue
            for path_value in values:
                if not isinstance(path_value, str) or not path_value:
                    errors.append(f"{field_name} entries must be non-empty strings")
                    continue
                path = self._resolve(path_value)
                checked_paths.append(str(path))
                path_error = self._path_error(path_value, path)
                if path_error:
                    errors.append(f"{field_name} {path_error}")
                elif not path.exists():
                    errors.append(f"{field_name} path does not exist: {path_value}")
        return RouteRegistryAdmissionStatus(
            admitted=not errors,
            route_name=route_name,
            errors=tuple(errors),
            checked_paths=tuple(checked_paths),
            governance_tags=_route_governance_tags(entry),
        )

    def evaluate_route_registry(self, registry: dict[str, Any] | str | Path) -> dict[str, RouteRegistryAdmissionStatus]:
        try:
            payload = _load_manifest(registry)
        except Exception as exc:
            return {"<registry>": RouteRegistryAdmissionStatus(admitted=False, route_name="<registry>", errors=(f"registry load failed: {exc}",))}
        routes = payload.get("routes", {})
        if not isinstance(routes, dict):
            return {"<registry>": RouteRegistryAdmissionStatus(admitted=False, route_name="<registry>", errors=("routes must be a mapping",))}
        statuses: dict[str, RouteRegistryAdmissionStatus] = {}
        for name, entry in routes.items():
            if not isinstance(entry, dict):
                statuses[name] = RouteRegistryAdmissionStatus(
                    admitted=False,
                    route_name=name,
                    errors=("route entry must be a mapping",),
                )
                continue
            statuses[name] = self.evaluate_route_registry_entry(name, entry)
        return statuses

    def _resolve(self, path_value: str) -> Path:
        path = Path(path_value)
        if path.is_absolute():
            return path
        return (self.base_dir / path).resolve()

    def _path_error(self, path_value: str, resolved_path: Path) -> str | None:
        raw_path = Path(path_value)
        if raw_path.is_absolute():
            return f"path must be relative to base_dir: {path_value}"
        try:
            resolved_path.relative_to(self.base_dir.resolve())
        except ValueError:
            return f"path escapes base_dir: {path_value}"
        return None


def evaluate_manifest(manifest: dict[str, Any] | str | Path, *, base_dir: str | Path | None = None) -> ManifestAdmissionStatus:
    return ManifestGate(Path(base_dir) if base_dir is not None else Path.cwd()).evaluate_manifest(manifest)


def evaluate_route_registry_entry(route_name: str, entry: dict[str, Any], *, base_dir: str | Path | None = None) -> RouteRegistryAdmissionStatus:
    return ManifestGate(Path(base_dir) if base_dir is not None else Path.cwd()).evaluate_route_registry_entry(route_name, entry)


def _load_manifest(manifest: dict[str, Any] | str | Path) -> dict[str, Any]:
    if isinstance(manifest, dict):
        return manifest
    loaded = load_config(manifest)
    if not isinstance(loaded, dict):
        raise ValueError("manifest must load to a mapping")
    return loaded


def _manifest_path_values(payload: dict[str, Any]) -> tuple[str, ...]:
    values: list[str] = []
    for key in ("path", "serving_config_path", "model_path", "bm25_index_path", "source_manifest_path", "artifact_report_path"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            values.append(value)
    artifact_store = payload.get("artifact_store")
    if isinstance(artifact_store, dict):
        local_path = artifact_store.get("local_path")
        if isinstance(local_path, str) and local_path and local_path not in values:
            values.append(local_path)
    return tuple(values)


def _manifest_governance_tags(payload: dict[str, Any]) -> tuple[str, ...]:
    tags: list[str] = []
    governance = payload.get("governance")
    if isinstance(governance, dict):
        for key in (
            "candidate_generation_allowed",
            "ranking_input_replacement_allowed",
            "promotion_allowed",
            "public_payload_allowed",
            "final_pool500_ready_claimed",
            "no_holdout",
        ):
            if key in governance:
                tags.append(f"{key}={governance[key]}")
    for key in ("serving_allowed", "production_ready_claimed", "diagnostic_only"):
        if key in payload:
            tags.append(f"{key}={payload[key]}")
    if isinstance(payload.get("fallback_policy"), dict):
        tags.append("fallback_policy")
    if isinstance(payload.get("build_policy"), dict):
        tags.append("async_build_policy")
    return tuple(tags)


def _route_governance_tags(entry: dict[str, Any]) -> tuple[str, ...]:
    tags: list[str] = []
    for key in (
        "status",
        "candidate_generation_allowed",
        "ranking_input_replacement_allowed",
        "pool1000_allowed",
        "promotion_allowed",
        "shadow_mode",
        "full_pool500_ready_semantics",
    ):
        if key in entry:
            tags.append(f"{key}={entry[key]}")
    forbidden = entry.get("public_display_forbidden_fields")
    if isinstance(forbidden, list) and forbidden:
        tags.append("public_display_forbidden_fields")
    return tuple(tags)


def _string_or_none(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


__all__ = (
    "ALLOWED_ARTIFACT_SCHEMA_VERSIONS",
    "ManifestAdmissionStatus",
    "RouteRegistryAdmissionStatus",
    "ManifestGate",
    "evaluate_manifest",
    "evaluate_route_registry_entry",
)
