from __future__ import annotations

from rs_core.offline.evaluation.agent_artifact import build_agent_eval_artifact, build_training_signals, write_agent_eval_artifact
from rs_core.offline.evaluation.agent_scorecard import build_agent_scorecard
from rs_core.offline.evaluation.ranking import (
    build_ranking_experiment_registry_entry,
    build_ranking_feature_contract,
    build_ranking_gpu_resource_summary,
    build_ranking_method_registry_entry,
    compare_frozen_candidate_artifacts,
    compare_frozen_candidate_signatures,
    evaluate,
    frozen_candidate_artifact,
    frozen_candidate_signature,
    heldout_positives,
    inspect_physical_ranking_pipeline_artifacts,
    inspect_ranking_run_artifacts,
    strict_ranking_promotion_status,
    terminal_ranking_promotion_gate,
)

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
    "build_ranking_experiment_registry_entry",
    "build_ranking_feature_contract",
    "build_ranking_gpu_resource_summary",
    "build_ranking_method_registry_entry",
    "compare_frozen_candidate_artifacts",
    "compare_frozen_candidate_signatures",
    "evaluate",
    "frozen_candidate_artifact",
    "frozen_candidate_signature",
    "heldout_positives",
    "inspect_physical_ranking_pipeline_artifacts",
    "inspect_ranking_run_artifacts",
    "strict_ranking_promotion_status",
    "terminal_ranking_promotion_gate",
    "write_agent_eval_artifact",
]
