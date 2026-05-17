from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = REPO_ROOT / ".omc" / "recall" / "registry" / "recall_experiment_registry.yaml"
SCHEMA_PATH = REPO_ROOT / ".omc" / "recall" / "schema" / "recall_experiment_registry.schema.yaml"
SOURCE_REGISTRY_PATH = REPO_ROOT / ".omc" / "recall" / "registry" / "source_group_registry.yaml"


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as file:
        data = yaml.safe_load(file)
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a YAML mapping")
    return data


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _path_exists(path_value: Any) -> bool:
    return isinstance(path_value, str) and bool(path_value.strip()) and (REPO_ROOT / path_value).exists()


def _mentions_metric(text: Any, metric: str) -> bool:
    if not isinstance(text, str):
        return False
    normalized = text.lower().replace("-", "_")
    aliases = {
        "ltr_score": ["ltr_score", "ltr"],
        "rerank_score": ["rerank_score", "rerank"],
        "ctr": ["ctr"],
        "cvr": ["cvr"],
        "gmv": ["gmv"],
    }
    return any(alias in normalized for alias in aliases.get(metric, [metric.lower()]))


def _metric_key_matches(key: Any, metric: str) -> bool:
    return isinstance(key, str) and _mentions_metric(key, metric)


def _collect_promotion_evidence_metric_keys(value: Any, forbidden_metrics: set[str], path: str = "") -> list[str]:
    if isinstance(value, dict):
        matches = []
        for key, child in value.items():
            child_path = f"{path}.{key}" if path else str(key)
            matches.extend(f"{child_path}:{metric}" for metric in forbidden_metrics if _metric_key_matches(key, metric))
            matches.extend(_collect_promotion_evidence_metric_keys(child, forbidden_metrics, child_path))
        return matches
    if isinstance(value, list):
        matches = []
        for index, child in enumerate(value):
            matches.extend(_collect_promotion_evidence_metric_keys(child, forbidden_metrics, f"{path}[{index}]"))
        return matches
    return []


def _canonical_sources(source_registry: dict[str, Any]) -> set[str]:
    sources = _as_list(source_registry.get("sources"))
    canonical: set[str] = set()
    for source in sources:
        if not isinstance(source, dict):
            continue
        source_id = source.get("source_id")
        if isinstance(source_id, str):
            canonical.add(source_id)
        for alias in _as_list(source.get("source_aliases")):
            if isinstance(alias, str):
                canonical.add(alias)
    return canonical


def _validate_record(
    record: dict[str, Any],
    schema: dict[str, Any],
    canonical_sources: set[str],
) -> list[str]:
    errors: list[str] = []
    experiment_id = record.get("experiment_id", "<unknown>")

    for field in _as_list(schema.get("required_fields")):
        if field not in record:
            errors.append(f"{experiment_id}: missing required field {field}")

    enums = schema.get("enums", {})
    if isinstance(enums, dict):
        for field, allowed_values in enums.items():
            if field in record and record[field] not in set(_as_list(allowed_values)):
                errors.append(f"{experiment_id}: invalid {field}={record[field]!r}")

    allowed_metrics = set(_as_list(record.get("allowed_metrics")))
    forbidden_metrics = set(_as_list(record.get("forbidden_metrics")))
    metric_enums = schema.get("enums", {}) if isinstance(schema.get("enums"), dict) else {}
    schema_allowed_metrics = set(_as_list(metric_enums.get("allowed_metric_names")))
    schema_forbidden_metrics = set(_as_list(metric_enums.get("forbidden_metric_names")))

    overlap = allowed_metrics & forbidden_metrics
    if overlap:
        errors.append(f"{experiment_id}: allowed_metrics and forbidden_metrics overlap: {sorted(overlap)}")

    unknown_allowed = allowed_metrics - schema_allowed_metrics
    if unknown_allowed:
        errors.append(f"{experiment_id}: unknown allowed_metrics: {sorted(unknown_allowed)}")

    missing_forbidden = schema_forbidden_metrics - forbidden_metrics
    if missing_forbidden:
        errors.append(f"{experiment_id}: forbidden_metrics missing ranking/business metrics: {sorted(missing_forbidden)}")

    diagnostic_only_metrics = set(_as_list(record.get("diagnostic_only_metrics")))
    diagnostic_excluded_metrics = set(_as_list(record.get("diagnostic_excluded_metrics")))
    diagnostic_metrics = schema_forbidden_metrics | diagnostic_only_metrics | diagnostic_excluded_metrics
    diagnostic_metric_allowed = allowed_metrics & diagnostic_metrics
    if diagnostic_metric_allowed:
        errors.append(f"{experiment_id}: diagnostic-only metrics cannot be allowed recall gate metrics: {sorted(diagnostic_metric_allowed)}")

    for reason_field in ("decision_reason", "gate_reason"):
        invalid_reason_metrics = sorted(metric for metric in diagnostic_metrics if _mentions_metric(record.get(reason_field), metric))
        if invalid_reason_metrics and record.get("gate_status") != "INVALID_SCOPE_DRIFT":
            errors.append(
                f"{experiment_id}: {reason_field} uses diagnostic-only metrics without INVALID_SCOPE_DRIFT: {invalid_reason_metrics}"
            )

    for evidence_field in ("promotion_required_artifacts", "promotion_evidence", "allowed_evidence"):
        invalid_evidence_metrics = sorted(set(_collect_promotion_evidence_metric_keys(record.get(evidence_field), diagnostic_metrics)))
        if invalid_evidence_metrics:
            errors.append(f"{experiment_id}: {evidence_field} contains diagnostic-only promotion evidence: {invalid_evidence_metrics}")

    for field in ("artifact_manifest_path", "metrics_path"):
        if not _path_exists(record.get(field)):
            errors.append(f"{experiment_id}: {field} does not exist: {record.get(field)!r}")

    if record.get("scope_contract") != "recall_only":
        errors.append(f"{experiment_id}: scope_contract must be recall_only")

    source_name = record.get("source_name")
    if not isinstance(source_name, str) or source_name not in canonical_sources:
        errors.append(f"{experiment_id}: source_name cannot canonicalize through source registry: {source_name!r}")

    if record.get("lane") == "promotion":
        manifest_path = record.get("artifact_manifest_path")
        manifest = _load_yaml(REPO_ROOT / manifest_path) if isinstance(manifest_path, str) else {}
        required_paths = _as_list(schema.get("promotion_required_paths"))
        path_sources = []
        for section in ("promotion_required_paths", "source_artifact_paths"):
            section_value = manifest.get(section)
            if isinstance(section_value, dict):
                path_sources.append(section_value)
        for required_path_name in required_paths:
            if not any(_path_exists(paths.get(required_path_name)) for paths in path_sources):
                errors.append(f"{experiment_id}: promotion lane missing required artifact {required_path_name}")

    return errors


def main() -> int:
    schema = _load_yaml(SCHEMA_PATH)
    registry = _load_yaml(REGISTRY_PATH)
    source_registry = _load_yaml(SOURCE_REGISTRY_PATH)
    canonical_sources = _canonical_sources(source_registry)

    errors: list[str] = []
    records = _as_list(registry.get("records"))
    if not records:
        errors.append("recall registry has no records")

    for record in records:
        if not isinstance(record, dict):
            errors.append("registry record must be a mapping")
            continue
        errors.extend(_validate_record(record, schema, canonical_sources))

    if errors:
        print("Recall registry validation failed:")
        for error in errors:
            print(f"- {error}")
        return 1

    print(f"Recall registry validation passed: {len(records)} record(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
