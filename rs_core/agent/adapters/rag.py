from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
import re
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
from rs_core.common.openai_compatible_client import OpenAICompatibleClient, first_message_content, safe_response_metadata
from rs_core.agent.rag import RAG_PARENT_PROFILE_FIELD
from rs_core.agent.contracts.schema import AgentTurn


RAG_AGENT_SUPPORT_SCHEMA_VERSION = "rag_agent_support_v1"
RAG_AGENT_QUERY_SUPPORT_SCHEMA_VERSION = "rag_agent_query_support_v1"
RAG_AGENT_PRE_RETRIEVAL_STAGE = "pre_retrieval_query_support"
RAG_AGENT_POST_RANKING_STAGE = "post_ranking_evidence_support"
RAG_AGENT_SYSTEM_PROMPT = """
<Role_And_Duty>
你是 RSAgent 内部调用的 RagAgent 子 Agent，不面向顾客独立运行，也不主动发起推荐流程。你的职责是整理、压缩和约束商品 RAG 证据：在 pre_retrieval_query_support 阶段为 RSAgent/runtime 提供紧凑 semantic_query_hint、query_rewrite 与 suggested_query_terms；如果用户 query 是中文或中英混合，可以先翻译/规范化为英文商品检索 query 再进行 RAG 召回规划；在 post_ranking_evidence_support 阶段围绕已有候选或已展示商品压缩 candidate-scoped evidence 与 small2big parent_profile support。你不是召回器、排序器或推荐决策器，最终目标是让推荐链路获得更准确、更短、更可验证的内部证据支持，同时不污染候选生成、排序、公开回答或训练监督。
</Role_And_Duty>

<Why_This_Matters>
商品 RAG 命中的 chunk 和 small2big parent profile 可能很长，直接并入 RecommendationAgent 会消耗上下文、放大内部检索细节泄漏风险，并可能让证据看起来像新的候选或排序依据。RagAgent 的价值是作为证据整理层，把商品知识从 raw evidence 转成受预算、受候选边界、受输出投影约束的 compact support，让 RSAgent 可以获得 grounding 辅助，但继续由推荐主链路负责候选获取、排序和展示安全输出。
</Why_This_Matters>

<Success_Standard>
一次成功运行应满足：pre-retrieval 阶段只在用户 query 可用且 runtime 显式请求时生成有助于语义召回规划的紧凑 hint；post-ranking 阶段只围绕 candidate_item_ids、final_items 或 ranking 中允许的商品给出 item-level support；所有 support 都应短、准、可追溯到候选内 evidence，但不暴露 raw evidence、parent_profile 原文、source、score、retriever、manifest、diagnostics、label、oracle、holdout、test/future 字段。成功的 RagAgent 不会新增候选、不会重排候选、不会替代 ranking input、不会 promotion，也不会把内容写入 public payload 或 SFT payload；缺少证据、缺少候选边界或输入不满足 call_stage 条件时，应安全跳过并返回 internal skipped diagnostics。
</Success_Standard>

<Context_Use>
你只能使用 RSAgent/runtime 显式传入的上下文，包括 call_stage、user query、candidate_item_ids、final_items 或 ranking 摘要、candidate-scoped evidence、parent_profile metadata、max_support_per_item、max_text_chars 与 governance flags。用户 query 可作为 pre-retrieval hint 的主信号，RAG evidence 只能作为辅助扩展词或候选内解释证据；candidate_item_ids 是硬边界，ranking/final_items 只能帮助确认哪些候选需要 support，不能扩大证据作用域。parent_profile 只表示命中商品的商品级画像材料，必须压缩成字段级可用性或安全摘要，不能原样输出。
</Context_Use>

<Subagent_Communication>
你的运行由 RSAgent 通过内部 call_rag_agent 子 Agent 工具显式触发，输入会带有 request_id、call_stage、payload 与 internal-only visibility。pre_retrieval_query_support 只发生在 retrieve_candidates 之前，用于把用户 query 和受控 evidence 压缩为 semantic_query_hint、query_rewrite、suggested_query_terms 与 retrieval_hints；当 query 为中文或中英混合时，可以调用已配置的双语 API 先生成英文 normalized retrieval query，再把该英文 query 用于 RAG query planning。它不返回候选、不调用排序、不决定展示。post_ranking_evidence_support 只发生在候选、ranking/final_items 与 turn.rag_context 已存在之后，用于对候选内 ordinary evidence 做截断、脱敏和 item-level support，对 small2big parent_profile 做 raw text withheld 的压缩。每次运行都应先校验 call_stage、candidate scope、allowed fields 与预算，再生成 internal-only structured result envelope；无法满足条件时返回 skipped diagnostics。
</Subagent_Communication>

<Evidence_Boundary>
RAG evidence 只能支持已有候选或已展示商品，不能新增商品、改变排序、扩大候选边界、替代推荐理由或伪装成业务指标。中文到英文的 query_rewrite 只服务 RAG query planning，不是新的候选来源或排序依据。不得输出 raw evidence、raw parent_profile、source path、score、retriever 名称、manifest、diagnostics、label、oracle、holdout、test/future 字段或任何训练/评估 artifact。不得把 source scores、method lineage、tool traces、trace、hidden catalog、private manifest 或内部字段名暴露给 RSAgent 的公开回答、display card、SFT supervision 或用户可见解释。
</Evidence_Boundary>

<Runtime_Boundary>
你可以做的是校验输入、按候选范围过滤 evidence、提取安全字段、截断文本、脱敏敏感片段、压缩 parent profile、生成 semantic_query_hint 和 item_support，并把结果标记为 internal-only。你不能主动运行，不能面向用户对话，不能调用或选择底层 provider，不能访问未传入的上下文，不能根据 evidence 修改 candidates、ranking、final_items 或 assistant_response，不能在 public/SFT projection 中留下 rag_context、raw_rag_evidence、diagnostics、trace 或工具调用细节。所有治理开关默认保持 candidate_generation_allowed=false、ranking_input_replacement_allowed=false、promotion_allowed=false、public_payload_allowed=false。
</Runtime_Boundary>

<Response_Style>
你的输出不是自然语言客服回复，而是给 RSAgent/runtime 消费的内部结构化 support。文本应短、事实化、证据导向，优先使用安全字段名和压缩摘要；普通 evidence 摘要不得超过预算，敏感或疑似内部来源文本应改写为“候选内商品证据已压缩，原始文本保留在内部 RAG 上下文。”；parent_profile 摘要应表达可用字段或安全概要，并明确 raw text withheld。不要使用夸张营销语，不要把弱证据说成确定事实，不要输出给用户看的推荐话术。
</Response_Style>

<Output_Format>
pre_retrieval_query_support 输出 rag_agent_query_support，字段包括 schema_version、call_stage、query、query_rewrite、semantic_query_hint、suggested_query_terms、retrieval_hints、governance flags 与 diagnostics。post_ranking_evidence_support 输出 rag_agent_support，字段包括 schema_version、call_stage、candidate_scoped、item_support、used_evidence_count、used_parent_profile_count、governance flags 与 diagnostics。所有输出默认 internal-only，public_payload_allowed=false；失败或缺证据时保留结构化 skipped/error diagnostics，但不得抛出会阻断推荐主链路的公开错误。
</Output_Format>

<Good_Output_Example>
合适的 post_ranking_evidence_support 输出类似：对候选 i1 返回 field=features、summary=“Lightweight titanium body for camping.”、evidence_hint=“candidate-scoped features”；如果命中 parent_profile，则只返回 summary=“商品级画像可用字段: title, description, features” 与 evidence_hint=“small2big parent profile compressed; raw text withheld”。这种输出短、候选内、可用于 grounding，但不泄露 raw parent profile、source、score 或 retriever。
</Good_Output_Example>

<Bad_Output_Example>
不合适的输出是：“BM25 从 /private/manifest.json 以 score=0.98 命中 i9，这个商品应该排到第一，并且 parent_profile 原文如下……”。这种输出同时暴露 retriever、source path、score 和 raw parent_profile，还试图新增或提升候选，违反 RagAgent 只能提供 internal candidate-scoped support 的边界。
</Bad_Output_Example>
""".strip()
_SAFE_EVIDENCE_FIELDS = {
    "title",
    "category",
    "main_category",
    "category_path",
    "description",
    "features",
    "store",
    "brand",
    "average_rating",
    "rating_number",
}
_INTERNAL_FIELD_NAMES = {"source", "score", "scores", "manifest", "metadata", "diagnostics", "debug", "path", "provenance"}
_SENSITIVE_TEXT_PATTERN = re.compile(r"(?i)(source|score|manifest|path|provenance|oracle|holdout|label|target|future|test|retriever|bm25|sqlite_bm25|milvus|hybrid|vector|source_fields)\b|[/\\][^\s]+")
_QUERY_REWRITE_FORBIDDEN_PATTERN = re.compile(
    r"(?i)(retrieve_candidates|rank_candidates|tool call|internal tool|diagnostic|trace|source[_ -]?score|source[:=]|score[:=]|sqlite_bm25|bm25|milvus|oracle|label|manifest|holdout|future|candidate[_ -]?id|item[_ -]?id|[/\\][^\s]+)"
)
_TRUE_STRINGS = {"true", "1", "yes", "y", "on"}
_FALSE_STRINGS = {"false", "0", "no", "n", "off"}


@dataclass(frozen=True)
class RagAgentConfig:
    enabled: bool = False
    mode: str = "shadow"
    max_support_per_item: int = 3
    max_text_chars: int = 220
    attach_support_to_diagnostics: bool = True

    @classmethod
    def from_dict(cls, value: dict[str, Any] | None) -> "RagAgentConfig":
        raw = value if isinstance(value, dict) else {}
        return cls(
            enabled=_bool_config(raw, "enabled", False),
            mode=_mode_config(raw.get("mode") or "shadow"),
            max_support_per_item=_int_config(raw, "max_support_per_item", 3),
            max_text_chars=_int_config(raw, "max_text_chars", 220),
            attach_support_to_diagnostics=_bool_config(raw, "attach_support_to_diagnostics", True),
        )


@dataclass(frozen=True)
class RagQueryRewriteConfig:
    enabled: bool = False
    mode: str = "disabled"
    model: str = ""
    base_url: str = "https://api.openai.com"
    api_key_env: str = "RS_AGENT_GPT_SFT_API_KEY"
    timeout_seconds: float = 8.0
    temperature: float | None = 0.0
    max_tokens: int | None = 300
    allow_insecure_local_api_base: bool = False

    @classmethod
    def from_dict(cls, value: dict[str, Any] | None) -> "RagQueryRewriteConfig":
        raw = value if isinstance(value, dict) else {}
        enabled_default = _bool_value(raw.get("enabled", False), False)
        mode = str(raw.get("mode") or ("active" if enabled_default else "disabled")).strip().lower()
        if mode not in {"disabled", "shadow", "active"}:
            mode = "disabled"
        return cls(
            enabled=_bool_value(raw.get("enabled", mode != "disabled"), mode != "disabled") and mode != "disabled",
            mode=mode,
            model=str(raw.get("model") or "").strip(),
            base_url=str(raw.get("base_url") or raw.get("api_base") or "https://api.openai.com").strip(),
            api_key_env=str(raw.get("api_key_env") or "RS_AGENT_GPT_SFT_API_KEY").strip(),
            timeout_seconds=_safe_float(raw.get("timeout_seconds"), 8.0),
            temperature=_optional_float(raw.get("temperature"), 0.0),
            max_tokens=_optional_int(raw.get("max_tokens"), 300),
            allow_insecure_local_api_base=_bool_value(raw.get("allow_insecure_local_api_base", False), False),
        )


@dataclass
class RagQueryRewriteResult:
    query: str
    query_rewrite: str = ""
    semantic_query_hint: str = ""
    suggested_query_terms: list[str] = field(default_factory=list)
    diagnostics: dict[str, Any] = field(default_factory=dict)
    error: str = ""

    @property
    def valid(self) -> bool:
        return bool(self.query_rewrite.strip()) and not self.error


class RagQueryRewriter:
    def __init__(self, config: RagQueryRewriteConfig, client: OpenAICompatibleClient | None = None) -> None:
        self.config = config
        self.client = client or OpenAICompatibleClient(
            base_url=config.base_url,
            api_key_env=config.api_key_env,
            timeout_seconds=config.timeout_seconds,
            allow_insecure_local_api_base=config.allow_insecure_local_api_base,
        )

    def rewrite(self, query: str) -> RagQueryRewriteResult:
        clean_query = str(query or "").strip()
        diagnostics: dict[str, Any] = {
            "enabled": self.config.enabled,
            "mode": self.config.mode,
            "model": self.config.model,
        }
        if not clean_query:
            return RagQueryRewriteResult(query=clean_query, diagnostics={**diagnostics, "status": "fallback", "reason": "missing_query"}, error="missing_query")
        if not self.config.enabled or self.config.mode == "disabled":
            return RagQueryRewriteResult(query=clean_query, diagnostics={**diagnostics, "status": "disabled"}, error="disabled")
        if not self.config.model:
            return RagQueryRewriteResult(query=clean_query, diagnostics={**diagnostics, "status": "fallback", "reason": "missing_model"}, error="missing_model")
        try:
            response = self.client.chat_completion(
                model=self.config.model,
                messages=_build_query_rewrite_messages(clean_query),
                temperature=self.config.temperature,
                max_tokens=self.config.max_tokens,
                response_format={"type": "json_object"},
            )
            payload = _extract_first_json_object(first_message_content(response))
            result = _query_rewrite_result_from_payload(clean_query, payload)
            result.diagnostics.update({**diagnostics, "status": "ok", "response": safe_response_metadata(response)})
            return result
        except Exception as exc:
            return RagQueryRewriteResult(
                query=clean_query,
                diagnostics={**diagnostics, "status": "fallback", "reason": type(exc).__name__, "message": str(exc)[:240]},
                error=f"{type(exc).__name__}: {exc}",
            )


@dataclass(frozen=True)
class RagAgentSupport:
    schema_version: str = RAG_AGENT_SUPPORT_SCHEMA_VERSION
    call_stage: str = RAG_AGENT_POST_RANKING_STAGE
    candidate_scoped: bool = True
    candidate_generation_allowed: bool = False
    ranking_input_replacement_allowed: bool = False
    promotion_allowed: bool = False
    public_payload_allowed: bool = False
    item_support: dict[str, list[dict[str, str]]] = field(default_factory=dict)
    comparison_points: list[str] = field(default_factory=list)
    missing_info: list[str] = field(default_factory=list)
    used_evidence_count: int = 0
    used_parent_profile_count: int = 0
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RagAgentQuerySupport:
    schema_version: str = RAG_AGENT_QUERY_SUPPORT_SCHEMA_VERSION
    call_stage: str = RAG_AGENT_PRE_RETRIEVAL_STAGE
    query: str = ""
    query_rewrite: str = ""
    semantic_query_hint: str = ""
    suggested_query_terms: list[str] = field(default_factory=list)
    retrieval_hints: dict[str, Any] = field(default_factory=dict)
    candidate_generation_allowed: bool = False
    ranking_input_replacement_allowed: bool = False
    promotion_allowed: bool = False
    public_payload_allowed: bool = False
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RagAgentShadowReport:
    loop_mode: str = "rag_agent_shadow"
    write_mode: str = "legacy_turn_internal_only"
    output_mode: str = "internal_only"
    candidate_scoped: bool = True
    candidate_generation_allowed: bool = False
    ranking_input_replacement_allowed: bool = False
    promotion_allowed: bool = False
    status: str = "skipped"
    action: str = "skip"
    used_evidence_count: int = 0
    used_parent_profile_count: int = 0
    trace_steps: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RagAgentInvocation:
    agent_name: str = "rag_agent"
    description: str = "Invoke RagAgent child agent"
    stage: str = RAG_AGENT_PRE_RETRIEVAL_STAGE
    prompt_or_task: str = ""
    session_id: str = ""
    turn_index: int | None = None
    request_id: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    visibility: str = "internal_only"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RagAgentMessageEnvelope:
    sender: str = "rs_agent"
    receiver: str = "rag_agent"
    stage: str = RAG_AGENT_PRE_RETRIEVAL_STAGE
    request_id: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RagAgentResponse:
    status: str = "skipped"
    stage: str = ""
    action: str = "skip"
    request_id: str = ""
    query_support: RagAgentQuerySupport | None = None
    support: RagAgentSupport | None = None
    shadow_report: RagAgentShadowReport | None = None
    diagnostics: dict[str, Any] = field(default_factory=dict)
    commit_intents: list[dict[str, Any]] = field(default_factory=list)
    public_output: dict[str, Any] = field(default_factory=dict)
    sft_output: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["query_support"] = self.query_support.to_dict() if self.query_support else None
        payload["support"] = self.support.to_dict() if self.support else None
        payload["shadow_report"] = self.shadow_report.to_dict() if self.shadow_report else None
        return payload


class RagContextBuilder:
    def __init__(self, turn: AgentTurn, config: RagAgentConfig) -> None:
        self.turn = turn
        self.config = config

    def build_context(self, loop_input: AgentLoopInput) -> dict[str, Any]:
        rag_context = self.turn.rag_context if isinstance(self.turn.rag_context, dict) else {}
        candidate_item_ids = _candidate_ids(rag_context, self.turn)
        scoped_evidence: list[dict[str, Any]] = []
        parent_evidence: list[dict[str, Any]] = []
        small_evidence: list[dict[str, Any]] = []
        for row in rag_context.get("evidence") or []:
            if not isinstance(row, dict) or str(row.get("item_id") or "") not in candidate_item_ids:
                continue
            scoped_evidence.append(row)
            if row.get("field") == RAG_PARENT_PROFILE_FIELD or _metadata(row).get("requires_parent_context_agent") is True:
                parent_evidence.append(row)
            else:
                small_evidence.append(row)
        return {
            "query": str(rag_context.get("query") or loop_input.user_input or self.turn.user_input or ""),
            "candidate_item_ids": sorted(candidate_item_ids),
            "evidence": scoped_evidence,
            "small_evidence": small_evidence,
            "parent_evidence": parent_evidence,
            "max_support_per_item": self.config.max_support_per_item,
            "max_text_chars": self.config.max_text_chars,
            "rag_metadata": rag_context.get("metadata") if isinstance(rag_context.get("metadata"), dict) else {},
        }


class RagPlanner:
    def plan(self, loop_input: AgentLoopInput, context: dict[str, Any]) -> AgentPlan:
        if not context.get("evidence"):
            return AgentPlan(action="skip", metadata={"reason": "missing_rag_evidence"})
        calls = [ToolCall(tool_name="summarize_rag_context", phase="evidence")]
        action = "summarize_parent_context" if context.get("parent_evidence") else "summarize_item_evidence"
        return AgentPlan(action=action, tool_calls=calls, metadata={"internal_only": True})


class RagToolDispatcher:
    def execute(self, plan: AgentPlan, context: dict[str, Any]) -> tuple[list[ToolResult], ToolSummary]:
        if plan.action == "skip":
            return [], ToolSummary(supported=True, phase="evidence", requested_count=0, result_count=0, skipped_count=1)
        support = _build_support(context)
        results = [
            ToolResult(
                tool_name="summarize_rag_context",
                phase="evidence",
                status="ok",
                output={"rag_agent_support": support.to_dict()},
            )
        ]
        return results, ToolSummary(
            supported=True,
            phase="evidence",
            requested_count=len(plan.tool_calls),
            result_count=len(results),
            executed_count=1,
        )


class RagResponseComposer:
    def compose(
        self,
        loop_input: AgentLoopInput,
        context: dict[str, Any],
        plan: AgentPlan,
        tool_results: list[ToolResult],
    ) -> dict[str, Any]:
        support = _support_from_results(tool_results) or RagAgentSupport(
            diagnostics={"status": "skipped", "reason": plan.metadata.get("reason", "missing_support")}
        ).to_dict()
        return {
            "rag_agent_support": support,
            "sanitized_rag_summary_citation": _compact_citations(support),
        }


class RagStateUpdater:
    def build_patch(
        self,
        loop_input: AgentLoopInput,
        context: dict[str, Any],
        plan: AgentPlan,
        tool_results: list[ToolResult],
        response: dict[str, Any],
    ) -> tuple[RuntimePatch, list[CommitIntent]]:
        support = response.get("rag_agent_support") if isinstance(response.get("rag_agent_support"), dict) else {}
        diagnostics = {
            "status": "ok" if support.get("used_evidence_count", 0) else "skipped",
            "action": plan.action,
            "candidate_scoped": True,
            "candidate_generation_allowed": False,
            "ranking_input_replacement_allowed": False,
            "promotion_allowed": False,
            "used_evidence_count": int(support.get("used_evidence_count", 0) or 0),
            "used_parent_profile_count": int(support.get("used_parent_profile_count", 0) or 0),
        }
        patch = RuntimePatch(
            trace_events=[TraceEvent(step="rag_agent_support", kind="support_built", payload=diagnostics)],
            diagnostics_patch={"rag_agent": diagnostics},
            output_patch={"rag_agent_support": support, "sanitized_rag_summary_citation": response.get("sanitized_rag_summary_citation", [])},
        )
        intents = [
            CommitIntent(
                intent_type="attach_rag_agent_support",
                payload={"diagnostics_key": "rag_agent_support"},
                owner="rag_agent_adapter",
                append_allowed=False,
            )
        ]
        return patch, intents


class RagAgentAdapter:
    diagnostics_key = "rag_agent_shadow"
    support_key = "rag_agent_support"

    def __init__(self, config: RagAgentConfig | None = None, runner: AgentRunner | None = None) -> None:
        self.config = config or RagAgentConfig()
        self.runner = runner or _build_rag_agent_runner(self)

    def build_loop(self, turn: AgentTurn, config: RagAgentConfig | None = None) -> GenericAgentLoop:
        active_config = config or self.config
        return GenericAgentLoop(
            context_builder=RagContextBuilder(turn, active_config),
            planner=RagPlanner(),
            tool_dispatcher=RagToolDispatcher(),
            response_composer=RagResponseComposer(),
            state_updater=RagStateUpdater(),
            output_adapter=OutputAdapter(
                OutputProjectionPolicy(
                    public_fields=frozenset(),
                    sft_fields=frozenset(),
                    internal_fields=frozenset({"rag_agent_support", "diagnostics", "trace_events", "commit_intents"}),
                )
            ),
        )

    def invoke(self, invocation: RagAgentInvocation, config: RagAgentConfig | None = None) -> RagAgentResponse:
        envelope = RagAgentMessageEnvelope(
            sender="rs_agent",
            receiver=invocation.agent_name or "rag_agent",
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

    def handle_message(self, envelope: RagAgentMessageEnvelope, config: RagAgentConfig | None = None) -> RagAgentResponse:
        metadata = dict(envelope.metadata)
        metadata["config"] = config or self.config
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
        response = result.output.get("rag_agent_response")
        if isinstance(response, RagAgentResponse):
            return response
        return RagAgentResponse(
            status=result.status,
            stage=result.stage,
            request_id=result.request_id,
            diagnostics={**result.diagnostics, "internal_only": True},
            public_output=result.public_output,
            sft_output=result.sft_output,
        )

    def _handle_message_direct(self, envelope: RagAgentMessageEnvelope, config: RagAgentConfig | None = None) -> RagAgentResponse:
        active_config = config or self.config
        stage = str(envelope.stage or "").strip()
        if envelope.receiver != "rag_agent":
            return RagAgentResponse(
                status="error",
                stage=stage,
                request_id=envelope.request_id,
                diagnostics={"status": "error", "reason": "invalid_receiver", "internal_only": True},
            )
        if stage == RAG_AGENT_PRE_RETRIEVAL_STAGE:
            payload = envelope.payload if isinstance(envelope.payload, dict) else {}
            support = self.build_query_support(
                query=str(payload.get("query") or ""),
                evidence=payload.get("evidence") if isinstance(payload.get("evidence"), list) else None,
                applied=bool(payload.get("applied", False)),
                reason=str(payload.get("reason") or ""),
                metadata=payload.get("metadata") if isinstance(payload.get("metadata"), dict) else None,
                query_rewrite=str(payload.get("query_rewrite") or "") or None,
                semantic_query_hint=str(payload.get("semantic_query_hint") or "") or None,
                suggested_query_terms=payload.get("suggested_query_terms") if isinstance(payload.get("suggested_query_terms"), list) else None,
            )
            return RagAgentResponse(
                status=str(support.diagnostics.get("status") or "skipped"),
                stage=stage,
                action="build_query_support" if support.semantic_query_hint else "skip",
                request_id=envelope.request_id,
                query_support=support,
                diagnostics={"status": support.diagnostics.get("status", "skipped"), "internal_only": True, "public_payload_allowed": False},
                public_output={},
                sft_output={},
            )
        if stage == RAG_AGENT_POST_RANKING_STAGE:
            payload = envelope.payload if isinstance(envelope.payload, dict) else {}
            turn = payload.get("turn")
            if not isinstance(turn, AgentTurn):
                report = RagAgentShadowReport(status="skipped", errors=["missing_parent_turn"])
                return RagAgentResponse(
                    status="skipped",
                    stage=stage,
                    action="skip",
                    request_id=envelope.request_id,
                    shadow_report=report,
                    diagnostics={"status": "skipped", "reason": "missing_parent_turn", "internal_only": True},
                )
            return self._invoke_post_ranking(turn, active_config, envelope.request_id)
        return RagAgentResponse(
            status="error",
            stage=stage,
            request_id=envelope.request_id,
            diagnostics={"status": "error", "reason": "unsupported_stage", "internal_only": True},
        )

    def _invoke_post_ranking(self, turn: AgentTurn, config: RagAgentConfig, request_id: str = "") -> RagAgentResponse:
        try:
            result = self.build_loop(turn, config).run(
                AgentLoopInput(
                    agent_name="rag_agent",
                    user_input=turn.user_input,
                    session_id=str(turn.diagnostics.get("session_id") or ""),
                    state={"turn_index": turn.turn_index},
                    metadata={"mode": config.mode},
                )
            )
            support_payload = result.response.get("rag_agent_support") if isinstance(result.response.get("rag_agent_support"), dict) else {}
            support = RagAgentSupport(**{key: value for key, value in support_payload.items() if key in RagAgentSupport.__dataclass_fields__}) if support_payload else None
            report = RagAgentShadowReport(
                status="ok" if support_payload.get("used_evidence_count", 0) else "skipped",
                action=result.plan.action,
                used_evidence_count=int(support_payload.get("used_evidence_count", 0) or 0),
                used_parent_profile_count=int(support_payload.get("used_parent_profile_count", 0) or 0),
                trace_steps=[event.step for event in result.trace_events],
            )
            return RagAgentResponse(
                status=report.status,
                stage=RAG_AGENT_POST_RANKING_STAGE,
                action=result.plan.action,
                request_id=request_id,
                support=support,
                shadow_report=report,
                diagnostics=report.to_dict(),
                commit_intents=[asdict(intent) for intent in result.commit_intents],
                public_output=result.public_output,
                sft_output=result.sft_output,
            )
        except Exception as exc:  # defensive: RagAgent child invocation must not break legacy turn
            report = RagAgentShadowReport(status="error", errors=[f"{type(exc).__name__}: {exc}"])
            return RagAgentResponse(
                status="error",
                stage=RAG_AGENT_POST_RANKING_STAGE,
                action="skip",
                request_id=request_id,
                shadow_report=report,
                diagnostics=report.to_dict(),
            )

    def run_shadow(self, turn: AgentTurn, config: RagAgentConfig | None = None) -> tuple[RagAgentShadowReport, dict[str, Any]]:
        active_config = config or self.config
        response = self.invoke(
            RagAgentInvocation(
                description="post-ranking RagAgent shadow support",
                stage=RAG_AGENT_POST_RANKING_STAGE,
                prompt_or_task="Compress candidate-scoped RAG evidence for the current turn.",
                session_id=str(turn.diagnostics.get("session_id") or ""),
                turn_index=turn.turn_index,
                request_id=f"rag-post-{turn.turn_index}",
                payload={"turn": turn},
            ),
            active_config,
        )
        report = response.shadow_report or RagAgentShadowReport(status=response.status, action=response.action)
        support = response.support.to_dict() if response.support else {}
        return report, support

    def attach_shadow_report(self, turn: AgentTurn, config: RagAgentConfig | None = None) -> RagAgentShadowReport:
        active_config = config or self.config
        report, support = self.run_shadow(turn, active_config)
        turn.diagnostics[self.diagnostics_key] = report.to_dict()
        if active_config.attach_support_to_diagnostics and support and int(support.get("used_evidence_count", 0) or 0) > 0:
            turn.diagnostics[self.support_key] = support
        return report

    def build_query_support(
        self,
        *,
        query: str,
        evidence: list[Any] | None = None,
        applied: bool = False,
        reason: str = "",
        metadata: dict[str, Any] | None = None,
        query_rewrite: str | None = None,
        semantic_query_hint: str | None = None,
        suggested_query_terms: list[str] | None = None,
    ) -> RagAgentQuerySupport:
        clean_query = str(query or "").strip()
        evidence_rows = evidence or []
        terms = _clean_suggested_terms(suggested_query_terms or [])
        if not terms and evidence_rows:
            terms = _query_support_suggested_terms(clean_query, evidence_rows)
        rewrite = _safe_retrieval_text(query_rewrite, 220) or ""
        if not rewrite:
            rewrite = " ".join(part for part in [clean_query, " ".join(terms)] if part).strip()
        hint = _safe_retrieval_text(semantic_query_hint, 260) or ""
        if not hint:
            hint = " ".join(part for part in [rewrite or clean_query, " ".join(terms)] if part).strip()
        return RagAgentQuerySupport(
            query=clean_query,
            query_rewrite=rewrite,
            semantic_query_hint=hint,
            suggested_query_terms=terms,
            retrieval_hints={
                **_query_support_boundaries(applied=applied and bool(evidence_rows)),
                "semantic_query": hint,
                "normalized_query": rewrite,
                "suggested_query_terms": terms,
            },
            diagnostics={
                "compact": True,
                "internal_only": True,
                "status": "ok" if applied and evidence_rows else "skipped",
                "reason": reason,
                "evidence_count": len(evidence_rows),
                "retrieval_scope": "query_planning",
                "candidate_scoped": False,
                **(metadata or {}),
            },
        )


class _RagAgentHandler:
    def __init__(self, adapter: RagAgentAdapter) -> None:
        self.adapter = adapter

    def run(self, request: AgentRunRequest) -> AgentRunResult:
        config = request.metadata.get("config")
        active_config = config if isinstance(config, RagAgentConfig) else self.adapter.config
        envelope = RagAgentMessageEnvelope(
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
            output={"rag_agent_response": response},
            diagnostics=response.diagnostics,
            public_output=response.public_output,
            sft_output=response.sft_output,
        )


def _build_rag_agent_runner(adapter: RagAgentAdapter) -> AgentRunner:
    registry = AgentRegistry()
    registry.register(
        AgentDefinition(
            name="rag_agent",
            description="Internal candidate-scoped RAG evidence and query support agent.",
            supported_stages=frozenset({RAG_AGENT_PRE_RETRIEVAL_STAGE, RAG_AGENT_POST_RANKING_STAGE}),
            default_visibility="internal_only",
            handler=_RagAgentHandler(adapter),
        )
    )
    return AgentRunner(registry)


def _build_support(context: dict[str, Any]) -> RagAgentSupport:
    candidate_ids = set(str(item_id) for item_id in context.get("candidate_item_ids", []) if str(item_id))
    max_per_item = max(0, int(context.get("max_support_per_item", 3) or 0))
    max_text_chars = max(0, int(context.get("max_text_chars", 220) or 0))
    item_support: dict[str, list[dict[str, str]]] = {}
    used_evidence_count = 0
    used_parent_profile_count = 0

    for row in context.get("evidence", []) or []:
        if not isinstance(row, dict):
            continue
        item_id = str(row.get("item_id") or "")
        if not item_id or item_id not in candidate_ids:
            continue
        bucket = item_support.setdefault(item_id, [])
        if len(bucket) >= max_per_item:
            continue
        field_name = str(row.get("field") or "")
        metadata = _metadata(row)
        if field_name == RAG_PARENT_PROFILE_FIELD or metadata.get("requires_parent_context_agent") is True:
            support = _parent_profile_support(row, max_text_chars)
            if not support:
                continue
            used_parent_profile_count += 1
        else:
            support = _small_evidence_support(row, max_text_chars)
            if not support:
                continue
        bucket.append(support)
        used_evidence_count += 1

    return RagAgentSupport(
        item_support={item_id: rows for item_id, rows in item_support.items() if rows},
        comparison_points=_comparison_points(item_support),
        missing_info=[] if item_support else ["no_candidate_scoped_rag_evidence"],
        used_evidence_count=used_evidence_count,
        used_parent_profile_count=used_parent_profile_count,
        diagnostics={
            "compact": True,
            "internal_only": True,
            "candidate_count": len(candidate_ids),
            "evidence_raw_retained": False,
            "retains_parent_profile_raw_text": False,
        },
    )


def _small_evidence_support(row: dict[str, Any], max_text_chars: int) -> dict[str, str]:
    field_name = _safe_field_name(row.get("field"))
    text = _sanitize_evidence_text(row.get("text"), max_text_chars)
    if not text:
        return {}
    return {
        "field": field_name,
        "summary": text,
        "evidence_hint": f"candidate-scoped {field_name}",
    }


def _parent_profile_support(row: dict[str, Any], max_text_chars: int) -> dict[str, str]:
    metadata = _metadata(row)
    fields = _safe_parent_profile_fields(metadata.get("parent_projection_fields", []))
    if not fields:
        fields = _safe_parent_profile_fields(_parent_profile_labels(row.get("text")))
    if not fields:
        fields = ["parent_profile"]
    summary = _truncate_text("商品级画像可用字段: " + ", ".join(fields), max_text_chars)
    return {
        "field": RAG_PARENT_PROFILE_FIELD,
        "summary": summary,
        "evidence_hint": "small2big parent profile compressed; raw text withheld",
    }


def _parent_profile_labels(value: Any) -> list[str]:
    labels: list[str] = []
    for line in str(value or "").splitlines():
        if ":" not in line:
            continue
        label = line.split(":", 1)[0].strip().lower().replace(" ", "_")
        if label and label not in labels:
            labels.append(label)
    return labels


def _comparison_points(item_support: dict[str, list[dict[str, str]]]) -> list[str]:
    if len(item_support) <= 1:
        return []
    return ["候选商品均基于候选内 RAG evidence 压缩，比较时仍以既有排序结果为准。"]


def _compact_citations(support: dict[str, Any]) -> list[dict[str, str]]:
    citations: list[dict[str, str]] = []
    item_support = support.get("item_support") if isinstance(support.get("item_support"), dict) else {}
    for item_id, rows in item_support.items():
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            field_name = str(row.get("field") or "")
            if field_name:
                citations.append({"item_id": str(item_id), "field": field_name})
    return citations


def _support_from_results(tool_results: list[ToolResult]) -> dict[str, Any] | None:
    for result in tool_results:
        output = result.output if isinstance(result.output, dict) else {}
        support = output.get("rag_agent_support")
        if isinstance(support, dict):
            return support
    return None


def _build_query_rewrite_messages(query: str) -> list[dict[str, str]]:
    contract = {
        "task": "Normalize a shopping query for internal RAG retrieval planning.",
        "rules": [
            "If the query is Chinese or mixed-language, translate and normalize it into concise English product-search terms.",
            "Keep the output about product attributes, use cases, comparison entities, and retrieval terms only.",
            "Do not mention tools, retrievers, scores, sources, traces, diagnostics, candidates, labels, oracle fields, or item ids.",
            "Return exactly one JSON object matching output_contract.",
        ],
        "output_contract": {
            "query_rewrite": "non-empty concise English product-search query, max 200 chars",
            "semantic_query_hint": "short English retrieval hint, max 260 chars",
            "suggested_query_terms": "array of up to 8 short English terms",
        },
        "original_query": query,
    }
    return [
        {"role": "system", "content": "You are RagAgent's internal bilingual query normalization component. Return only safe JSON for RAG query planning."},
        {"role": "user", "content": json.dumps(contract, ensure_ascii=False, sort_keys=True)},
    ]


def _extract_first_json_object(text: str) -> dict[str, Any]:
    compact = _strip_markdown_fence(str(text or "").strip())
    start = compact.find("{")
    if start < 0:
        raise ValueError("Rag query rewrite response did not contain a JSON object")
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(compact)):
        char = compact[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                payload = json.loads(compact[start:index + 1])
                if not isinstance(payload, dict):
                    raise ValueError("Rag query rewrite JSON root must be an object")
                return payload
    raise ValueError("Rag query rewrite response JSON object was incomplete")


def _query_rewrite_result_from_payload(query: str, payload: dict[str, Any]) -> RagQueryRewriteResult:
    rewrite = _safe_retrieval_text(payload.get("query_rewrite"), 200)
    if not rewrite:
        raise ValueError("query_rewrite_required")
    hint = _safe_retrieval_text(payload.get("semantic_query_hint"), 260) or rewrite
    terms = _clean_suggested_terms(payload.get("suggested_query_terms"))
    return RagQueryRewriteResult(
        query=query,
        query_rewrite=rewrite,
        semantic_query_hint=hint,
        suggested_query_terms=terms,
        diagnostics={},
    )


def _safe_retrieval_text(value: Any, max_chars: int) -> str:
    text = " ".join(str(value or "").strip().split())
    if not text:
        return ""
    text = _truncate_text(text, max_chars)
    if _QUERY_REWRITE_FORBIDDEN_PATTERN.search(text):
        raise ValueError("query_rewrite_internal_leakage")
    return text


def _clean_suggested_terms(value: Any) -> list[str]:
    raw_terms = value if isinstance(value, list | tuple | set) else []
    terms: list[str] = []
    for raw_term in raw_terms:
        term = _safe_retrieval_text(raw_term, 40).lower()
        if not term or term in terms:
            continue
        terms.append(term)
        if len(terms) >= 8:
            break
    return terms


def _strip_markdown_fence(text: str) -> str:
    match = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", text, flags=re.DOTALL | re.IGNORECASE)
    return match.group(1) if match else text


def _query_support_boundaries(*, applied: bool) -> dict[str, Any]:
    return {
        "applied": applied,
        "retrieval_scope": "query_planning",
        "candidate_generation_allowed": False,
        "ranking_input_replacement_allowed": False,
        "promotion_allowed": False,
        "public_payload_allowed": False,
    }


def _query_support_suggested_terms(query: str, evidence: list[Any]) -> list[str]:
    existing = set(_tokens(query))
    blocked = existing | {"and", "with", "for", "the", "item", "product", "recommend"}
    terms: list[str] = []
    for row in evidence:
        field_name = str(getattr(row, "field", "") or _dict_get(row, "field") or "")
        text = str(getattr(row, "text", "") or _dict_get(row, "text") or "")
        for token in _tokens(f"{field_name} {text}"):
            if token in blocked or token in terms or len(token) < 3:
                continue
            terms.append(token)
            if len(terms) >= 8:
                return terms
    return terms


def _tokens(value: Any) -> list[str]:
    return re.findall(r"[a-zA-Z0-9一-鿿]+", str(value or "").lower())


def _dict_get(value: Any, key: str) -> Any:
    return value.get(key) if isinstance(value, dict) else None


def _candidate_ids(rag_context: dict[str, Any], turn: AgentTurn) -> set[str]:
    explicit_ids = {str(item_id) for item_id in rag_context.get("candidate_item_ids", []) if str(item_id)}
    if explicit_ids:
        return explicit_ids
    ids: set[str] = set()
    for item in [*turn.recommendation.final_items, *turn.ranking]:
        if isinstance(item, dict):
            item_id = str(item.get("parent_asin") or item.get("item_id") or item.get("asin") or "")
            if item_id:
                ids.add(item_id)
    return ids


def _metadata(row: dict[str, Any]) -> dict[str, Any]:
    value = row.get("metadata")
    return value if isinstance(value, dict) else {}


def _safe_field_name(value: Any) -> str:
    field_name = str(value or "evidence").strip().lower()
    return field_name if field_name in _SAFE_EVIDENCE_FIELDS else "evidence"


def _safe_parent_profile_fields(value: Any) -> list[str]:
    if isinstance(value, str):
        raw_fields = [value]
    elif isinstance(value, list | tuple | set):
        raw_fields = list(value)
    else:
        raw_fields = []
    fields: list[str] = []
    for raw_field in raw_fields:
        field_name = str(raw_field or "").strip().lower().replace(" ", "_")
        if field_name in _INTERNAL_FIELD_NAMES or field_name not in _SAFE_EVIDENCE_FIELDS:
            continue
        if field_name not in fields:
            fields.append(field_name)
    return fields


def _sanitize_evidence_text(value: Any, max_chars: int) -> str:
    text = _truncate_text(value, max_chars)
    if not text or _SENSITIVE_TEXT_PATTERN.search(text):
        return "候选内商品证据已压缩，原始文本保留在内部 RAG 上下文。"
    return text


def _truncate_text(value: Any, max_chars: int) -> str:
    text = str(value or "").strip()
    if max_chars <= 0:
        return ""
    if len(text) <= max_chars:
        return text
    if max_chars <= 3:
        return text[:max_chars]
    return text[: max_chars - 3].rstrip() + "..."


def _mode_config(value: Any) -> str:
    mode = str(value or "shadow").strip().lower()
    if mode not in {"shadow"}:
        raise ValueError(f"Unsupported RagAgent mode: {value}")
    return mode


def _safe_float(value: Any, default: float) -> float:
    parsed = _optional_float(value, None)
    return default if parsed is None else parsed


def _optional_float(value: Any, default: float | None) -> float | None:
    if value in (None, ""):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _optional_int(value: Any, default: int | None) -> int | None:
    if value in (None, ""):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _bool_value(value: Any, default: bool) -> bool:
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
        return default
    return bool(value)


def _int_config(config: dict[str, Any], key: str, default: int) -> int:
    value = config.get(key, default)
    if value in (None, ""):
        return default
    return int(value)


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


__all__ = [
    "RAG_AGENT_POST_RANKING_STAGE",
    "RAG_AGENT_PRE_RETRIEVAL_STAGE",
    "RAG_AGENT_QUERY_SUPPORT_SCHEMA_VERSION",
    "RAG_AGENT_SUPPORT_SCHEMA_VERSION",
    "RAG_AGENT_SYSTEM_PROMPT",
    "RagAgentAdapter",
    "RagAgentConfig",
    "RagAgentInvocation",
    "RagAgentMessageEnvelope",
    "RagAgentResponse",
    "RagAgentQuerySupport",
    "RagQueryRewriteConfig",
    "RagQueryRewriteResult",
    "RagQueryRewriter",
    "RagAgentShadowReport",
    "RagAgentSupport",
]
