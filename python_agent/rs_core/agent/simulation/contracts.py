from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AgentSimulationSandboxContract:
    schema_version: str = "rs_agent_simulation_sandbox_contract_v1"
    owner: str = "rs_core.agent.simulation"
    purpose: str = "agent_behavior_sandbox"
    offline_boundary: str = "rs_core.offline.simulation"
    canonical_entrypoints: tuple[str, ...] = (
        "rs_core.agent.simulation.run_simulation_scene",
        "rs_core.agent.simulation.run_simulation_batch",
    )
    service_entrypoints: tuple[str, ...] = (
        "/simulation/scene",
        "/simulation/batch",
    )
    allowed_public_roots: tuple[str, ...] = (
        "actions",
        "batch_id",
        "metrics",
        "role",
        "scene_id",
        "scenes",
        "session",
        "state",
        "summary",
    )
    forbidden_public_fields: tuple[str, ...] = (
        "agent_boost",
        "base_score",
        "diagnostics",
        "final_score",
        "ground_truth",
        "holdout",
        "label_binary",
        "oracle",
        "ranking",
        "reward",
        "reward_evidence",
        "score_trace",
        "training_samples",
    )
    constraints: tuple[str, ...] = (
        "public_display_only",
        "sandbox_debug_entrypoint_only",
        "no_online_ranking_state_read",
        "no_training_or_evaluation_label_fields",
        "offline_metrics_written_only_via_offline_boundary",
    )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "owner": self.owner,
            "purpose": self.purpose,
            "offline_boundary": self.offline_boundary,
            "canonical_entrypoints": list(self.canonical_entrypoints),
            "service_entrypoints": list(self.service_entrypoints),
            "allowed_public_roots": list(self.allowed_public_roots),
            "forbidden_public_fields": list(self.forbidden_public_fields),
            "constraints": list(self.constraints),
        }


AGENT_SIMULATION_SANDBOX_CONTRACT = AgentSimulationSandboxContract()


def agent_simulation_sandbox_contract() -> dict[str, object]:
    return AGENT_SIMULATION_SANDBOX_CONTRACT.to_dict()
