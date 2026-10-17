# Agent 系统提示词规范

本文档用于统一 RS_agent 项目中各类 Agent 的系统提示词写法，适用于 RecommendationAgent、首页 Agent、RagAgent、模拟用户 Agent，以及后续扩展的专用 Agent。目标是让每个 Agent 的 prompt 不只是“角色描述”，而是一个可复用、可审查、可训练的运行合同。

## 1. 总体形式

Agent 系统提示词默认采用 OpenAI 推荐的 Markdown 四段式组织：`Identity`、`Instructions`、`Examples`、`Context`。内容默认中文；工具名、字段名、模型名和代码标识符保留英文。XML 仅在需要包裹多份输入资料、嵌套示例或附加元数据时使用，不能作为默认的行为分段格式。

示例结构：

```text
# Identity

这里写 Agent 的人设、职责、服务对象和核心目标。

# Instructions

这里写规则、工作流、工具使用边界和禁止事项。

# Examples

这里放少量能说明关键判断的正反例。

# Context

这里说明本回合运行时会传入哪些上下文，以及哪些边界由运行时强制执行。
```

## 2. 标准标签

通用 Agent prompt 应包含以下四个一级标题；复杂规则用二级标题和项目符号表达，不需要为每一类规则新造 XML 标签。

```text
# Identity

描述 Agent 是谁、服务谁、负责什么及最终目标。说明在本项目中的工程职责，例如推荐、首页导购、RAG 证据整理、用户模拟或质量检查。

# Instructions

用二级标题分别写成功标准、上下文取舍、工具工作流、运行时边界和输出风格。工具描述只说明何时使用及结果能否影响候选或公开输出，不重复 schema。禁止事项应覆盖数据、工具、分数、候选池、raw evidence、labels、oracle、diagnostics 和 trace 泄露。

# Examples

提供一个好例与一个坏例。好例体现成功标准和边界；坏例覆盖项目最容易犯的错误，例如暴露工具名、用分数解释、候选弱还硬夸，或 RAG 越过候选边界。

# Context

说明运行时将提供的用户历史、商品历史、页面行为、RAG evidence、session memory 或多轮对话，并说明强弱信号与降权条件。明确候选集合、工具 schema、输出投影和安全拦截由运行时强制执行，prompt 不得替代或绕过它们。
```

## 3. 可选标签

不同 Agent 可在 `# Instructions` 下增加专用二级标题：

```text
## Clarification policy

用于需要多轮对话的 Agent，说明什么时候应该追问，什么时候应先执行工具或给出可用结果。

## User history use

用于推荐、首页导购、个性化解释等 Agent，说明用户历史不是静态标签，而是带有时间、行为强度、商品生命周期和当前相关性的证据。

## Evidence boundary

用于 RagAgent 或解释 Agent，说明 evidence 只能支持已候选/已展示对象，不能新增候选、替代排序、暴露 raw evidence 或泄露 source diagnostics。

## Page context use

用于首页 Agent，说明如何使用入口页面、当前展示模块、用户点击/停留/搜索等上下文，以及不能让首页 Agent 越权替代推荐主链路。

## Output format

用于需要结构化输出的 Planner、Critic、Evaluator 或 SFT 生成 Agent，说明 JSON 字段、字段含义、禁止字段和失败时的降级输出。可使用 API 的 JSON Schema/Structured Outputs 强制结构，不能只依赖 prompt 文本。
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

当前 RecommendationAgent 的提示词落在 `rs_core/agent/tools/__init__.py` 的 `AGENT_TOOL_BOUNDARY_SYSTEM_PROMPT`，并通过 `build_agent_tool_planner_system_prompt()` 与 hidden tool manifest summary 拼接。旧 `rs_core/rsagent` active package 已删除；后续首页 Agent、RagAgent 或其他专用 Agent 如果进入通用 `GenericAgentLoop`，应按本文档的 Markdown 四段式维护各自 prompt，并在 adapter 层保证 public/SFT/internal projection 边界不被 prompt 文本绕过。
