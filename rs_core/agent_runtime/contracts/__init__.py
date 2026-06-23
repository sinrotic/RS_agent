"""Compatibility contracts for generic agent runtime migrations."""

from rs_core.agent_runtime.contracts.compatibility import (
    FAILURE_CONTRACTS,
    LEGACY_RUNTIME_TRACE_STEP_ORDER,
    OUTPUT_VISIBILITY_MATRIX,
    TOOL_RESULT_FIELDS,
    TOOL_SUMMARY_FIELDS,
    FailureContract,
    assert_legacy_trace_order,
)

__all__ = [
    "FAILURE_CONTRACTS",
    "LEGACY_RUNTIME_TRACE_STEP_ORDER",
    "OUTPUT_VISIBILITY_MATRIX",
    "TOOL_RESULT_FIELDS",
    "TOOL_SUMMARY_FIELDS",
    "FailureContract",
    "assert_legacy_trace_order",
]
