from __future__ import annotations

from rs_core.offline.evaluation.agent_artifact import build_agent_eval_artifact, build_training_signals, write_agent_eval_artifact
from rs_core.offline.evaluation.agent_scorecard import build_agent_scorecard

OFFLINE_EVALUATION_CONTRACT = {
    "owner": "rs_core.offline.evaluation",
    "legacy_import": None,
    "migration_status": "implemented",
    "allowed_execution_modes": ("smoke",),
    "forbidden_actions": ("full_eval", "refresh_artifact"),
}
OFFLINE_DEFERRED_CONTRACT = OFFLINE_EVALUATION_CONTRACT

__all__ = [
    "OFFLINE_DEFERRED_CONTRACT",
    "OFFLINE_EVALUATION_CONTRACT",
    "build_agent_eval_artifact",
    "build_agent_scorecard",
    "build_training_signals",
    "write_agent_eval_artifact",
]
