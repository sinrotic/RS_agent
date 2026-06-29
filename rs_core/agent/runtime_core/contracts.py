from __future__ import annotations

from dataclasses import dataclass
from typing import Any


LEGACY_RUNTIME_TRACE_STEP_ORDER = (
    "observe_input",
    "memory_prefetch",
    "context_compact",
    "tool_result_budget",
    "plan_dialogue",
    "apply_constraints",
    "execute_pre_recommendation_tools",
    "recommend_or_dialogue",
    "build_turn",
    "execute_post_recommendation_tools",
    "stop_check",
    "attach_diagnostics",
    "update_session_summary",
)

TOOL_SUMMARY_FIELDS = (
    "supported",
    "phase",
    "requested_count",
    "result_count",
    "executed_count",
    "skipped_count",
    "error_count",
)

TOOL_RESULT_FIELDS = (
    "tool_name",
    "phase",
    "status",
    "reason",
    "error_type",
    "message",
    "output",
)


@dataclass(frozen=True)
class FailureContract:
    status: str
    reason: str
    error_type: str
    executed_count_delta: int
    skipped_count_delta: int
    error_count_delta: int
    public_visibility: str = "transformed"
    sft_visibility: str = "transformed"
    internal_visibility: str = "allow_sanitized"


FAILURE_CONTRACTS = {
    "unknown_tool": FailureContract(
        status="skipped",
        reason="unknown_tool",
        error_type="unknown_tool",
        executed_count_delta=0,
        skipped_count_delta=1,
        error_count_delta=0,
    ),
    "validation_failed": FailureContract(
        status="error",
        reason="validation_failed",
        error_type="validation_failed",
        executed_count_delta=0,
        skipped_count_delta=0,
        error_count_delta=1,
    ),
    "handler_exception": FailureContract(
        status="error",
        reason="handler_exception",
        error_type="handler_exception",
        executed_count_delta=1,
        skipped_count_delta=0,
        error_count_delta=1,
    ),
    "dispatcher_exception": FailureContract(
        status="error",
        reason="dispatcher_exception",
        error_type="dispatcher_exception",
        executed_count_delta=0,
        skipped_count_delta=0,
        error_count_delta=1,
    ),
}

OUTPUT_VISIBILITY_MATRIX = {
    "hidden_tool_result": {"public": "deny", "sft": "deny", "internal": "allow_sanitized"},
    "public_tool_result": {"public": "allow_sanitized", "sft": "allow_sanitized", "internal": "allow"},
    "diagnostics": {"public": "transformed", "sft": "transformed", "internal": "allow_sanitized"},
    "raw_trace": {"public": "deny", "sft": "deny", "internal": "allow_sanitized"},
    "reward": {"public": "deny", "sft": "transformed_if_schema_approved", "internal": "allow"},
    "raw_rag_evidence": {"public": "deny", "sft": "deny", "internal": "allow_sanitized"},
    "sanitized_rag_summary_citation": {"public": "allow", "sft": "allow", "internal": "allow"},
    "loop_mode": {"public": "deny", "sft": "deny", "internal": "allow"},
    "routing_attributes": {"public": "deny", "sft": "transformed_if_schema_approved", "internal": "allow"},
    "boundary_prompt": {"public": "deny", "sft": "deny", "internal": "allow_sanitized"},
    "mcpInfo": {"public": "deny", "sft": "deny", "internal": "allow_sanitized"},
    "inputJSONSchema": {"public": "deny", "sft": "deny", "internal": "allow_sanitized"},
}


def assert_legacy_trace_order(trace: list[dict[str, Any]] | tuple[dict[str, Any], ...]) -> None:
    names = tuple(str(step.get("name") or step.get("step") or "") for step in trace)
    if names != LEGACY_RUNTIME_TRACE_STEP_ORDER:
        raise AssertionError(f"runtime trace step order mismatch: {names!r}")
