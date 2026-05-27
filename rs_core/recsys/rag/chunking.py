from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable

_SENTENCE_RE = re.compile(r"(?<=[.!?。！？])\s+")


@dataclass
class RagItemChunk:
    item_id: str
    field: str
    text: str
    source: str = "catalog_bm25"
    metadata: dict[str, Any] = field(default_factory=dict)


DEFAULT_RAG_FIELDS = ["title", "category", "main_category", "summary", "description", "features"]


def chunk_item_record(
    item: dict[str, Any],
    fields: Iterable[str] | None = None,
    max_chunk_chars: int = 400,
    source: str = "catalog_bm25",
) -> list[RagItemChunk]:
    item_id = _item_id(item)
    if not item_id:
        return []

    chunks: list[RagItemChunk] = []
    for field_name in fields or DEFAULT_RAG_FIELDS:
        value = item.get(field_name)
        for index, text in enumerate(_field_chunks(value, max_chunk_chars=max_chunk_chars)):
            chunks.append(
                RagItemChunk(
                    item_id=item_id,
                    field=field_name,
                    text=text,
                    source=source,
                    metadata={"artifact_scope": "candidate_internal", "chunk_index": index},
                )
            )
    return chunks


def _item_id(item: dict[str, Any]) -> str:
    return str(item.get("parent_asin") or item.get("item_id") or item.get("asin") or "").strip()


def _field_chunks(value: Any, max_chunk_chars: int) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [_clip(str(item).strip(), max_chunk_chars) for item in value if str(item).strip()]

    text = str(value).strip()
    if not text:
        return []
    if len(text) <= max_chunk_chars:
        return [text]

    parts = [part.strip() for part in _SENTENCE_RE.split(text) if part.strip()]
    if not parts:
        parts = [text]

    chunks: list[str] = []
    current = ""
    for part in parts:
        if not current:
            current = _clip(part, max_chunk_chars)
        elif len(current) + 1 + len(part) <= max_chunk_chars:
            current = f"{current} {part}"
        else:
            chunks.append(current)
            current = _clip(part, max_chunk_chars)
    if current:
        chunks.append(current)
    return chunks


def _clip(text: str, max_chunk_chars: int) -> str:
    if len(text) <= max_chunk_chars:
        return text
    return text[:max_chunk_chars].rstrip()
