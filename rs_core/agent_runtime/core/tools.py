from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class ToolSpec:
    """Domain-neutral tool contract.

    Domain-specific fields, such as recommendation routing and SFT visibility
    policy, must live in ``metadata`` and be interpreted by the owning adapter.
    The generic runtime may carry this metadata, but must not branch on it.
    """

    name: str
    description: str
    input_schema: dict[str, Any] = field(default_factory=dict)
    output_schema: dict[str, Any] = field(default_factory=dict)
    read_only: bool = True
    permission: dict[str, Any] | None = None
    mcpInfo: dict[str, Any] | None = None
    inputJSONSchema: dict[str, Any] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
