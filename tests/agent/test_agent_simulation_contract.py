from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


def test_agent_simulation_sandbox_contract_is_public_safe() -> None:
    from rs_core.agent.simulation import agent_simulation_sandbox_contract

    contract = agent_simulation_sandbox_contract()

    assert contract["schema_version"] == "rs_agent_simulation_sandbox_contract_v1"
    assert contract["owner"] == "rs_core.agent.simulation"
    assert contract["purpose"] == "agent_behavior_sandbox"
    assert contract["offline_boundary"] == "rs_core.offline.simulation"
    assert "rs_core.agent.simulation.run_simulation_scene" in contract["canonical_entrypoints"]
    assert "rs_core.agent.simulation.run_simulation_batch" in contract["canonical_entrypoints"]
    assert "/simulation/scene" in contract["service_entrypoints"]
    assert "/simulation/batch" in contract["service_entrypoints"]
    assert "public_display_only" in contract["constraints"]
    assert "offline_metrics_written_only_via_offline_boundary" in contract["constraints"]
    assert "diagnostics" in contract["forbidden_public_fields"]
    assert "oracle" in contract["forbidden_public_fields"]
    assert "training_samples" in contract["forbidden_public_fields"]


def test_agent_simulation_facade_keeps_offline_scene_entrypoints_available() -> None:
    from rs_core.agent.simulation import RoleAction, RoleActionType, SimulatedCustomerRole, run_simulation_batch, run_simulation_scene
    from rs_core.offline.simulation import run_simulation_batch as offline_batch
    from rs_core.offline.simulation import run_simulation_scene as offline_scene

    assert run_simulation_scene is offline_scene
    assert run_simulation_batch is offline_batch
    assert RoleAction.chat("hello").type == RoleActionType.CHAT
    assert SimulatedCustomerRole(role_id="r", persona="p", shopping_goal="g").initial_prompt() == "g"
