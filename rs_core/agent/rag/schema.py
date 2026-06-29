from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


def _jsonable(value: Any) -> Any:
    if isinstance(value, set):
        return sorted(value)
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    return value


@dataclass
class RagEvidence:
    item_id: str
    field: str
    text: str
    source: str
    score: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return _jsonable(asdict(self))


@dataclass
class RagContext:
    query: str
    candidate_item_ids: list[str] = field(default_factory=list)
    evidence: list[RagEvidence] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "candidate_item_ids": list(self.candidate_item_ids),
            "evidence": [item.to_dict() for item in self.evidence],
            "metadata": _jsonable(self.metadata),
        }
