from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from rs_core.recsys.types import MergedCandidate


@dataclass(frozen=True)
class FallbackCandidate:
    item_id: str
    score: float
    fallback_source: str
    canonical_source: str
    category: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass
class FallbackCompletionContext:
    seed_meta_by_item: dict[str, dict[str, Any]]
    seed_keys_by_user: dict[str, dict[str, set[str]]]
    category_recall_index: dict[str, list[dict[str, Any]]]
    category_top_index: dict[str, list[dict[str, Any]]]
    metadata_neighbor_index: dict[str, list[dict[str, Any]]]
    semantic_token_index: dict[str, list[dict[str, Any]]]
    global_popular_items: list[dict[str, Any]]
    resource_audit: dict[str, Any]


@dataclass
class FallbackCompletionResult:
    user_id: str
    candidates: list[MergedCandidate]
    audit_input: dict[str, Any]
    added_candidates: list[MergedCandidate]
    source_contribution: dict[str, int]


@dataclass(frozen=True)
class FallbackInputPaths:
    train_user_sequences: Path
    canonical_items: Path
    category_recall_items: Path
    category_top_items: Path
    popular_recall: Path
    semantic_inverted_index: Path | None = None
