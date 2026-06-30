from __future__ import annotations

from rs_core.offline.simulation.policy import DEFAULT_ROLE_POLICY, ModelDrivenRolePolicy, RolePolicy
from rs_core.offline.simulation.presets import COMMUTER_PRACTICAL, GIFT_BUYER, PRESET_ROLES, PRICE_SENSITIVE, get_preset_role
from rs_core.offline.simulation.runner import run_simulation_batch, run_simulation_scene
from rs_core.offline.simulation.schema import RoleAction, RoleActionType, RoleState, SimulatedCustomerRole

OFFLINE_SIMULATION_CONTRACT = {
    "owner": "rs_core.offline.simulation",
    "legacy_import": None,
    "migration_status": "implemented",
    "allowed_execution_modes": ("smoke",),
    "forbidden_actions": ("full_simulation", "refresh_artifact"),
}
OFFLINE_DEFERRED_CONTRACT = OFFLINE_SIMULATION_CONTRACT

__all__ = [
    "COMMUTER_PRACTICAL",
    "DEFAULT_ROLE_POLICY",
    "GIFT_BUYER",
    "ModelDrivenRolePolicy",
    "OFFLINE_DEFERRED_CONTRACT",
    "OFFLINE_SIMULATION_CONTRACT",
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
]
