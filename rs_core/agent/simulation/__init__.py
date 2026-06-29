from __future__ import annotations

from rs_core.agent.simulation.contracts import (
    AGENT_SIMULATION_SANDBOX_CONTRACT,
    AgentSimulationSandboxContract,
    agent_simulation_sandbox_contract,
)
from rs_core.offline.simulation.policy import DEFAULT_ROLE_POLICY, ModelDrivenRolePolicy, RolePolicy
from rs_core.offline.simulation.presets import COMMUTER_PRACTICAL, GIFT_BUYER, PRESET_ROLES, PRICE_SENSITIVE, get_preset_role
from rs_core.offline.simulation.runner import run_simulation_batch, run_simulation_scene
from rs_core.offline.simulation.schema import RoleAction, RoleActionType, RoleState, SimulatedCustomerRole

__all__ = [
    "COMMUTER_PRACTICAL",
    "DEFAULT_ROLE_POLICY",
    "GIFT_BUYER",
    "ModelDrivenRolePolicy",
    "PRESET_ROLES",
    "PRICE_SENSITIVE",
    "RoleAction",
    "RoleActionType",
    "RolePolicy",
    "RoleState",
    "SimulatedCustomerRole",
    "get_preset_role",
    "run_simulation_batch",
    "run_simulation_scene",
    "AGENT_SIMULATION_SANDBOX_CONTRACT",
    "AgentSimulationSandboxContract",
    "agent_simulation_sandbox_contract",
]
