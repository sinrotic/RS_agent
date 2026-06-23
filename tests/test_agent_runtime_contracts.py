from __future__ import annotations

import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

from rs_core.agent_runtime.contracts import (
    FAILURE_CONTRACTS,
    LEGACY_RUNTIME_TRACE_STEP_ORDER,
    OUTPUT_VISIBILITY_MATRIX,
    TOOL_RESULT_FIELDS,
    TOOL_SUMMARY_FIELDS,
    assert_legacy_trace_order,
)
from rs_core.agent_runtime.core import (
    AgentRuntimeConfig,
    LoopMode,
    OutputAdapter,
    OutputProjectionPolicy,
    ProjectionViolation,
    ToolResult,
    ToolSpec,
    TraceEvent,
    parse_loop_mode,
)
from rs_core.rsagent.runtime import RUNTIME_TRACE_STEP_ORDER


PROJECT_ROOT = Path(__file__).resolve().parents[1]
GENERIC_RUNTIME_ROOT = PROJECT_ROOT / "rs_core" / "agent_runtime"
DOMAIN_IMPORT_PREFIXES = (
    "rs_core.rsagent",
    "rs_core.workflow",
    "rs_core.simulation",
    "rs_core.recsys",
)


def test_loop_mode_parser_defaults_to_legacy_and_rejects_unknown() -> None:
    assert parse_loop_mode(None) == LoopMode.LEGACY
    assert parse_loop_mode("") == LoopMode.LEGACY
    assert parse_loop_mode("generic_shadow") == LoopMode.GENERIC_SHADOW
    assert AgentRuntimeConfig.from_dict({"loop_mode": "generic_active"}).loop_mode == LoopMode.GENERIC_ACTIVE

    with pytest.raises(ValueError, match="Unsupported agent_runtime.loop_mode"):
        parse_loop_mode("shadow")


def test_contract_trace_order_matches_legacy_runtime_order() -> None:
    assert LEGACY_RUNTIME_TRACE_STEP_ORDER == tuple(RUNTIME_TRACE_STEP_ORDER)
    trace = [{"name": name} for name in RUNTIME_TRACE_STEP_ORDER]

    assert_legacy_trace_order(trace)

    with pytest.raises(AssertionError, match="runtime trace step order mismatch"):
        assert_legacy_trace_order(list(reversed(trace)))


def test_generic_core_does_not_import_domain_modules() -> None:
    violations: list[str] = []
    for path in (GENERIC_RUNTIME_ROOT / "core").glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith(DOMAIN_IMPORT_PREFIXES):
                        violations.append(f"{path.relative_to(PROJECT_ROOT)} imports {alias.name}")
            elif isinstance(node, ast.ImportFrom) and node.module:
                if node.module.startswith(DOMAIN_IMPORT_PREFIXES):
                    violations.append(f"{path.relative_to(PROJECT_ROOT)} imports {node.module}")

    assert violations == []


def test_generic_runtime_and_adapters_do_not_append_recommendation_turns() -> None:
    violations: list[str] = []
    for path in GENERIC_RUNTIME_ROOT.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if "session.turns.append(" in text:
            violations.append(str(path.relative_to(PROJECT_ROOT)))

    assert violations == []


def test_tool_summary_and_result_contract_fields_are_explicit() -> None:
    assert TOOL_SUMMARY_FIELDS == (
        "supported",
        "phase",
        "requested_count",
        "result_count",
        "executed_count",
        "skipped_count",
        "error_count",
    )
    assert TOOL_RESULT_FIELDS == (
        "tool_name",
        "phase",
        "status",
        "reason",
        "error_type",
        "message",
        "output",
    )
    result = ToolResult(
        tool_name="retrieve_candidates",
        phase="pre_recommendation",
        status="ok",
        output={"candidate_count": 2},
    )

    assert set(TOOL_RESULT_FIELDS) <= set(result.to_dict())


def test_four_tool_failure_contracts_are_stable_and_sanitized_by_policy() -> None:
    assert set(FAILURE_CONTRACTS) == {
        "unknown_tool",
        "validation_failed",
        "handler_exception",
        "dispatcher_exception",
    }
    assert FAILURE_CONTRACTS["unknown_tool"].status == "skipped"
    assert FAILURE_CONTRACTS["unknown_tool"].reason == "unknown_tool"
    assert FAILURE_CONTRACTS["unknown_tool"].skipped_count_delta == 1
    assert FAILURE_CONTRACTS["validation_failed"].error_count_delta == 1
    assert FAILURE_CONTRACTS["handler_exception"].executed_count_delta == 1
    assert FAILURE_CONTRACTS["dispatcher_exception"].error_type == "dispatcher_exception"
    for contract in FAILURE_CONTRACTS.values():
        assert contract.public_visibility == "transformed"
        assert contract.sft_visibility == "transformed"
        assert contract.internal_visibility == "allow_sanitized"


def test_output_visibility_matrix_denies_raw_internal_fields_from_public_and_sft() -> None:
    for key in ["hidden_tool_result", "raw_trace", "raw_rag_evidence", "mcpInfo", "inputJSONSchema", "boundary_prompt"]:
        assert OUTPUT_VISIBILITY_MATRIX[key]["public"] == "deny"
        assert OUTPUT_VISIBILITY_MATRIX[key]["sft"] == "deny"
    assert OUTPUT_VISIBILITY_MATRIX["sanitized_rag_summary_citation"]["public"] == "allow"
    assert OUTPUT_VISIBILITY_MATRIX["sanitized_rag_summary_citation"]["sft"] == "allow"


def test_output_adapter_defaults_to_deny_and_blocks_forbidden_nested_fields() -> None:
    adapter = OutputAdapter()
    payload = {
        "assistant_message": "Here are options.",
        "agent_runtime_trace": [{"name": "observe_input"}],
    }

    assert adapter.project_public(payload) == {}
    assert adapter.project_sft(payload) == {}
    assert adapter.project_internal(payload) == {}

    public_adapter = OutputAdapter(OutputProjectionPolicy(public_fields=frozenset({"assistant_message", "debug"})))
    assert public_adapter.project_public(payload) == {"assistant_message": "Here are options."}

    with pytest.raises(ProjectionViolation, match="Forbidden public field"):
        public_adapter.project_public({"debug": {"raw_trace": []}})


def test_internal_projection_redacts_secret_shaped_keys_by_contract() -> None:
    adapter = OutputAdapter(OutputProjectionPolicy(internal_fields=frozenset({"safe", "secret"})))

    with pytest.raises(ProjectionViolation, match="Forbidden internal field"):
        adapter.project_internal({"safe": True, "secret": "do-not-project"})


def test_rs_tool_fields_stay_adapter_owned_opaque_metadata() -> None:
    spec = ToolSpec(
        name="retrieve_candidates",
        description="Retrieve candidates.",
        metadata={
            "recommendation": {
                "hidden": True,
                "public_payload_allowed": False,
                "exportable_to_sft": False,
                "allowed_intents": ["recommend_request"],
                "requires_candidate_pool": False,
                "uses_reference_item": True,
                "can_search_catalog": True,
                "uses_rag_evidence": False,
                "routing_attributes": {"available_phase": "pre_recommendation"},
                "boundary_prompt": "Do not leak raw scores.",
            }
        },
    )

    payload = spec.to_dict()
    assert payload["metadata"]["recommendation"]["hidden"] is True
    assert "hidden" not in payload
    assert "allowed_intents" not in payload


def test_trace_event_requires_known_visibility() -> None:
    assert TraceEvent(step="observe_input", kind="input_observed").visibility == "internal"

    with pytest.raises(ValueError, match="Unsupported trace visibility"):
        TraceEvent(step="observe_input", kind="input_observed", visibility="sensitive")
