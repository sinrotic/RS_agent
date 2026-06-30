from __future__ import annotations

from dataclasses import dataclass, field

from rs_core.agent.runtime_core.definition import AgentDefinition


@dataclass
class AgentRegistry:
    _definitions: dict[str, AgentDefinition] = field(default_factory=dict)

    def register(self, definition: AgentDefinition) -> None:
        name = str(definition.name or "").strip()
        if not name:
            raise ValueError("AgentDefinition.name must not be empty")
        if name in self._definitions:
            raise ValueError(f"Agent already registered: {name}")
        self._definitions[name] = definition

    def get(self, name: str) -> AgentDefinition:
        normalized = str(name or "").strip()
        if not normalized or normalized not in self._definitions:
            raise KeyError(normalized)
        return self._definitions[normalized]

    def definitions(self) -> tuple[AgentDefinition, ...]:
        return tuple(self._definitions.values())
