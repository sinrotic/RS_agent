# 通用 GenericAgentLoop 使用说明

## 目标

`GenericAgentLoop` 是一个领域无关的 Agent 循环骨架，用来复用“输入观察 → 上下文构建 → 规划 → 工具执行 → 回复组装 → 状态补丁 → 输出投影”的基础能力。它不直接绑定推荐、模拟用户、训练数据或前端展示，因此后续可以基于同一个 loop 衍生 Recommendation Agent、Simulated User Agent、RAG QA Agent、评估 Agent 等。

当前实现仍是 skeleton：可以用于 fake-agent、离线实验和新 Agent 的适配层开发；生产 Recommendation 主路径仍默认走 legacy runtime，`generic_active` 仍保持关闭。

## 核心原则

1. **组件外置**：系统提示词、上下文、工具、规划、回复、状态写入策略都由外部组件提供。
2. **loop 不懂业务**：generic core 不导入 `rsagent`、`simulation`、`recsys`、`workflow` 等领域模块。
3. **只返回意图，不直接提交状态**：loop 返回 `RuntimePatch` 和 `CommitIntent`，由领域 adapter 决定是否写入 session、数据库或日志。
4. **输出默认最小暴露**：通过 `OutputAdapter` 显式声明 public / SFT / internal 字段；未声明字段默认不投影。
5. **工具 metadata 由 adapter 解释**：领域字段放进 `ToolSpec.metadata`，例如推荐侧字段放入 `metadata["recommendation"]`，不要提升为 generic 顶层字段。

## 组件接口

派生新 Agent 时，通常需要实现下面 5 个组件：

| 组件 | 责任 | 不应做的事 |
| --- | --- | --- |
| `ContextBuilder` | 把输入、会话摘要、记忆、可见证据组装成上下文 | 不暴露隐藏候选池、label、oracle、raw ranking |
| `Planner` | 基于上下文决定本轮动作和 `ToolCall` | 不直接执行工具或写状态 |
| `ToolDispatcher` | 校验并执行工具，返回 `ToolResult` 与 `ToolSummary` | 不把 hidden tool raw output 直接塞进 public 回复 |
| `ResponseComposer` | 组装回复 payload | 不绕过 `OutputAdapter` 输出敏感字段 |
| `StateUpdater` | 生成 `RuntimePatch` 与 `CommitIntent` | 不直接 `session.turns.append(...)` |

## 最小使用示例

```python
from rs_core.agent.runtime_core import (
    AgentLoopInput,
    AgentPlan,
    GenericAgentLoop,
    OutputAdapter,
    OutputProjectionPolicy,
    RuntimePatch,
    ToolCall,
    ToolResult,
    ToolSummary,
)

class MyContextBuilder:
    def build_context(self, loop_input):
        return {"summary": loop_input.state.get("summary", "")}

class MyPlanner:
    def plan(self, loop_input, context):
        return AgentPlan(
            action="answer",
            tool_calls=[ToolCall(tool_name="my_tool", arguments={"query": loop_input.user_input})],
        )

class MyToolDispatcher:
    def execute(self, plan, context):
        results = [ToolResult(tool_name="my_tool", phase="pre_response", status="ok", output={"text": "safe evidence"})]
        summary = ToolSummary(supported=True, phase="pre_response", requested_count=1, result_count=1, executed_count=1)
        return results, summary

class MyResponseComposer:
    def compose(self, loop_input, context, plan, tool_results):
        return {"assistant_message": tool_results[0].output["text"]}

class MyStateUpdater:
    def build_patch(self, loop_input, context, plan, tool_results, response):
        return RuntimePatch(session_summary_patch={"last_action": plan.action}), []

loop = GenericAgentLoop(
    context_builder=MyContextBuilder(),
    planner=MyPlanner(),
    tool_dispatcher=MyToolDispatcher(),
    response_composer=MyResponseComposer(),
    state_updater=MyStateUpdater(),
    output_adapter=OutputAdapter(
        OutputProjectionPolicy(public_fields=frozenset({"assistant_message"}))
    ),
)

result = loop.run(AgentLoopInput(agent_name="my_agent", user_input="hello", session_id="s1"))
print(result.public_output)
```

## 工具接入建议

工具应该注册为协议对象，而不是散落函数。建议每个工具至少包含：

- `name`
- `description`
- `input_schema`
- `output_schema`
- `read_only`
- `permission`
- `metadata`

推荐 Agent 的领域字段示例：

```python
ToolSpec(
    name="retrieve_candidates",
    description="Retrieve recommendation candidates.",
    metadata={
        "recommendation": {
            "hidden": True,
            "public_payload_allowed": False,
            "exportable_to_sft": False,
            "requires_candidate_pool": False,
            "can_search_catalog": True,
            "boundary_prompt": "Do not leak raw scores.",
        }
    },
)
```

`GenericAgentLoop` 可以携带 metadata，但不解释这些字段；解释权属于 Recommendation adapter 或其他领域 adapter。

## 输出边界

输出分三层：

- `public_output`：可给前端/用户看的字段。
- `sft_output`：可进入训练样本的字段。
- `internal_output`：内部诊断字段，但仍不能包含 secret/token/password/api key 等字段。

新增 Agent 时必须先定义 `OutputProjectionPolicy`。例如：

```python
OutputProjectionPolicy(
    public_fields=frozenset({"assistant_message", "display_items"}),
    sft_fields=frozenset({"assistant_message", "display_items", "tool_summary"}),
    internal_fields=frozenset({"assistant_message", "diagnostics", "trace_events"}),
)
```

如果字段没有出现在 allowlist 中，就不会被投影。`raw_trace`、`hidden_tool_result`、`raw_rag_evidence`、`mcpInfo`、`inputJSONSchema`、`boundary_prompt`、`loop_mode` 等字段不能进入 public/SFT。

## 状态提交边界

`StateUpdater` 只生成：

- `RuntimePatch`：trace、tool results、diagnostics、session summary、output patch。
- `CommitIntent`：表达“希望由谁提交什么状态”。

真正提交状态必须在领域 adapter 中完成。这样可以避免 generic loop 直接修改推荐 session，尤其避免重复 append turn。

推荐侧迁移期间保持：

- `session.turns.append(...)` 仍由 legacy Recommendation builder 负责。
- `generic_shadow` 只附加内部 shadow report，不改变公开输出。
- `generic_active` 在 readiness gates 通过前继续拒绝启用。

## 衍生 Agent 的推荐步骤

1. 定义 Agent 边界：这个 Agent 看到什么、不能看到什么、最终输出给谁。
2. 定义 `ToolSpec` 与工具 dispatcher：先从 local tools 开始，MCP 作为可选 provider。
3. 定义 prompt/context 组件：系统提示词和上下文组装都放在组件里，不写死在 loop 中。
4. 定义 `OutputProjectionPolicy`：先写 public/SFT/internal allowlist，再写回复逻辑。
5. 写 fake-agent 单测：不用真实 LLM、不加载大数据，先验证 loop 顺序、工具汇总、输出投影、状态补丁。
6. 接入领域 adapter：让 adapter 把领域 session 转为 `AgentLoopInput`，并消费 `RuntimePatch` / `CommitIntent`。
7. shadow 运行：先对比 legacy/generic 输出和 trace，再考虑 active。

## Recommendation Agent 后续接入方向

Recommendation Agent 可以把现有 runtime 的阶段拆成组件：

- `RecommendationContextBuilder`：封装用户画像、session summary、候选池摘要、RAG safe evidence。
- `RecommendationPlanner`：决定澄清、推荐、解释、反馈修正、工具调用。
- `RecommendationToolDispatcher`：复用现有 agent tools manifest 与校验逻辑。
- `RecommendationResponseComposer`：生成用户可见回复和展示卡片。
- `RecommendationStateUpdater`：生成 session summary patch、diagnostics patch、reward evidence patch。
- `RecommendationOutputAdapter`：保证 hidden tools、raw ranking、raw RAG evidence 不进入 public/SFT。

上线顺序仍建议：contract → fake test → shadow → golden diff → active readiness gate。

## SimulatedUserAgent 后续接入方向

模拟用户 Agent 可以复用同一个 loop，但它的边界更严格：

- 可见：persona、历史摘要、当前意图、可见对话、已展示商品。
- 不可见：商品库全量、候选池、分数、label、oracle target、raw ranking、内部工具 trace。
- 工具：通常应少于 Recommendation Agent，可先只允许记忆/偏好生成类工具。
- 输出：只输出用户自然语言动作、反馈类型、停止信号；不要输出隐藏评分依据。

这样后续生成多轮 SFT 样本时，可以让 Recommendation Agent 与 SimulatedUserAgent 都基于同一个 loop 框架，但各自拥有独立的工具集、prompt、上下文和输出策略。
