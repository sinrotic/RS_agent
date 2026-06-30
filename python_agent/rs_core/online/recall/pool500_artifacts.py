from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rs_core.common.io import iter_jsonl
from rs_core.online.recall.candidate_merge import merge_candidates
from rs_core.common.recsys_types import MergedCandidate, RecallCandidate

ORACLE_FIELD_NAMES = {
    "ground_truth",
    "holdout",
    "label",
    "label_binary",
    "target_item",
    "test_item",
    "valid_item",
}
INTERNAL_ARTIFACT_FIELD_NAMES = {
    "agent_thoughts",
    "diagnostic",
    "diagnostics",
    "ranking_evidence",
    "raw_export_trace",
    "source_diagnostics",
    "source_trace",
    "tool_calls",
}
FORBIDDEN_ARTIFACT_FIELD_NAMES = ORACLE_FIELD_NAMES | INTERNAL_ARTIFACT_FIELD_NAMES


@dataclass(frozen=True)
class Pool500ArtifactIndex:
    candidates_path: str
    candidates_by_user: dict[str, list[MergedCandidate]]
    row_count: int
    user_count: int
    source_counts: dict[str, int]

    def candidates_for_user(self, user_id: str, *, seen_items: set[str] | None = None) -> list[MergedCandidate]:
        seen = seen_items or set()
        rows = [candidate for candidate in self.candidates_by_user.get(str(user_id), []) if candidate.item_id not in seen]
        return [_clone_candidate(candidate) for candidate in rows]

    def readiness(self) -> dict[str, Any]:
        return {
            "enabled": True,
            "status": "ready",
            "candidates_path": self.candidates_path,
            "row_count": self.row_count,
            "user_count": self.user_count,
            "source_counts": dict(sorted(self.source_counts.items())),
        }


def load_pool500_artifact_index(
    candidates_path: str | Path,
    *,
    allowed_sources: set[str] | None = None,
    require_non_empty: bool = True,
) -> Pool500ArtifactIndex:
    path = Path(candidates_path)
    if not path.exists():
        raise FileNotFoundError(f"pool500 candidates artifact not found: {path}")
    by_user_raw: dict[str, list[RecallCandidate]] = {}
    source_counts: dict[str, int] = {}
    row_count = 0
    for line_number, row in enumerate(iter_jsonl(path), start=1):
        row_count += 1
        _reject_oracle_fields(row, line_number)
        user_id = _required_text(row, "user_id", line_number)
        item_id = _required_text(row, "item_id", line_number, aliases=("parent_asin",))
        source = _required_text(row, "source", line_number)
        if allowed_sources is not None and source not in allowed_sources:
            continue
        metadata = _metadata(row)
        sources = _sources(row, source, allowed_sources)
        score = _score(row, line_number)
        rank = row.get("rank")
        lineage = metadata.get("pool500_source_lineage")
        if not isinstance(lineage, list):
            lineage = []
        for source_name in sources:
            lineage.append({"source": source_name, "rank": rank, "score": _source_score(row, metadata, source_name, score)})
        metadata["pool500_source_lineage"] = lineage
        metadata.setdefault("pool500_online_artifact", True)
        metadata.setdefault("category", row.get("category") or metadata.get("category") or "")
        for source_name in sources:
            source_counts[source_name] = source_counts.get(source_name, 0) + 1
            candidate_metadata = dict(metadata)
            candidate_metadata[f"{source_name}_rank"] = rank
            by_user_raw.setdefault(user_id, []).append(
                RecallCandidate(
                    item_id=item_id,
                    source=source_name,
                    score=_source_score(row, metadata, source_name, score),
                    category=str(metadata.get("category") or ""),
                    metadata=candidate_metadata,
                )
            )
    if require_non_empty and row_count == 0:
        raise ValueError(f"empty pool500 candidates artifact: {path}")
    candidates_by_user = {
        user_id: merge_candidates(rows)
        for user_id, rows in by_user_raw.items()
    }
    if require_non_empty and not candidates_by_user:
        raise ValueError(f"pool500 candidates artifact has no usable rows after filtering: {path}")
    return Pool500ArtifactIndex(
        candidates_path=str(path),
        candidates_by_user=candidates_by_user,
        row_count=row_count,
        user_count=len(candidates_by_user),
        source_counts=source_counts,
    )


def _required_text(row: dict[str, Any], key: str, line_number: int, *, aliases: tuple[str, ...] = ()) -> str:
    value = row.get(key)
    if value in (None, ""):
        for alias in aliases:
            value = row.get(alias)
            if value not in (None, ""):
                break
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"missing {key} in pool500 candidate row {line_number}")
    return text


def _metadata(row: dict[str, Any]) -> dict[str, Any]:
    metadata = row.get("metadata")
    return dict(metadata) if isinstance(metadata, dict) else {}


def _sources(row: dict[str, Any], source: str, allowed_sources: set[str] | None) -> list[str]:
    raw_sources = row.get("sources")
    if isinstance(raw_sources, list):
        sources = [str(value).strip() for value in raw_sources if str(value or "").strip()]
    else:
        sources = [source]
    if source not in sources:
        sources.insert(0, source)
    if allowed_sources is not None:
        sources = [value for value in sources if value in allowed_sources]
    return sources or [source]


def _score(row: dict[str, Any], line_number: int) -> float:
    try:
        return float(row.get("score", 0.0) or 0.0)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid score in pool500 candidate row {line_number}: {row.get('score')!r}") from exc


def _source_score(row: dict[str, Any], metadata: dict[str, Any], source: str, default: float) -> float:
    source_scores = metadata.get("source_scores")
    if isinstance(source_scores, dict) and source_scores.get(source) not in (None, ""):
        try:
            return float(source_scores[source])
        except (TypeError, ValueError):
            return default
    row_source_scores = row.get("source_scores")
    if isinstance(row_source_scores, dict) and row_source_scores.get(source) not in (None, ""):
        try:
            return float(row_source_scores[source])
        except (TypeError, ValueError):
            return default
    return default


def _reject_oracle_fields(value: Any, line_number: int) -> None:
    fields = _forbidden_fields_in(value)
    if fields:
        raise ValueError(f"pool500 candidate row {line_number} contains evaluation-only or internal fields: {sorted(fields)}")


def _forbidden_fields_in(value: Any) -> set[str]:
    if isinstance(value, dict):
        fields = {str(key) for key in value if str(key) in FORBIDDEN_ARTIFACT_FIELD_NAMES}
        for child in value.values():
            fields.update(_forbidden_fields_in(child))
        return fields
    if isinstance(value, list):
        fields: set[str] = set()
        for child in value:
            fields.update(_forbidden_fields_in(child))
        return fields
    return set()


def _clone_candidate(candidate: MergedCandidate) -> MergedCandidate:
    return MergedCandidate(
        item_id=candidate.item_id,
        sources=list(candidate.sources),
        source_scores=dict(candidate.source_scores),
        category=candidate.category,
        metadata=dict(candidate.metadata),
    )
