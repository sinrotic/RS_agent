from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from rs_core.agent.runtime_core import (
    AgentDefinition,
    AgentLoopInput,
    AgentPlan,
    AgentRegistry,
    AgentRunRequest,
    AgentRunResult,
    AgentRunner,
    CommitIntent,
    GenericAgentLoop,
    OutputAdapter,
    OutputProjectionPolicy,
    RuntimePatch,
    ToolCall,
    ToolResult,
    ToolSummary,
)
from rs_core.agent.runtime_core.events import TraceEvent
from rs_core.agent.memory import LongMemoryConfig, recall_relevant_long_memory, snapshot_session_long_memory
from rs_core.agent.contracts.schema import AgentSession, AgentTurn
from rs_core.serving.session_summary import build_public_session_summary_input


MEMORY_AGENT_SUPPORT_SCHEMA_VERSION = "memory_agent_support_v1"
MEMORY_AGENT_SUMMARY_SUPPORT_SCHEMA_VERSION = "memory_agent_summary_support_v1"
MEMORY_AGENT_RECALL_STAGE = "pre_turn_memory_recall"
MEMORY_AGENT_POST_TURN_STAGE = "post_turn_memory_snapshot"
MEMORY_AGENT_SESSION_END_STAGE = "session_end_memory_summary"
_TRUE_STRINGS = {"true", "1", "yes", "y", "on"}
_FALSE_STRINGS = {"false", "0", "no", "n", "off"}


@dataclass(frozen=True)
class MemoryAgentConfig:
    enabled: bool = False
    mode: str = "shadow"
    attach_support_to_diagnostics: bool = True
    max_recalled_entries: int = 20
    max_memory_entries: int = 200
    recall_min_score: float = 0.0
    fail_open: bool = True

    @classmethod
    def from_dict(cls, value: dict[str, Any] | None) -> "MemoryAgentConfig":
        raw = value if isinstance(value, dict) else {}
        return cls(
            enabled=_bool_config(raw, "enabled", False),
            mode=_mode_config(raw.get("mode") or "shadow"),
            attach_support_to_diagnostics=_bool_config(raw, "attach_support_to_diagnostics", True),
            max_recalled_entries=_int_config(raw, "max_recalled_entries", 20),
            max_memory_entries=_int_config(raw, "max_memory_entries", 200),
            recall_min_score=_float_config(raw, "recall_min_score", 0.0),
            fail_open=_bool_config(raw, "fail_open", True),
        )


@dataclass(frozen=True)
class MemoryAgentSupport:
    schema_version: str = MEMORY_AGENT_SUPPORT_SCHEMA_VERSION
    call_stage: str = MEMORY_AGENT_POST_TURN_STAGE
    user_id: str = ""
    session_id: str = ""
    turn_index: int | None = None
    internal_only: bool = True
    public_payload_allowed: bool = False
    candidate_generation_allowed: bool = False
    ranking_input_replacement_allowed: bool = False
    promotion_allowed: bool = False
    recalled_memory: dict[str, Any] = field(default_factory=dict)
    snapshot_summary: dict[str, Any] = field(default_factory=dict)
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MemoryAgentSummarySupport:
    schema_version: str = MEMORY_AGENT_SUMMARY_SUPPORT_SCHEMA_VERSION
    call_stage: str = MEMORY_AGENT_SESSION_END_STAGE
    user_id: str = ""
    session_id: str = ""
    turn_count: int = 0
    summary_input_schema_version: str = ""
    internal_only: bool = True
    public_payload_allowed: bool = False
    candidate_generation_allowed: bool = False
    ranking_input_replacement_allowed: bool = False
    promotion_allowed: bool = False
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MemoryAgentShadowReport:
    loop_mode: str = "memory_agent_shadow"
    write_mode: str = "legacy_turn_internal_only"
    output_mode: str = "internal_only"
    status: str = "skipped"
    action: str = "skip"
    recalled_entry_count: int = 0
    available_entry_count: int = 0
    trace_steps: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    internal_only: bool = True
    public_payload_allowed: bool = False
    candidate_generation_allowed: bool = False
    ranking_input_replacement_allowed: bool = False
    promotion_allowed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MemoryAgentInvocation:
    agent_name: str = "memory_agent"
    description: str = "Invoke MemoryAgent child agent"
    stage: str = MEMORY_AGENT_POST_TURN_STAGE
    prompt_or_task: str = ""
    session_id: str = ""
    turn_index: int | None = None
    request_id: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    visibility: str = "internal_only"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MemoryAgentMessageEnvelope:
    sender: str = "rs_agent"
    receiver: str = "memory_agent"
    stage: str = MEMORY_AGENT_POST_TURN_STAGE
    request_id: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MemoryAgentResponse:
    status: str = "skipped"
    stage: str = ""
    action: str = "skip"
    request_id: str = ""
    support: MemoryAgentSupport | None = None
    summary_support: MemoryAgentSummarySupport | None = None
    shadow_report: MemoryAgentShadowReport | None = None
    diagnostics: dict[str, Any] = field(default_factory=dict)
    commit_intents: list[dict[str, Any]] = field(default_factory=list)
    public_output: dict[str, Any] = field(default_factory=dict)
    sft_output: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["support"] = self.support.to_dict() if self.support else None
        payload["summary_support"] = self.summary_support.to_dict() if self.summary_support else None
        payload["shadow_report"] = self.shadow_report.to_dict() if self.shadow_report else None
        return payload


class MemoryContextBuilder:
    def __init__(self, session: AgentSession, turn: AgentTurn, config: MemoryAgentConfig, long_memory_config: LongMemoryConfig | None = None) -> None:
        self.session = session
        self.turn = turn
        self.config = config
        self.long_memory_config = _memory_recall_config(long_memory_config, config)

    def build_context(self, loop_input: AgentLoopInput) -> dict[str, Any]:
        memory = snapshot_session_long_memory(self.session, self.long_memory_config)
        query = str(loop_input.user_input or self.turn.user_input or "")
        recall = recall_relevant_long_memory(memory, query=query, session=self.session, config=self.long_memory_config)
        return {
            "session": self.session,
            "turn": self.turn,
            "query": query,
            "memory": memory,
            "recall": recall,
            "snapshot_summary": _snapshot_summary(memory),
            "config": self.config,
        }


class MemoryPlanner:
    def plan(self, loop_input: AgentLoopInput, context: dict[str, Any]) -> AgentPlan:
        recall = context.get("recall") if isinstance(context.get("recall"), dict) else {}
        if int(recall.get("available_entry_count", 0) or 0) <= 0:
            return AgentPlan(action="skip", metadata={"reason": "missing_long_memory_entries", "internal_only": True})
        return AgentPlan(
            action="build_memory_support",
            tool_calls=[ToolCall(tool_name="recall_long_memory", phase="memory")],
            metadata={"internal_only": True},
        )


class MemoryToolDispatcher:
    def execute(self, plan: AgentPlan, context: dict[str, Any]) -> tuple[list[ToolResult], ToolSummary]:
        if plan.action == "skip":
            return [], ToolSummary(supported=True, phase="memory", requested_count=0, result_count=0, skipped_count=1)
        support = _build_memory_support(context)
        results = [
            ToolResult(
                tool_name="recall_long_memory",
                phase="memory",
                status="ok",
                output={"memory_agent_support": support.to_dict()},
            )
        ]
        return results, ToolSummary(supported=True, phase="memory", requested_count=len(plan.tool_calls), result_count=len(results), executed_count=1)


class MemoryResponseComposer:
    def compose(self, loop_input: AgentLoopInput, context: dict[str, Any], plan: AgentPlan, tool_results: list[ToolResult]) -> dict[str, Any]:
        support = _support_from_results(tool_results)
        if support is None:
            session = context.get("session")
            turn = context.get("turn")
            support = MemoryAgentSupport(
                user_id=getattr(session, "user_id", ""),
                session_id=getattr(session, "session_id", ""),
                turn_index=getattr(turn, "turn_index", None),
                snapshot_summary=context.get("snapshot_summary") if isinstance(context.get("snapshot_summary"), dict) else {},
                diagnostics={"status": "skipped", "reason": plan.metadata.get("reason", "missing_support"), "internal_only": True},
            ).to_dict()
        return {"memory_agent_support": support}


class MemoryStateUpdater:
    def build_patch(
        self,
        loop_input: AgentLoopInput,
        context: dict[str, Any],
        plan: AgentPlan,
        tool_results: list[ToolResult],
        response: dict[str, Any],
    ) -> tuple[RuntimePatch, list[CommitIntent]]:
        support = response.get("memory_agent_support") if isinstance(response.get("memory_agent_support"), dict) else {}
        recall = support.get("recalled_memory") if isinstance(support.get("recalled_memory"), dict) else {}
        recalled_count = int(recall.get("entry_count", 0) or 0)
        available_count = int(recall.get("available_entry_count", 0) or 0)
        diagnostics = {
            "status": "ok" if available_count else "skipped",
            "action": plan.action,
            "internal_only": True,
            "public_payload_allowed": False,
            "candidate_generation_allowed": False,
            "ranking_input_replacement_allowed": False,
            "promotion_allowed": False,
            "recalled_entry_count": recalled_count,
            "available_entry_count": available_count,
        }
        patch = RuntimePatch(
            trace_events=[TraceEvent(step="memory_agent_support", kind="support_built", payload=diagnostics)],
            diagnostics_patch={"memory_agent": diagnostics},
            output_patch={"memory_agent_support": support},
        )
        intents = [
            CommitIntent(
                intent_type="attach_memory_agent_support",
                payload={"diagnostics_key": "memory_agent_support"},
                owner="memory_agent_adapter",
                append_allowed=False,
            )
        ]
        return patch, intents


class MemoryAgentAdapter:
    diagnostics_key = "memory_agent_shadow"
    support_key = "memory_agent_support"

    def __init__(self, config: MemoryAgentConfig | None = None, runner: AgentRunner | None = None) -> None:
        self.config = config or MemoryAgentConfig()
        self.runner = runner or _build_memory_agent_runner(self)

    def build_loop(
        self,
        session: AgentSession,
        turn: AgentTurn,
        config: MemoryAgentConfig | None = None,
        long_memory_config: LongMemoryConfig | None = None,
    ) -> GenericAgentLoop:
        active_config = config or self.config
        return GenericAgentLoop(
            context_builder=MemoryContextBuilder(session, turn, active_config, long_memory_config),
            planner=MemoryPlanner(),
            tool_dispatcher=MemoryToolDispatcher(),
            response_composer=MemoryResponseComposer(),
            state_updater=MemoryStateUpdater(),
            output_adapter=OutputAdapter(
                OutputProjectionPolicy(
                    public_fields=frozenset(),
                    sft_fields=frozenset(),
                    internal_fields=frozenset({"memory_agent_support", "diagnostics", "trace_events", "commit_intents"}),
                )
            ),
        )

    def invoke(self, invocation: MemoryAgentInvocation, config: MemoryAgentConfig | None = None) -> MemoryAgentResponse:
        envelope = MemoryAgentMessageEnvelope(
            sender="rs_agent",
            receiver=invocation.agent_name or "memory_agent",
            stage=invocation.stage,
            request_id=invocation.request_id,
            payload=invocation.payload,
            metadata={
                "description": invocation.description,
                "prompt_or_task": invocation.prompt_or_task,
                "session_id": invocation.session_id,
                "turn_index": invocation.turn_index,
                "visibility": invocation.visibility,
            },
        )
        return self.handle_message(envelope, config)

    def handle_message(self, envelope: MemoryAgentMessageEnvelope, config: MemoryAgentConfig | None = None) -> MemoryAgentResponse:
        metadata = dict(envelope.metadata)
        metadata["config"] = config or self.config
        try:
            result = self.runner.run(
                AgentRunRequest(
                    agent_name=envelope.receiver,
                    stage=str(envelope.stage or "").strip(),
                    request_id=envelope.request_id,
                    payload=envelope.payload if isinstance(envelope.payload, dict) else {},
                    metadata=metadata,
                    visibility=str(metadata.get("visibility") or "internal_only"),
                )
            )
        except Exception as exc:
            return _memory_error_response(str(envelope.stage or "").strip(), envelope.request_id, _safe_error(exc))
        response = result.output.get("memory_agent_response")
        if isinstance(response, MemoryAgentResponse):
            return response
        return MemoryAgentResponse(
            status=result.status,
            stage=result.stage,
            request_id=result.request_id,
            diagnostics={**result.diagnostics, "internal_only": True},
            public_output=result.public_output,
            sft_output=result.sft_output,
        )

    def _handle_message_direct(self, envelope: MemoryAgentMessageEnvelope, config: MemoryAgentConfig | None = None) -> MemoryAgentResponse:
        active_config = config or self.config
        stage = str(envelope.stage or "").strip()
        if envelope.receiver != "memory_agent":
            return MemoryAgentResponse(status="error", stage=stage, request_id=envelope.request_id, diagnostics={"status": "error", "reason": "invalid_receiver", "internal_only": True})
        if not active_config.enabled:
            return MemoryAgentResponse(status="skipped", stage=stage, action="skip", request_id=envelope.request_id, diagnostics={"status": "skipped", "reason": "disabled", "internal_only": True})
        if active_config.mode != "shadow":
            return _memory_error_response(stage, envelope.request_id, f"Unsupported MemoryAgent mode: {active_config.mode}")
        payload = envelope.payload if isinstance(envelope.payload, dict) else {}
        if stage in {MEMORY_AGENT_RECALL_STAGE, MEMORY_AGENT_POST_TURN_STAGE}:
            session = payload.get("session")
            turn = payload.get("turn")
            if not isinstance(session, AgentSession) or not isinstance(turn, AgentTurn):
                report = MemoryAgentShadowReport(status="skipped", errors=["missing_session_or_turn"])
                return MemoryAgentResponse(
                    status="skipped",
                    stage=stage,
                    action="skip",
                    request_id=envelope.request_id,
                    shadow_report=report,
                    diagnostics={"status": "skipped", "reason": "missing_session_or_turn", "internal_only": True},
                )
            long_memory_config = payload.get("long_memory_config") if isinstance(payload.get("long_memory_config"), LongMemoryConfig) else None
            return self._invoke_post_turn(session, turn, active_config, envelope.request_id, stage=stage, long_memory_config=long_memory_config)
        if stage == MEMORY_AGENT_SESSION_END_STAGE:
            public_export = payload.get("public_export") if isinstance(payload.get("public_export"), dict) else {}
            return self._invoke_session_end(public_export, active_config, envelope.request_id)
        return MemoryAgentResponse(status="error", stage=stage, request_id=envelope.request_id, diagnostics={"status": "error", "reason": "unsupported_stage", "internal_only": True})

    def _invoke_post_turn(
        self,
        session: AgentSession,
        turn: AgentTurn,
        config: MemoryAgentConfig,
        request_id: str = "",
        *,
        stage: str = MEMORY_AGENT_POST_TURN_STAGE,
        long_memory_config: LongMemoryConfig | None = None,
    ) -> MemoryAgentResponse:
        try:
            result = self.build_loop(session, turn, config, long_memory_config).run(
                AgentLoopInput(
                    agent_name="memory_agent",
                    user_input=turn.user_input,
                    session_id=session.session_id,
                    state={"turn_index": turn.turn_index},
                    metadata={"mode": config.mode, "stage": stage},
                )
            )
            support_payload = result.response.get("memory_agent_support") if isinstance(result.response.get("memory_agent_support"), dict) else {}
            support = MemoryAgentSupport(**{key: value for key, value in support_payload.items() if key in MemoryAgentSupport.__dataclass_fields__}) if support_payload else None
            recall = support.recalled_memory if support else {}
            available_count = int(recall.get("available_entry_count", 0) or 0)
            report = MemoryAgentShadowReport(
                status="ok" if support and available_count else "skipped",
                action=result.plan.action,
                recalled_entry_count=int(recall.get("entry_count", 0) or 0),
                available_entry_count=int(recall.get("available_entry_count", 0) or 0),
                trace_steps=[event.step for event in result.trace_events],
            )
            return MemoryAgentResponse(
                status=report.status,
                stage=stage,
                action=result.plan.action,
                request_id=request_id,
                support=support,
                shadow_report=report,
                diagnostics=report.to_dict(),
                commit_intents=[asdict(intent) for intent in result.commit_intents],
                public_output=result.public_output,
                sft_output=result.sft_output,
            )
        except Exception as exc:
            report = MemoryAgentShadowReport(status="error", errors=[_safe_error(exc)])
            return MemoryAgentResponse(status="error", stage=stage, action="skip", request_id=request_id, shadow_report=report, diagnostics=report.to_dict())

    def _invoke_session_end(self, public_export: dict[str, Any], config: MemoryAgentConfig, request_id: str = "") -> MemoryAgentResponse:
        try:
            safe_input = build_public_session_summary_input(public_export)
            support = MemoryAgentSummarySupport(
                user_id=str(safe_input.get("user_id") or ""),
                session_id=str(safe_input.get("session_id") or ""),
                turn_count=int(safe_input.get("turn_count") or 0),
                summary_input_schema_version=str(safe_input.get("schema_version") or ""),
                diagnostics={"status": "ok", "internal_only": True, "safe_public_summary_input": True},
            )
            return MemoryAgentResponse(
                status="ok",
                stage=MEMORY_AGENT_SESSION_END_STAGE,
                action="build_session_summary_support",
                request_id=request_id,
                summary_support=support,
                diagnostics=support.diagnostics,
                public_output={},
                sft_output={},
            )
        except Exception as exc:
            return _memory_error_response(MEMORY_AGENT_SESSION_END_STAGE, request_id, _safe_error(exc))

    def run_shadow(
        self,
        session: AgentSession,
        turn: AgentTurn,
        config: MemoryAgentConfig | None = None,
        long_memory_config: LongMemoryConfig | None = None,
    ) -> tuple[MemoryAgentShadowReport, dict[str, Any]]:
        active_config = config or self.config
        response = self.invoke(
            MemoryAgentInvocation(
                description="post-turn MemoryAgent shadow support",
                stage=MEMORY_AGENT_POST_TURN_STAGE,
                prompt_or_task="Build internal long-memory recall support for the current turn.",
                session_id=session.session_id,
                turn_index=turn.turn_index,
                request_id=f"memory-post-{session.session_id}-{turn.turn_index}",
                payload={"session": session, "turn": turn, "long_memory_config": long_memory_config},
            ),
            active_config,
        )
        report = response.shadow_report or MemoryAgentShadowReport(status=response.status, action=response.action)
        support = response.support.to_dict() if response.support else {}
        return report, support

    def attach_shadow_report(
        self,
        session: AgentSession,
        turn: AgentTurn,
        config: MemoryAgentConfig | None = None,
        long_memory_config: LongMemoryConfig | None = None,
    ) -> MemoryAgentShadowReport:
        active_config = config or self.config
        report, support = self.run_shadow(session, turn, active_config, long_memory_config)
        turn.diagnostics[self.diagnostics_key] = report.to_dict()
        if active_config.attach_support_to_diagnostics and support:
            turn.diagnostics[self.support_key] = support
        return report


class _MemoryAgentHandler:
    def __init__(self, adapter: MemoryAgentAdapter) -> None:
        self.adapter = adapter

    def run(self, request: AgentRunRequest) -> AgentRunResult:
        config = request.metadata.get("config")
        active_config = config if isinstance(config, MemoryAgentConfig) else self.adapter.config
        envelope = MemoryAgentMessageEnvelope(
            receiver=request.agent_name,
            stage=request.stage,
            request_id=request.request_id,
            payload=request.payload,
            metadata={key: value for key, value in request.metadata.items() if key != "config"},
        )
        response = self.adapter._handle_message_direct(envelope, active_config)
        return AgentRunResult(
            agent_name=request.agent_name,
            status=response.status,
            stage=response.stage,
            request_id=response.request_id,
            output={"memory_agent_response": response},
            diagnostics=response.diagnostics,
            public_output=response.public_output,
            sft_output=response.sft_output,
        )


def _build_memory_agent_runner(adapter: MemoryAgentAdapter) -> AgentRunner:
    registry = AgentRegistry()
    registry.register(
        AgentDefinition(
            name="memory_agent",
            description="Internal long-memory recall and session memory support agent.",
            supported_stages=frozenset({MEMORY_AGENT_RECALL_STAGE, MEMORY_AGENT_POST_TURN_STAGE, MEMORY_AGENT_SESSION_END_STAGE}),
            default_visibility="internal_only",
            handler=_MemoryAgentHandler(adapter),
        )
    )
    return AgentRunner(registry)


def _build_memory_support(context: dict[str, Any]) -> MemoryAgentSupport:
    session = context.get("session")
    turn = context.get("turn")
    recall = context.get("recall") if isinstance(context.get("recall"), dict) else {}
    return MemoryAgentSupport(
        user_id=getattr(session, "user_id", ""),
        session_id=getattr(session, "session_id", ""),
        turn_index=getattr(turn, "turn_index", None),
        recalled_memory=_sanitize_recall(recall),
        snapshot_summary=context.get("snapshot_summary") if isinstance(context.get("snapshot_summary"), dict) else {},
        diagnostics={"status": "ok", "internal_only": True, "recall_strategy": recall.get("recall_strategy")},
    )


def _snapshot_summary(memory: Any) -> dict[str, Any]:
    constraints = memory.active_constraints
    return {
        "schema_version": getattr(memory, "schema_version", ""),
        "user_id": getattr(memory, "user_id", ""),
        "updated_session_id": getattr(memory, "updated_session_id", None),
        "updated_turn_count": int(getattr(memory, "updated_turn_count", 0) or 0),
        "entry_count": len(getattr(memory, "entries", []) or []),
        "active_constraint_keys": sorted(
            key
            for key, value in constraints.to_dict().items()
            if value not in (None, False, [], {}, set())
        ),
    }


def _sanitize_recall(recall: dict[str, Any]) -> dict[str, Any]:
    entries = recall.get("entries") if isinstance(recall.get("entries"), list) else []
    return {
        "entries": [_sanitize_entry(entry) for entry in entries if isinstance(entry, dict)],
        "entry_count": int(recall.get("entry_count", 0) or 0),
        "available_entry_count": int(recall.get("available_entry_count", 0) or 0),
        "recall_strategy": str(recall.get("recall_strategy") or ""),
    }


def _sanitize_entry(entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "entry_id": str(entry.get("entry_id") or ""),
        "type": str(entry.get("type") or ""),
        "value": entry.get("value") if isinstance(entry.get("value"), dict) else {},
        "confidence": float(entry.get("confidence", 0.0) or 0.0),
        "updated_turn_index": int(entry.get("updated_turn_index", 0) or 0),
        "updated_session_id": entry.get("updated_session_id"),
    }


def _support_from_results(tool_results: list[ToolResult]) -> dict[str, Any] | None:
    for result in tool_results:
        output = result.output if isinstance(result.output, dict) else {}
        support = output.get("memory_agent_support")
        if isinstance(support, dict):
            return support
    return None


def _memory_recall_config(base: LongMemoryConfig | None, config: MemoryAgentConfig) -> LongMemoryConfig:
    source = base or LongMemoryConfig()
    return LongMemoryConfig(
        enabled=source.enabled,
        store_type=source.store_type,
        json_path=source.json_path,
        max_liked_item_ids=source.max_liked_item_ids,
        max_disliked_item_ids=source.max_disliked_item_ids,
        max_preference_terms=source.max_preference_terms,
        persist_unsupported_free_text=source.persist_unsupported_free_text,
        enable_typed_entries=source.enable_typed_entries,
        enable_relevance_recall=source.enable_relevance_recall,
        max_memory_entries=max(0, config.max_memory_entries),
        max_recalled_entries=max(0, config.max_recalled_entries),
        recall_min_score=float(config.recall_min_score),
    )


def _memory_error_response(stage: str, request_id: str, message: str) -> MemoryAgentResponse:
    report = MemoryAgentShadowReport(status="error", action="skip", errors=[message])
    return MemoryAgentResponse(status="error", stage=stage, action="skip", request_id=request_id, shadow_report=report, diagnostics=report.to_dict(), public_output={}, sft_output={})


def _bool_config(config: dict[str, Any], key: str, default: bool) -> bool:
    value = config.get(key, default)
    if isinstance(value, bool):
        return value
    if value in (None, ""):
        return default
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in _TRUE_STRINGS:
            return True
        if normalized in _FALSE_STRINGS:
            return False
        raise ValueError(f"Invalid boolean config for {key}: {value}")
    return bool(value)


def _int_config(config: dict[str, Any], key: str, default: int) -> int:
    value = config.get(key, default)
    if value in (None, ""):
        return default
    return int(value)


def _float_config(config: dict[str, Any], key: str, default: float) -> float:
    value = config.get(key, default)
    if value in (None, ""):
        return default
    return float(value)


def _mode_config(value: Any) -> str:
    return str(value or "shadow").strip().lower()


def _safe_error(exc: Exception, limit: int = 180) -> str:
    text = f"{type(exc).__name__}: {exc}".replace("\n", " ").strip()
    if len(text) <= limit:
        return text
    return f"{text[: max(0, limit - 3)]}..."
