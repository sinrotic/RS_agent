from __future__ import annotations

from dataclasses import dataclass

READY = "READY"
DIAGNOSTIC_ONLY = "DIAGNOSTIC_ONLY"
DEFERRED = "DEFERRED"


@dataclass(frozen=True)
class RecallSourceSpec:
    name: str
    readiness: str
    role: str
    eligible_user_policy: str
    method_doc: str
    latest_artifact: str
    latest_row_count: int
    candidate_generating: bool = True
    ranking_input_replacement_allowed: bool = False

    @property
    def is_ready(self) -> bool:
        return self.readiness == READY
