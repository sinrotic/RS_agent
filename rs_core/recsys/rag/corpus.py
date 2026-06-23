from __future__ import annotations

from typing import Any

RAG_STANDARD_FIELDS = ["title", "category_path", "description", "features"]
RAG_COMPACT_DENSE_FIELD = "compact_text"
RAG_PARENT_PROFILE_FIELD = "parent_profile"
RAG_COMPACT_DENSE_SOURCE_FIELDS = ["title", "category_path", "description", "features", "full_text"]
RAG_PARENT_PROFILE_SOURCE_FIELDS = ["title", "category_path", "store", "average_rating", "rating_number", "features", "description"]
RAG_EXCLUDED_EVIDENCE_FIELDS = {"category", "main_category"}
RAG_DEFAULT_FIELD_WEIGHTS = {
    "title": 0.65,
    "category_path": 1.05,
    "description": 1.35,
    "features": 1.45,
    "compact_text": 1.25,
}
RAG_EVIDENCE_FIELD_QUOTAS = {
    "title": 1,
    "category_path": 1,
    RAG_PARENT_PROFILE_FIELD: 1,
}

_FIELD_SOURCES = {
    "item_id": ("parent_asin", "item_id", "asin"),
    "title": ("title_clean", "title"),
    "category": ("category",),
    "main_category": ("main_category",),
    "category_path": ("categories_path", "category_path", "categories_flat", "source_categories"),
    "description": ("description_text", "description"),
    "features": ("features_text", "features"),
    "summary": ("summary",),
    "full_text": ("item_text", "full_text"),
    "store": ("store", "brand"),
    "average_rating": ("average_rating", "rating", "stars"),
    "rating_number": ("rating_number", "rating_count", "reviews_count"),
}

_PARENT_PROFILE_LABELS = {
    "title": "Title",
    "category_path": "Category",
    "store": "Store",
    "average_rating": "Average rating",
    "rating_number": "Rating count",
    "features": "Features",
    "description": "Description",
    "summary": "Summary",
}
_PARENT_PROFILE_FORBIDDEN_KEY_TOKENS = {
    "diagnostic",
    "eval",
    "future",
    "ground",
    "holdout",
    "item_text",
    "label",
    "oracle",
    "raw",
    "target",
    "test",
    "truth",
    "full_text",
}


def normalize_item_record(item: dict[str, Any]) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for field_name, source_fields in _FIELD_SOURCES.items():
        value = _first_text(item, source_fields)
        if value:
            normalized[field_name] = value

    if not normalized.get("main_category") and normalized.get("category_path"):
        normalized["main_category"] = normalized["category_path"].split(">")[0].strip()
    if not normalized.get("category") and normalized.get("main_category"):
        normalized["category"] = normalized["main_category"]

    return normalized


def source_fields_for(field_name: str, item: dict[str, Any]) -> list[str]:
    if field_name == RAG_COMPACT_DENSE_FIELD:
        normalized = normalize_item_record(item)
        sources: list[str] = []
        for source_field in RAG_COMPACT_DENSE_SOURCE_FIELDS:
            if normalized.get(source_field):
                sources.extend(source_fields_for(source_field, item))
        return list(dict.fromkeys(sources))

    source_fields = _FIELD_SOURCES.get(field_name, (field_name,))
    return [source_field for source_field in source_fields if _has_value(item.get(source_field))]


def build_compact_item_text(item: dict[str, Any], *, max_chars: int = 600) -> str:
    normalized = normalize_item_record(item)
    parts: list[str] = []
    for field_name in RAG_COMPACT_DENSE_SOURCE_FIELDS:
        text = str(normalized.get(field_name) or "").strip()
        if text:
            parts.append(text)
    return _clip_text(" | ".join(dict.fromkeys(parts)), max_chars)


def build_parent_profile_text(
    item: dict[str, Any],
    *,
    fields: list[str] | None = None,
    max_chars: int = 1000,
) -> tuple[str, list[str]]:
    normalized = normalize_item_record(item)
    selected_fields = fields or list(RAG_PARENT_PROFILE_SOURCE_FIELDS)
    parts: list[str] = []
    used_fields: list[str] = []
    for field_name in selected_fields:
        if field_name == "full_text":
            continue
        text = _public_parent_field_text(item, field_name)
        if not text:
            continue
        label = _PARENT_PROFILE_LABELS.get(field_name, field_name.replace("_", " ").title())
        parts.append(f"{label}: {text}")
        used_fields.append(field_name)
    return _clip_text("\n".join(parts), max_chars), used_fields


def _first_text(item: dict[str, Any], source_fields: tuple[str, ...]) -> str:
    for field_name in source_fields:
        value = _stringify(item.get(field_name))
        if value:
            return value
    return ""


def _public_parent_field_text(item: dict[str, Any], field_name: str) -> str:
    for source_field in _FIELD_SOURCES.get(field_name, (field_name,)):
        value = item.get(source_field)
        if not _has_value(value):
            continue
        if _has_forbidden_parent_key(source_field):
            continue
        text = _stringify_public_parent_value(value)
        if text:
            return text
    return ""


def _stringify_public_parent_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return " > ".join(text for item in value if (text := _stringify_public_parent_value(item)))
    if isinstance(value, dict):
        parts: list[str] = []
        for key, item in value.items():
            if _has_forbidden_parent_key(str(key)):
                continue
            text = _stringify_public_parent_value(item)
            if text:
                parts.append(f"{key}: {text}")
        return " ".join(parts).strip()
    return str(value).strip()


def _has_forbidden_parent_key(key: str) -> bool:
    normalized = key.lower().replace("-", "_").replace(" ", "_")
    tokens = {token for token in normalized.replace("/", "_").split("_") if token}
    tokens.add(normalized)
    return bool(tokens & _PARENT_PROFILE_FORBIDDEN_KEY_TOKENS)


def _clip_text(text: str, max_chars: int) -> str:
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip()


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return _stringify_list(value)
    if isinstance(value, dict):
        return " ".join(f"{key}: {_stringify(item)}" for key, item in value.items() if _stringify(item)).strip()
    return str(value).strip()


def _stringify_list(values: list[Any]) -> str:
    parts: list[str] = []
    for value in values:
        text = _stringify(value)
        if text:
            parts.append(text)
    return " > ".join(parts)


def _has_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, list):
        return any(_has_value(item) for item in value)
    if isinstance(value, dict):
        return any(_has_value(item) for item in value.values())
    return bool(str(value).strip())
