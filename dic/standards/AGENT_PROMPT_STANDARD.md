# Agent 系统提示词规范

本文档用于统一 RS_agent 项目中各类 Agent 的系统提示词写法，适用于 RecommendationAgent、首页 Agent、RagAgent、模拟用户 Agent，以及后续扩展的专用 Agent。目标是让每个 Agent 的 prompt 不只是“角色描述”，而是一个可复用、可审查、可训练的运行合同。

## 1. 总体形式

Agent 系统提示词默认采用 XML-like 标签块组织。最外层不再包 `<Agent_Prompt>`，每个标签块内部用一整段连续描述表达，不写成过细的项目符号列表。标签名使用英文，内容默认中文；工具名、字段名、模型名和代码标识符保留英文。

示例结构：

```text
<Role_And_Duty>
这里写 Agent 的人设、职责、服务对象和核心目标。
</Role_And_Duty>

<Why_This_Matters>
这里写为什么需要这个 Agent，它在系统中解决什么问题，不只是重复功能说明。
</Why_This_Matters>
```

## 2. 标准标签

通用 Agent prompt 建议至少包含以下标签：

```text
<Role_And_Duty>
描述这个 Agent 是谁、服务谁、负责什么、最终目标是什么。这里要避免空泛角色词，要说明它在本项目中的工程职责，例如推荐、首页导购、RAG 证据整理、用户模拟、质量检查等。
</Role_And_Duty>

<Why_This_Matters>
描述为什么需要这个 Agent，以及它弥补底层模型、工具、检索、排序或前端展示的哪类不足。这里用于让模型理解自己的存在价值，而不是只按模板执行。
</Why_This_Matters>

<Success_Standard>
描述什么叫一次成功运行。成功标准必须面向最终业务结果和用户体验，而不是只写“调用了工具”或“输出了 JSON”。例如推荐 Agent 的成功是顾客更接近满意选择，RagAgent 的成功是证据支持更准确且不越过候选边界，首页 Agent 的成功是把用户有效引导到合适入口或场景。
</Success_Standard>

<Context_Use>
描述 Agent 可以使用哪些上下文，以及如何权衡上下文。凡是涉及用户历史、商品历史、页面行为、RAG evidence、session memory 或多轮对话，都要说明哪些信息是强信号、哪些只是辅助证据，哪些情况需要降权或忽略。
</Context_Use>

<Tool_Workflow>
描述工具在工作流程中的位置，而不是重复工具 schema。工具本身已有 description，这里只说明什么时候先理解输入、什么时候读取上下文、什么时候检索、什么时候排序、什么时候取证据、什么时候生成展示，以及哪些工具结果不能改变候选或公开输出。
</Tool_Workflow>

<Runtime_Boundary>
描述运行过程中允许和禁止的事情。边界要覆盖数据泄漏、工具泄漏、候选集合外推荐、编造属性、越权使用上下文、把内部诊断公开、把 shadow 结果当最终结果等问题。
</Runtime_Boundary>

<Response_Style>
描述输出语气、长度、结构和面向用户的表达方式。这里要区分 public response、internal summary、SFT supervision、debug diagnostics，不同 Agent 可以有不同输出风格。
</Response_Style>

<Good_Output_Example>
给一个符合该 Agent 职责的好输出范例。范例要体现成功标准和边界，例如不泄露工具、不夸大证据、不机械复述历史、不把内部字段暴露给用户。
</Good_Output_Example>

<Bad_Output_Example>
给一个坏输出范例，并通过内容本身体现它为什么坏。坏例子应覆盖项目最容易犯的错误，例如暴露工具名、用分数解释、候选弱还硬夸、RAG 越过候选边界、首页强行推荐、模拟用户知道 hidden catalog 等。
</Bad_Output_Example>
```

## 3. 可选标签

不同 Agent 可以按职责增加专用标签：

```text
<Clarification_Policy>
用于需要多轮对话的 Agent，说明什么时候应该追问，什么时候应该先执行工具或先给出可用结果。
</Clarification_Policy>

<User_History_Use>
用于推荐、首页导购、个性化解释等 Agent，说明用户历史不是静态标签，而是带有时间、行为强度、商品生命周期和当前相关性的证据。
</User_History_Use>

<Evidence_Boundary>
用于 RagAgent 或解释 Agent，说明 evidence 只能支持已候选/已展示对象，不能新增候选、替代排序、暴露 raw evidence 或泄露 source diagnostics。
</Evidence_Boundary>

<Page_Context_Use>
用于首页 Agent，说明如何使用入口页面、当前展示模块、用户点击/停留/搜索等上下文，以及不能让首页 Agent 越权替代推荐主链路。
</Page_Context_Use>

<Output_Format>
用于需要结构化输出的 Planner、Critic、Evaluator 或 SFT 生成 Agent，说明 JSON 字段、字段含义、禁止字段和失败时的降级输出。
</Output_Format>
```

## 4. 推荐 Agent 专用补充

推荐 Agent 必须强调当前需求优先于历史偏好。用户历史不是静态偏好标签，而是有时效、行为强度、商品生命周期和当前相关性的证据。最近买过的耐用品通常不应重复推荐同类主商品，耗材和配件可以因为最近购买而更相关；历史关键词只有在和当前请求相关时才增强权重。如果历史偏好与当前需求冲突，必须以当前需求为主。

推荐 Agent 的工具说明应写成工作流：先理解当前输入，再读取用户上下文；请求是场景型、模糊型、属性型或自然购物语言时，可以使用受控商品知识或查询扩展能力；随后召回候选、排序、检查 slate 质量、取 display-safe 证据并生成推荐展示。不要在 prompt 中让模型选择底层 provider、source、index 或泄露 RAG/score/trace。

## 5. RagAgent 专用补充

RagAgent 的职责是整理、压缩和约束商品证据，不是召回器、排序器或推荐决策器。它只能围绕已有候选或已展示商品提供 grounded support，不能新增商品、改变排序、扩大候选边界或把 raw parent profile / raw chunk 原文直接输出。RagAgent 的成功标准是证据更准确、上下文更紧凑、解释更可验证，同时 public/SFT projection 不泄露内部 evidence、source、diagnostics 或 trace。

## 6. 首页 Agent 专用补充

首页 Agent 的职责不是直接替代推荐 Agent，而是理解用户进入首页时的意图、场景和探索状态，帮助用户进入合适的推荐入口、搜索入口、活动模块或个性化频道。它可以使用页面上下文、公开展示模块、用户最近可见行为和高层偏好摘要，但不能暴露内部召回策略、排序分数、候选池或训练标签。首页 Agent 的成功标准是降低用户找入口的成本，并把模糊需求转成可执行的下一步，而不是强行给出不受候选约束的商品推荐。

## 7. Prompt 编写检查表

新增或修改 Agent prompt 前，应检查：这个 Agent 的最终目标是否写清楚；成功标准是否能被测试或人工评审；上下文使用是否区分强信号和弱证据；工具说明是否只讲流程位置而不是重复 schema；禁止事项是否覆盖工具、分数、候选池、raw evidence、labels、oracle、diagnostics、trace；输出范例是否同时有 good 和 bad；如果该 Agent 会进入 SFT 数据，public/SFT/internal 边界是否明确。

## 8. 与代码的落点

当前 RecommendationAgent 的提示词落在 `rs_core/rsagent/tools.py` 的 `AGENT_TOOL_BOUNDARY_SYSTEM_PROMPT`，并通过 `build_agent_tool_planner_system_prompt()` 与 hidden tool manifest summary 拼接。后续首页 Agent、RagAgent 或其他专用 Agent 如果进入通用 `GenericAgentLoop`，应按本文档的标签规范维护各自 prompt，并在 adapter 层保证 public/SFT/internal projection 边界不被 prompt 文本绕过。
