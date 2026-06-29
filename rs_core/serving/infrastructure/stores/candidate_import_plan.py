from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

PROJECT_ROOT = Path(__file__).resolve().parents[4]
SchemaKind = Literal[
    "usercf_candidates",
    "item_neighbors",
    "popular_candidates",
    "category_candidates",
    "user_category_profiles",
    "pool_candidates",
    "unsupported",
]
TargetSchema = Literal[
    "auto",
    "usercf_candidates",
    "item_neighbors",
    "popular_candidates",
    "category_candidates",
    "user_category_profiles",
    "pool_candidates",
]


@dataclass(frozen=True)
class ImportPlan:
    path: Path
    schema: SchemaKind
    rows: list[dict[str, Any]]
    report: dict[str, Any]


def resolve_path(path: Path) -> Path:
    return path if path.is_absolute() else PROJECT_ROOT / path


def plan_jsonl(
    path: Path,
    limit_rows: int,
    *,
    artifact_id: str,
    source_override: str,
    target_schema: TargetSchema = "auto",
    classify_pool_candidates: bool = True,
) -> ImportPlan:
    report: dict[str, Any] = {"path": str(path), "exists": path.exists(), "scanned_rows": 0, "candidate_like_rows": 0, "sources": {}}
    if target_schema != "auto":
        report["target_schema"] = target_schema
    if not path.exists():
        report["status"] = "missing"
        report["schema"] = "unsupported"
        return ImportPlan(path, "unsupported", [], report)

    schema: SchemaKind | None = None
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if limit_rows and report["scanned_rows"] >= limit_rows:
                report["truncated"] = True
                break
            report["scanned_rows"] += 1
            try:
                raw = json.loads(line)
            except json.JSONDecodeError:
                report["json_errors"] = int(report.get("json_errors", 0)) + 1
                continue
            row_schema = classify_row(raw, target_schema=target_schema, classify_pool_candidates=classify_pool_candidates)
            if row_schema == "unsupported":
                report["unsupported_rows"] = int(report.get("unsupported_rows", 0)) + 1
                continue
            if schema is None:
                schema = row_schema
            elif schema != row_schema:
                report["mixed_schema_rows"] = int(report.get("mixed_schema_rows", 0)) + 1
                continue
            normalized = normalize_row(raw, row_schema, artifact_id=artifact_id, source_override=source_override, rank=len(rows) + 1)
            if normalized is None:
                report["unsupported_rows"] = int(report.get("unsupported_rows", 0)) + 1
                continue
            rows.append(normalized)
            report["candidate_like_rows"] += 1

    if schema is None:
        schema = "unsupported"
        report["status"] = "unsupported"
    else:
        rows, duplicate_rows = dedupe_rows(schema, rows)
        if duplicate_rows:
            report["duplicate_rows"] = duplicate_rows
        report["status"] = "supported"
    report["schema"] = schema
    report["importable_rows"] = len(rows)
    report["sources"] = source_counts(rows)
    return ImportPlan(path, schema, rows, report)


def classify_row(row: Any, *, target_schema: TargetSchema = "auto", classify_pool_candidates: bool = True) -> SchemaKind:
    if not isinstance(row, dict):
        return "unsupported"
    if target_schema != "auto":
        return target_schema if row_matches_schema(row, target_schema) else "unsupported"
    if (row.get("src_item") or row.get("src_item_id")) and (row.get("dst_item") or row.get("dst_item_id")):
        return "item_neighbors"
    source = str(row.get("source") or "").strip()
    if source.startswith("popular") and (row.get("parent_asin") or row.get("item_id")):
        return "popular_candidates"
    if source.startswith("category") and (row.get("parent_asin") or row.get("item_id")):
        return "category_candidates"
    if row.get("user_id") and (row.get("parent_asin") or row.get("item_id")):
        return "pool_candidates" if classify_pool_candidates and looks_like_pool_candidate(row) else "usercf_candidates"
    if row.get("user_id") and (row.get("bucket") or row.get("category_bucket")):
        return "user_category_profiles"
    return "unsupported"


def looks_like_pool_candidate(row: dict[str, Any]) -> bool:
    return isinstance(row.get("sources"), list) or isinstance(row.get("source_scores"), dict) or clean_text(row.get("pool_name")).startswith("pool")


def row_matches_schema(row: dict[str, Any], schema: TargetSchema) -> bool:
    if schema == "item_neighbors":
        return bool((row.get("src_item") or row.get("src_item_id")) and (row.get("dst_item") or row.get("dst_item_id")))
    if schema in {"usercf_candidates", "pool_candidates"}:
        return bool(row.get("user_id") and (row.get("parent_asin") or row.get("item_id")))
    if schema in {"popular_candidates", "category_candidates"}:
        return bool(row.get("parent_asin") or row.get("item_id"))
    if schema == "user_category_profiles":
        return bool(row.get("user_id") and (row.get("bucket") or row.get("category_bucket") or row.get("category")))
    return False


def normalize_row(row: dict[str, Any], schema: SchemaKind, *, artifact_id: str, source_override: str, rank: int) -> dict[str, Any] | None:
    if schema == "item_neighbors":
        src_item_id = clean_text(row.get("src_item") or row.get("src_item_id"))
        dst_item_id = clean_text(row.get("dst_item") or row.get("dst_item_id"))
        source = source_for_row(row, source_override, default="item_neighbors", prefer_row_source=True)
        score = score_for_row(row, source)
        if not src_item_id or not dst_item_id or score is None:
            return None
        return common_candidate_row(row, source=source, item_id=dst_item_id, rank=rank, artifact_id=artifact_id) | {"src_item_id": src_item_id, "dst_item_id": dst_item_id, "score": score}
    if schema == "usercf_candidates":
        user_id = clean_text(row.get("user_id"))
        parent_asin = clean_text(row.get("parent_asin") or row.get("item_id"))
        source = source_for_row(row, source_override, default="usercf_recall", prefer_row_source=False)
        score = score_for_row(row, source)
        if not user_id or not parent_asin or score is None:
            return None
        return common_candidate_row(row, source=source, item_id=parent_asin, rank=rank, artifact_id=artifact_id) | {"user_id": user_id, "parent_asin": parent_asin, "score": score}
    if schema == "pool_candidates":
        user_id = clean_text(row.get("user_id"))
        parent_asin = clean_text(row.get("parent_asin") or row.get("item_id"))
        source = source_for_row(row, source_override, default="pool500_fallback", prefer_row_source=True)
        score = score_for_row(row, source)
        if not user_id or not parent_asin or score is None:
            return None
        return common_candidate_row(row, source=source, item_id=parent_asin, rank=rank, artifact_id=artifact_id) | {"user_id": user_id, "parent_asin": parent_asin, "score": score}
    if schema in {"popular_candidates", "category_candidates"}:
        parent_asin = clean_text(row.get("parent_asin") or row.get("item_id"))
        default_source = "popular" if schema == "popular_candidates" else "category"
        source = default_source
        score = score_for_row(row, source_for_row(row, source_override, default=default_source, prefer_row_source=True))
        if not parent_asin or score is None:
            return None
        payload = common_candidate_row(row, source=source, item_id=parent_asin, rank=rank, artifact_id=artifact_id) | {"parent_asin": parent_asin, "score": score}
        raw_source = source_for_row(row, source_override, default=default_source, prefer_row_source=True)
        if raw_source != source:
            payload["metadata"].setdefault("raw_source", raw_source)
        if schema == "popular_candidates":
            payload["scope"] = clean_text(row.get("scope")) or "global"
            payload["bucket"] = clean_text(row.get("bucket"))
        else:
            payload["bucket"] = clean_text(row.get("bucket") or row.get("category_bucket") or row.get("category"))
            if not payload["bucket"]:
                return None
        return payload
    if schema == "user_category_profiles":
        user_id = clean_text(row.get("user_id"))
        bucket = clean_text(row.get("bucket") or row.get("category_bucket") or row.get("category"))
        score = finite_float_or_none(row.get("score"))
        if score is None:
            score = 0.0
        if not user_id or not bucket:
            return None
        return {"user_id": user_id, "bucket": bucket, "score": score, "rank": int_or_default(row.get("rank"), rank), "metadata": metadata_for_row(row)}
    return None


def common_candidate_row(row: dict[str, Any], *, source: str, item_id: str, rank: int, artifact_id: str) -> dict[str, Any]:
    return {"source": source, "parent_asin": item_id, "rank": int_or_default(row.get("rank"), rank), "category": clean_text(row.get("category")), "artifact_id": artifact_id or clean_text(row.get("artifact_id")), "metadata": metadata_for_row(row)}


def batches(rows: list[dict[str, Any]], batch_size: int) -> list[list[dict[str, Any]]]:
    return [rows[index : index + batch_size] for index in range(0, len(rows), batch_size)]


def source_for_row(row: dict[str, Any], override: str, *, default: str, prefer_row_source: bool) -> str:
    if override.strip():
        return override.strip()
    if prefer_row_source and clean_text(row.get("source")):
        return clean_text(row.get("source"))
    sources = row.get("sources")
    if prefer_row_source and isinstance(sources, list) and sources:
        return clean_text(sources[0]) or default
    return default


def score_for_row(row: dict[str, Any], source: str) -> float | None:
    if row.get("score") is not None:
        return finite_float_or_none(row.get("score"))
    source_scores = row.get("source_scores")
    if isinstance(source_scores, dict) and source_scores:
        if source in source_scores:
            return finite_float_or_none(source_scores[source])
        scores = [finite_float_or_none(value) for value in source_scores.values()]
        valid_scores = [score for score in scores if score is not None]
        return max(valid_scores) if valid_scores else None
    return 0.0


def metadata_for_row(row: dict[str, Any]) -> dict[str, Any]:
    metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
    result = dict(metadata)
    if isinstance(row.get("sources"), list):
        result.setdefault("sources", row["sources"])
    if isinstance(row.get("source_scores"), dict):
        result.setdefault("source_scores", row["source_scores"])
    return result


def dedupe_rows(schema: SchemaKind, rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    by_key: dict[tuple[str, ...], dict[str, Any]] = {}
    for row in rows:
        if schema == "item_neighbors":
            key = (str(row["source"]), str(row["src_item_id"]), str(row["dst_item_id"]))
        elif schema == "usercf_candidates":
            key = (str(row["source"]), str(row["user_id"]), str(row["parent_asin"]))
        elif schema == "pool_candidates":
            key = (str(row["user_id"]), str(row["parent_asin"]))
        elif schema == "popular_candidates":
            key = (str(row["source"]), str(row.get("scope", "global")), str(row.get("bucket", "")), str(row["parent_asin"]))
        elif schema == "category_candidates":
            key = (str(row["source"]), str(row["bucket"]), str(row["parent_asin"]))
        elif schema == "user_category_profiles":
            key = (str(row["user_id"]), str(row["bucket"]))
        else:
            key = (str(len(by_key)),)
        by_key[key] = row
    return list(by_key.values()), len(rows) - len(by_key)


def source_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        source = str(row.get("source") or "user_category_profiles")
        counts[source] = counts.get(source, 0) + 1
    return counts


def has_partial_artifact_errors(report: dict[str, Any]) -> bool:
    return bool(report.get("truncated")) or any(int(report.get(key, 0)) > 0 for key in ("json_errors", "mixed_schema_rows", "unsupported_rows"))


def clean_text(value: Any) -> str:
    return str(value or "").strip()


def int_or_default(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def finite_float_or_none(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


_resolve_path = resolve_path
_plan_jsonl = plan_jsonl
_classify_row = classify_row
_normalize_row = normalize_row
_dedupe_rows = dedupe_rows
_has_partial_artifact_errors = has_partial_artifact_errors
_batches = batches
_clean_text = clean_text
_int_or_default = int_or_default
_finite_float_or_none = finite_float_or_none
_source_for_row = source_for_row
_score_for_row = score_for_row
_metadata_for_row = metadata_for_row
