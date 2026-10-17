# pi 与 Claude Code Agent 实现对比调研

更新时间：2026-07-21  
状态：已完成。pi 使用固定公开 commit；Claude Code 使用本仓库 `参考/claudecode_src/` 本地源码快照。

## 调研边界与固定基线

- 只使用 `earendil-works/pi` 官方仓库中的源码、README、包清单和提交记录，不采用博客、第三方评测或转述。
- 固定基线为提交 [`8495f9d0d6407d4ec94e16a685df70740335dd29`](https://github.com/earendil-works/pi/commit/8495f9d0d6407d4ec94e16a685df70740335dd29)（2026-07-21，`chore: rename orchestrator to server (#6898)`）。以下链接都固定到该 commit，避免 `main` 后续变化导致证据漂移。
- 该基线中 `@earendil-works/pi-agent-core`、`@earendil-works/pi-coding-agent` 和 `@earendil-works/pi-ai` 的版本均为 `0.80.10`；仓库要求 Node.js `>=22.19.0`。见 [agent 包名/版本 L1-L4](https://github.com/earendil-works/pi/blob/8495f9d0d6407d4ec94e16a685df70740335dd29/packages/agent/package.json#L1-L4)、[pi-ai 包名/版本 L1-L4](https://github.com/earendil-works/pi/blob/8495f9d0d6407d4ec94e16a685df70740335dd29/packages/ai/package.json#L1-L4)、[coding-agent 包名/版本 L1-L4](https://github.com/earendil-works/pi/blob/8495f9d0d6407d4ec94e16a685df70740335dd29/packages/coding-agent/package.json#L1-L4)，以及 [agent engine L50-L52](https://github.com/earendil-works/pi/blob/8495f9d0d6407d4ec94e16a685df70740335dd29/packages/agent/package.json#L50-L52) 与 [coding-agent engine L97-L99](https://github.com/earendil-works/pi/blob/8495f9d0d6407d4ec94e16a685df70740335dd29/packages/coding-agent/package.json#L97-L99)。

本地仓库是单上下文布局：根目录存在 `CONTEXT.md`，不存在 `CONTEXT-MAP.md`。后续比较应使用本地术语 `Session`、`Turn`、`Session Event`、`Durable Session History`、`Effective Context`、`Context Checkpoint`、`Safe Compaction Boundary`、`Replay-safe Tool`，并逐项检查 ADR-0001 至 ADR-0008，尤其是持久化权威来源、压缩边界、工具可重放、同 Session 串行和单活实例约束。

## pi 自身实现：摘要

pi 的当前 coding agent 是一个分层的 TypeScript/Node.js 单进程程序：`pi-ai` 统一不同模型供应商，`pi-agent-core` 提供有状态工具循环，`pi-coding-agent` 再叠加本地 Session、上下文压缩、资源加载、扩展机制以及 TUI/SDK/RPC 接口。官方根 README 也把三个包分别定义为统一 LLM API、Agent runtime 和交互式 coding agent CLI。[根 README L13-L33](https://github.com/earendil-works/pi/blob/8495f9d0d6407d4ec94e16a685df70740335dd29/README.md#L13-L33)

最重要的版本辨析是：**当前 `pi-coding-agent` 仍走 `AgentSession → Agent → runAgentLoop`，仓库中的新 `AgentHarness` 尚未替换这条路径。** `createAgentSession()` 明确实例化 `Agent`，随后把它传给 `AgentSession`；新的 harness 文档则把 “Later coding-agent migration plan” 标为 `Planned`，且迁移项一个都未完成。[sdk.ts L248-L355](https://github.com/earendil-works/pi/blob/8495f9d0d6407d4ec94e16a685df70740335dd29/packages/coding-agent/src/core/sdk.ts#L248-L355) [sdk.ts L357-L385](https://github.com/earendil-works/pi/blob/8495f9d0d6407d4ec94e16a685df70740335dd29/packages/coding-agent/src/core/sdk.ts#L357-L385) [agent-harness.md L397-L425](https://github.com/earendil-works/pi/blob/8495f9d0d6407d4ec94e16a685df70740335dd29/packages/agent/docs/agent-harness.md#L397-L425)

## 1. 当前运行路径和职责分层

| 层 | 当前职责 | 主要实现证据 |
|---|---|---|
| `pi-ai` | 模型、供应商、认证、流式事件、tool calling 参数和 usage/cost 的统一抽象 | [pi-ai README L1-L5](https://github.com/earendil-works/pi/blob/8495f9d0d6407d4ec94e16a685df70740335dd29/packages/ai/README.md#L1-L5)、[L57-L88](https://github.com/earendil-works/pi/blob/8495f9d0d6407d4ec94e16a685df70740335dd29/packages/ai/README.md#L57-L88) |
| `pi-agent-core` | 内存中的 Agent 状态、LLM/tool 循环、流式生命周期事件、steering/follow-up 队列、取消 | [agent.ts L164-L228](https://github.com/earendil-works/pi/blob/8495f9d0d6407d4ec94e16a685df70740335dd29/packages/agent/src/agent.ts#L164-L228) |
| `pi-coding-agent/AgentSession` | Session 持久化、自动重试、自动/手工压缩、分支导航、模型与 thinking level、扩展桥接、系统提示词刷新 | [agent-session.ts L1-L14](https://github.com/earendil-works/pi/blob/8495f9d0d6407d4ec94e16a685df70740335dd29/packages/coding-agent/src/core/agent-session.ts#L1-L14)、[L358-L383](https://github.com/earendil-works/pi/blob/8495f9d0d6407d4ec94e16a685df70740335dd29/packages/coding-agent/src/core/agent-session.ts#L358-L383) |
| 表面接口 | 同一 `AgentSession` 被 interactive、print、RPC 共用；另有可嵌入 SDK | [agent-session.ts L1-L13](https://github.com/earendil-works/pi/blob/8495f9d0d6407d4ec94e16a685df70740335dd29/packages/coding-agent/src/core/agent-session.ts#L1-L13)、[coding-agent README L457-L487](https://github.com/earendil-works/pi/blob/8495f9d0d6407d4ec94e16a685df70740335dd29/packages/coding-agent/README.md#L457-L487) |

这意味着核心循环本身不负责磁盘 Session、coding prompt 或扩展 UI；这些应用层能力由 `AgentSession` 订阅核心事件后组合。构造函数中的注释也明确说，该订阅用于 session persistence、extensions、auto-compaction 和 retry logic。[agent-session.ts L358-L378](https://github.com/earendil-works/pi/blob/8495f9d0d6407d4ec94e16a685df70740335dd29/packages/coding-agent/src/core/agent-session.ts#L358-L378)

## 2. Agent 循环语义

### 2.1 一次运行与 Turn

`runAgentLoop()` 把新 prompt 复制进当前上下文，依次发出 `agent_start`、`turn_start`、prompt 的 `message_start/message_end`，然后进入循环。每个内层迭代执行一次模型流；模型产生 tool calls 时执行工具、生成 `toolResult` 消息，再发 `turn_end` 并进入下一次模型调用。模型响应为 `error` 或 `aborted` 时直接结束该次运行。[agent-loop.ts L94-L140](https://github.com/earendil-works/pi/blob/8495f9d0d6407d4ec94e16a685df70740335dd29/packages/agent/src/agent-loop.ts#L94-L140) [agent-loop.ts L154-L224](https://github.com/earendil-works/pi/blob/8495f9d0d6407d4ec94e16a685df70740335dd29/packages/agent/src/agent-loop.ts#L154-L224)

这里源码中的 `turn_start/turn_end` 是“**一次 LLM 响应及其工具批次**”的生命周期，而不是本地 `CONTEXT.md` 定义的、从用户消息直到最终回答持久化完成的整个业务 `Turn`。后续对比时必须先对齐这一术语差异，不能仅按同名事件比较。

模型调用边界依次执行 `transformContext(AgentMessage[])`、`convertToLlm()`，然后用当前 `systemPrompt/messages/tools` 调流式 provider；partial assistant message 在流中持续替换，最终在 `message_end` 固化。[agent-loop.ts L276-L311](https://github.com/earendil-works/pi/blob/8495f9d0d6407d4ec94e16a685df70740335dd29/packages/agent/src/agent-loop.ts#L276-L311) [agent-loop.ts L313-L370](https://github.com/earendil-works/pi/blob/8495f9d0d6407d4ec94e16a685df70740335dd29/packages/agent/src/agent-loop.ts#L313-L370)

### 2.2 Steering、follow-up 与同一 Agent 的并发

- steering 消息在当前 assistant turn 及其工具执行结束后、下一次模型调用前注入；follow-up 只在 Agent 原本准备停止时注入。[agent-loop.ts L165-L189](https://github.com/earendil-works/pi/blob/8495f9d0d6407d4ec94e16a685df70740335dd29/packages/agent/src/agent-loop.ts#L165-L189) [agent-loop.ts L258-L273](https://github.com/earendil-works/pi/blob/8495f9d0d6407d4ec94e16a685df70740335dd29/packages/agent/src/agent-loop.ts#L258-L273)
- 两种队列均支持 `one-at-a-time` 和 `all`；默认都是前者。`AgentSession` 在 UI 层同步维护队列文本，并把实际消息送入 core 队列。[agent.ts L122-L156](https://github.com/earendil-works/pi/blob/8495f9d0d6407d4ec94e16a685df70740335dd29/packages/agent/src/agent.ts#L122-L156) [agent.ts L209-L227](https://github.com/earendil-works/pi/blob/8495f9d0d6407d4ec94e16a685df70740335dd29/packages/agent/src/agent.ts#L209-L227) [agent-session.ts L1351-L1383](https://github.com/earendil-works/pi/blob/8495f9d0d6407d4ec94e16a685df70740335dd29/packages/coding-agent/src/core/agent-session.ts#L1351-L1383)
- 同一个 `Agent` 同时只能有一个 `activeRun`；忙时再次 `prompt()` 会抛错，调用方只能排队、等待或取消。因此并发工具不等于并发处理多个用户 prompt。[agent.ts L333-L374](https://github.com/earendil-works/pi/blob/8495f9d0d6407d4ec94e16a685df70740335dd29/packages/agent/src/agent.ts#L333-L374) [agent.ts L468-L490](https://github.com/earendil-works/pi/blob/8495f9d0d6407d4ec94e16a685df70740335dd29/packages/agent/src/agent.ts#L468-L490)
- core 生命周期 listener 按订阅顺序逐个 `await`；`agent_end` 后也要等 listener 完成，`waitForIdle()` 才结算。这使 `AgentSession` 的持久化和扩展处理处在运行结算路径上。[agent.ts L230-L243](https://github.com/earendil-works/pi/blob/8495f9d0d6407d4ec94e16a685df70740335dd29/packages/agent/src/agent.ts#L230-L243) [agent.ts L519-L573](https://github.com/earendil-works/pi/blob/8495f9d0d6407d4ec94e16a685df70740335dd29/packages/agent/src/agent.ts#L519-L573)

### 2.3 取消和自动延续

`abort()` 通过当前 `AbortController` 发信号；provider、工具和 bash 子进程共享该 signal。core 在运行清理时清除 streaming message 与 pending tool call 状态。[agent.ts L303-L320](https://github.com/earendil-works/pi/blob/8495f9d0d6407d4ec94e16a685df70740335dd29/packages/agent/src/agent.ts#L303-L320) [agent.ts L511-L517](https://github.com/earendil-works/pi/blob/8495f9d0d6407d4ec94e16a685df70740335dd29/packages/agent/src/agent.ts#L511-L517) [bash.ts L111-L129](https://github.com/earendil-works/pi/blob/8495f9d0d6407d4ec94e16a685df70740335dd29/packages/coding-agent/src/core/tools/bash.ts#L111-L129)

`AgentSession` 在 core 一次运行结束后，还会在外层检查可重试错误、上下文压缩和 `agent_end` 扩展新排入的消息；满足条件时调用 `agent.continue()`。所以用户看到的一次 `prompt()` 可能包含多个 core run。[agent-session.ts L1044-L1085](https://github.com/earendil-works/pi/blob/8495f9d0d6407d4ec94e16a685df70740335dd29/packages/coding-agent/src/core/agent-session.ts#L1044-L1085)

## 3. 工具系统

### 3.1 默认工具与执行策略

pi 内置的工具集合是 `read/bash/edit/write/grep/find/ls`，但默认 coding tools 只有 `read/bash/edit/write`；`grep/find/ls` 组成额外的只读工具组。SDK 支持 allowlist、denylist、禁用全部或禁用 built-in，以及注册 custom tools。[tools/index.ts L71-L94](https://github.com/earendil-works/pi/blob/8495f9d0d6407d4ec94e16a685df70740335dd29/packages/coding-agent/src/core/tools/index.ts#L71-L94) [tools/index.ts L138-L183](https://github.com/earendil-works/pi/blob/8495f9d0d6407d4ec94e16a685df70740335dd29/packages/coding-agent/src/core/tools/index.ts#L138-L183) [sdk.ts L49-L68](https://github.com/earendil-works/pi/blob/8495f9d0d6407d4ec94e16a685df70740335dd29/packages/coding-agent/src/core/sdk.ts#L49-L68)

同一 assistant message 内的多个 tool calls 默认并行。只要全局设为 `sequential`，或批次中任一工具声明 `executionMode: "sequential"`，整个批次就串行；并行模式仍按 assistant 原始顺序生成/persist tool-result messages。[agent.ts L206-L227](https://github.com/earendil-works/pi/blob/8495f9d0d6407d4ec94e16a685df70740335dd29/packages/agent/src/agent.ts#L206-L227) [agent-loop.ts L407-L425](https://github.com/earendil-works/pi/blob/8495f9d0d6407d4ec94e16a685df70740335dd29/packages/agent/src/agent-loop.ts#L407-L425) [agent-loop.ts L488-L552](https://github.com/earendil-works/pi/blob/8495f9d0d6407d4ec94e16a685df70740335dd29/packages/agent/src/agent-loop.ts#L488-L552)

工具执行前先查找工具、准备并校验 TypeBox 参数，再调用 `beforeToolCall`；hook 可返回 `block`。执行后 `afterToolCall` 可改写 content/details/usage/error/terminate。工具不存在、参数错误、hook 抛错或执行抛错都会被规范化为发给模型的错误 tool result，而不是直接让整个进程崩溃。[agent-loop.ts L599-L663](https://github.com/earendil-works/pi/blob/8495f9d0d6407d4ec94e16a685df70740335dd29/packages/agent/src/agent-loop.ts#L599-L663) [agent-loop.ts L665-L752](https://github.com/earendil-works/pi/blob/8495f9d0d6407d4ec94e16a685df70740335dd29/packages/agent/src/agent-loop.ts#L665-L752)

若模型响应因输出 token 上限截断，pi 不执行该消息中的任何 tool call，防止 partial JSON 恰好通过校验后造成意外副作用，而是为每个 call 返回错误，要求模型重发完整参数。[agent-loop.ts L373-L405](https://github.com/earendil-works/pi/blob/8495f9d0d6407d4ec94e16a685df70740335dd29/packages/agent/src/agent-loop.ts#L373-L405)

### 3.2 权限边界

pi **没有内置的文件系统、进程、网络或凭据权限系统**，默认继承启动用户/进程权限；官方建议需要强边界时用容器或 sandbox。[根 README L37-L45](https://github.com/earendil-works/pi/blob/8495f9d0d6407d4ec94e16a685df70740335dd29/README.md#L37-L45)

项目 trust 只决定是否加载项目级 settings/resources/extensions/packages，并不等价于逐次工具调用授权。命令级确认或路径保护可以由 extension 的 `tool_call` hook 自行实现；核心 `AgentSession` 只是把该 hook 接到 `beforeToolCall` 上。[coding-agent README L294-L306](https://github.com/earendil-works/pi/blob/8495f9d0d6407d4ec94e16a685df70740335dd29/packages/coding-agent/README.md#L294-L306) [agent-session.ts L443-L500](https://github.com/earendil-works/pi/blob/8495f9d0d6407d4ec94e16a685df70740335dd29/packages/coding-agent/src/core/agent-session.ts#L443-L500)

## 4. Session、持久化与恢复边界

### 4.1 JSONL 追加树

当前 coding agent 的 Session 是本地 JSONL 追加树。header 记录版本、Session id、时间、cwd、可选 parent Session；每个 entry 有 `id/parentId/timestamp`。entry 类型包括 message、model/thinking change、compaction、branch summary、extension custom/custom_message、label 和 session info。[session-manager.ts L30-L153](https://github.com/earendil-works/pi/blob/8495f9d0d6407d4ec94e16a685df70740335dd29/packages/coding-agent/src/core/session-manager.ts#L30-L153)

`SessionManager` 用 `leafId` 表示当前分支位置；追加 entry 会把它挂到当前 leaf 并推进 leaf。分支操作只是把 leaf 移到旧 entry，既有 entry 不修改、不删除。因此一份文件可以保留多条路径。[session-manager.ts L844-L867](https://github.com/earendil-works/pi/blob/8495f9d0d6407d4ec94e16a685df70740335dd29/packages/coding-agent/src/core/session-manager.ts#L844-L867) [session-manager.ts L1260-L1269](https://github.com/earendil-works/pi/blob/8495f9d0d6407d4ec94e16a685df70740335dd29/packages/coding-agent/src/core/session-manager.ts#L1260-L1269) [session-manager.ts L1350-L1405](https://github.com/earendil-works/pi/blob/8495f9d0d6407d4ec94e16a685df70740335dd29/packages/coding-agent/src/core/session-manager.ts#L1350-L1405)

`AgentSession` 在 core 发出 `message_end` 后才把 user/assistant/toolResult 追加为 `SessionMessageEntry`；custom message 使用独立 entry。也就是说，流式 token delta、provider request start、tool start/progress 本身不进入当前 Session schema。[agent-session.ts L601-L648](https://github.com/earendil-works/pi/blob/8495f9d0d6407d4ec94e16a685df70740335dd29/packages/coding-agent/src/core/agent-session.ts#L601-L648) [session-manager.ts L46-L153](https://github.com/earendil-works/pi/blob/8495f9d0d6407d4ec94e16a685df70740335dd29/packages/coding-agent/src/core/session-manager.ts#L46-L153)

持久化使用 Node 同步文件 API：首次 assistant message 出现时创建并写出此前的全部 entries，之后 `appendFileSync` 逐条追加。新 Session 在尚无 assistant response 时可以只存在于内存、文件尚未创建。[session-manager.ts L1015-L1049](https://github.com/earendil-works/pi/blob/8495f9d0d6407d4ec94e16a685df70740335dd29/packages/coding-agent/src/core/session-manager.ts#L1015-L1049)

**实现层推论：**当前 JSONL Session 是完成消息和配置/树变更的记录，不是对 in-flight provider/tool 操作的事务日志；进程在 provider stream 或工具执行中间崩溃时，源码没有足够 entry 表示并恢复该未完成操作。该判断也与下一代 `AgentHarness` 文档把 durable queue、operation/turn/provider/tool start/finish 和保守恢复策略列为未来工作一致。[agent-harness.md L352-L372](https://github.com/earendil-works/pi/blob/8495f9d0d6407d4ec94e16a685df70740335dd29/packages/agent/docs/agent-harness.md#L352-L372)

### 4.2 Context 投影与压缩

模型上下文不是整个 JSONL 文件，而是从当前 leaf 回溯得到的 active branch，再经过 compaction-aware 投影。若存在压缩 entry，只把最新 compaction summary、`firstKeptEntryId` 起的保留项以及压缩后的新增项送进模型；原始旧 entries 仍保留在文件里。[session-manager.ts L410-L469](https://github.com/earendil-works/pi/blob/8495f9d0d6407d4ec94e16a685df70740335dd29/packages/coding-agent/src/core/session-manager.ts#L410-L469)

自动压缩在 `agent_end` 后或下一条用户 prompt 发出前检查：

- overflow：移除内存上下文中的错误 assistant message（但该错误已保存在 Session 历史），生成压缩并最多 compact-and-retry 一次；
- threshold：接近 context window 时主动压缩，但不自动重试已经成功完成的回答。

证据见 [agent-session.ts L1923-L1992](https://github.com/earendil-works/pi/blob/8495f9d0d6407d4ec94e16a685df70740335dd29/packages/coding-agent/src/core/agent-session.ts#L1923-L1992) 与 [agent-session.ts L1994-L2022](https://github.com/earendil-works/pi/blob/8495f9d0d6407d4ec94e16a685df70740335dd29/packages/coding-agent/src/core/agent-session.ts#L1994-L2022)。

压缩使用同一模型生成结构化摘要，支持把前次 summary 迭代合并，并跟踪已读/已修改文件。cut point 可以落在 user 或 assistant message，但不会落在 tool result；若在带 tool calls 的 assistant message 处切分，其后的 tool results 一并保留。超大单个 turn 允许拆成“turn prefix summary + 保留 suffix”。[compaction.ts L39-L69](https://github.com/earendil-works/pi/blob/8495f9d0d6407d4ec94e16a685df70740335dd29/packages/coding-agent/src/core/compaction/compaction.ts#L39-L69) [compaction.ts L387-L460](https://github.com/earendil-works/pi/blob/8495f9d0d6407d4ec94e16a685df70740335dd29/packages/coding-agent/src/core/compaction/compaction.ts#L387-L460) [compaction.ts L687-L765](https://github.com/earendil-works/pi/blob/8495f9d0d6407d4ec94e16a685df70740335dd29/packages/coding-agent/src/core/compaction/compaction.ts#L687-L765)

压缩完成后先追加 `compaction` entry，再用 Session 投影重建 `agent.state.messages`。因此压缩改变的是 Effective Context，而非删除 Session 历史。[agent-session.ts L2125-L2140](https://github.com/earendil-works/pi/blob/8495f9d0d6407d4ec94e16a685df70740335dd29/packages/coding-agent/src/core/agent-session.ts#L2125-L2140)

## 5. 系统提示词、项目上下文与 Skills

默认 system prompt 很短：声明自己是 pi 中的 coding assistant，列出当前 tool snippets，加上简洁和文件路径等少量 guideline，并附 pi 自身文档位置。它不是一个隐藏的庞大固定 prompt；调用方可完全替换或追加。[system-prompt.ts L8-L25](https://github.com/earendil-works/pi/blob/8495f9d0d6407d4ec94e16a685df70740335dd29/packages/coding-agent/src/core/system-prompt.ts#L8-L25) [system-prompt.ts L79-L138](https://github.com/earendil-works/pi/blob/8495f9d0d6407d4ec94e16a685df70740335dd29/packages/coding-agent/src/core/system-prompt.ts#L79-L138)

资源加载器会从全局 agent dir，以及 cwd 向文件系统根逐级查找每层的 `AGENTS.md` 或 `CLAUDE.md`，按祖先到当前目录顺序拼接；随后作为带路径的 `<project_instructions>` 注入 system prompt。[resource-loader.ts L67-L119](https://github.com/earendil-works/pi/blob/8495f9d0d6407d4ec94e16a685df70740335dd29/packages/coding-agent/src/core/resource-loader.ts#L67-L119) [system-prompt.ts L144-L159](https://github.com/earendil-works/pi/blob/8495f9d0d6407d4ec94e16a685df70740335dd29/packages/coding-agent/src/core/system-prompt.ts#L144-L159)

Skills 遵循 Agent Skills 规范并采用渐进披露：启动时只扫描名称和描述并放进 system prompt，匹配任务后模型用 `read` 读取完整 `SKILL.md`；也可通过 `/skill:name` 强制调用。[skills.md L64-L82](https://github.com/earendil-works/pi/blob/8495f9d0d6407d4ec94e16a685df70740335dd29/packages/coding-agent/docs/skills.md#L64-L82)

在每个工具循环的 save point，`AgentSession` 会为下一次模型调用刷新 system prompt、tools、model 和 thinking level；每次用户 prompt 前，extension 的 `before_agent_start` 还可注入 custom messages 或临时替换 system prompt。[agent-session.ts L503-L523](https://github.com/earendil-works/pi/blob/8495f9d0d6407d4ec94e16a685df70740335dd29/packages/coding-agent/src/core/agent-session.ts#L503-L523) [agent-session.ts L1201-L1236](https://github.com/earendil-works/pi/blob/8495f9d0d6407d4ec94e16a685df70740335dd29/packages/coding-agent/src/core/agent-session.ts#L1201-L1236)

## 6. 扩展哲学与内建能力边界

扩展是由 `jiti` 直接加载的 TypeScript 模块，可注册 tools、commands、shortcuts、flags、事件 handler 和 UI。它们在宿主 Node 进程里运行，拥有完整系统权限；不是隔离的插件进程。[extensions.md L109-L120](https://github.com/earendil-works/pi/blob/8495f9d0d6407d4ec94e16a685df70740335dd29/packages/coding-agent/docs/extensions.md#L109-L120) [extensions.md L139-L179](https://github.com/earendil-works/pi/blob/8495f9d0d6407d4ec94e16a685df70740335dd29/packages/coding-agent/docs/extensions.md#L139-L179)

官方明确把核心定位为“aggressively extensible but minimal”。以下能力**不是内建核心功能**：MCP、sub-agents、permission popups、plan mode、内建 to-dos、background bash；官方建议用 CLI/tmux、extensions 或第三方 pi package 自行组合。[coding-agent README L491-L505](https://github.com/earendil-works/pi/blob/8495f9d0d6407d4ec94e16a685df70740335dd29/packages/coding-agent/README.md#L491-L505)

因此，“pi 能否支持某能力”要分成两问：core/官方 CLI 是否内建，以及 extension/package 是否能实现。README 确实列举了扩展可实现 sub-agents、plan mode、custom compaction、permission gates、sandbox、MCP 等，但这不代表这些能力属于当前 core 默认语义。[coding-agent README L366-L396](https://github.com/earendil-works/pi/blob/8495f9d0d6407d4ec94e16a685df70740335dd29/packages/coding-agent/README.md#L366-L396)

## 7. 模型与传输抽象

`pi-ai` 不是 Anthropic 专用适配层。固定基线列出 OpenAI、Anthropic、Google/Vertex、Mistral、Bedrock、OpenRouter、GitHub Copilot、OpenAI-compatible API 等多种 provider，且库只纳入支持 tool calling 的模型。[pi-ai README L1-L5](https://github.com/earendil-works/pi/blob/8495f9d0d6407d4ec94e16a685df70740335dd29/packages/ai/README.md#L1-L5) [pi-ai README L57-L88](https://github.com/earendil-works/pi/blob/8495f9d0d6407d4ec94e16a685df70740335dd29/packages/ai/README.md#L57-L88)

Session 可在中途切换 provider/model 和 thinking level，变化作为树 entry 持久化；恢复时 SDK 从 active branch 还原模型与 thinking level，找不到原模型时回退并给出提示。[sdk.ts L182-L237](https://github.com/earendil-works/pi/blob/8495f9d0d6407d4ec94e16a685df70740335dd29/packages/coding-agent/src/core/sdk.ts#L182-L237) [session-manager.ts L58-L80](https://github.com/earendil-works/pi/blob/8495f9d0d6407d4ec94e16a685df70740335dd29/packages/coding-agent/src/core/session-manager.ts#L58-L80)

## 8. 下一代 `AgentHarness`：不要与当前 CLI 混淆

新 `AgentHarness` 的目标是把 session persistence、runtime config、resource resolution、operation locking 和 extension mutation semantics 收进通用编排层，并用明确的 `idle/turn/compaction/branch_summary/retry` phase、turn snapshot 和 save point 管理状态。[agent-harness.md L1-L20](https://github.com/earendil-works/pi/blob/8495f9d0d6407d4ec94e16a685df70740335dd29/packages/agent/docs/agent-harness.md#L1-L20) [agent-harness.md L34-L76](https://github.com/earendil-works/pi/blob/8495f9d0d6407d4ec94e16a685df70740335dd29/packages/agent/docs/agent-harness.md#L34-L76) [agent-harness.md L94-L152](https://github.com/earendil-works/pi/blob/8495f9d0d6407d4ec94e16a685df70740335dd29/packages/agent/docs/agent-harness.md#L94-L152)

但在该 commit，它仍有实质未完成项：auto-compaction/retry decision point 未实现，通用 hook/event 机制未实现，半持久恢复仅有设计，生命周期 hardening 未做，coding-agent migration 仍为 planned。[agent-harness.md L210-L218](https://github.com/earendil-works/pi/blob/8495f9d0d6407d4ec94e16a685df70740335dd29/packages/agent/docs/agent-harness.md#L210-L218) [agent-harness.md L291-L372](https://github.com/earendil-works/pi/blob/8495f9d0d6407d4ec94e16a685df70740335dd29/packages/agent/docs/agent-harness.md#L291-L372) [agent-harness.md L397-L411](https://github.com/earendil-works/pi/blob/8495f9d0d6407d4ec94e16a685df70740335dd29/packages/agent/docs/agent-harness.md#L397-L411)

后续比较 Claude Code 时，应以第 1～7 节的当前 `AgentSession/Agent` 路径为主；第 8 节只能作为 pi 的演进方向，不能当成已交付行为。

## 9. Claude Code 本地参考实现事实

### 9.1 证据边界

本地参考代码位于 `参考/claudecode_src/`。该目录被 `.gitignore` 排除，快照内也没有可用于确认官方发行版或上游 commit 的包清单，因此本文不把它冒充成“Claude Code 某个公开版本”。以下 Claude Code 结论都引用**本地文件与行号**；它们只描述这个快照中实际可见的实现。

### 9.2 主循环比 pi core 承担更多生产策略

Claude Code 的 `query()` 是 async generator，内部 `while (true)` 持有跨迭代状态；每次迭代先从 compact boundary 后取消息，依次应用 tool-result replacement、snip/microcompact/context collapse/auto-compact，再发起模型流。只要流中出现 `tool_use` block 就设置 `needsFollowUp`，执行工具后把 assistant 与 tool results 拼回消息数组，继续下一次模型调用；没有工具时才进入 stop hooks 并结束。见 `参考/claudecode_src/query.ts:247-318`、`:360-401`、`:433-640`、`:660-682`、`:1296-1640`、`:1643-1692`、`:2028-2087`。

这和 pi 的基本 LLM → tools → LLM 结构相同，但 Claude Code 的 query engine 同时内建模型 fallback、prompt-too-long 恢复、max-output-token 延续、stop hook 阻塞重试、token budget continuation、动态 MCP tool refresh 和大量 feature-gated context 策略；pi 把相当一部分应用策略留在 `AgentSession` 或 extension 层。

### 9.3 工具可以在模型仍流式输出时启动

这是最容易被忽略的实质差异：Claude Code 在模型流中一收到 assistant message 内的 `tool_use` block，就调用 `StreamingToolExecutor.addTool()`，并在后续 stream event 到来时持续提取已完成结果；流结束后才 drain 剩余结果。模型 fallback 时还会丢弃旧 executor，防止旧 `tool_use_id` 的孤儿结果泄漏。见 `参考/claudecode_src/query.ts:999-1037`、`:1075-1107`、`:1227-1253`、`:1643-1692`。

pi 则必须先等待 `streamAssistantResponse()` 返回完整 assistant message，随后才筛出全部 tool calls 并批量执行；默认批内并行，但它不是“边生成边执行”。[pi `agent-loop.ts` L192-L216](https://github.com/earendil-works/pi/blob/8495f9d0d6407d4ec94e16a685df70740335dd29/packages/agent/src/agent-loop.ts#L192-L216) [L276-L370](https://github.com/earendil-works/pi/blob/8495f9d0d6407d4ec94e16a685df70740335dd29/packages/agent/src/agent-loop.ts#L276-L370)

### 9.4 权限、工具、MCP 和 Agent 是内建子系统

Claude Code 的工具池不只是 `Read/Bash/Edit/Write`：本地快照直接装配 Agent、TaskOutput、WebFetch/WebSearch、Todo、AskUserQuestion、Skill、Plan、Task 管理、MCP resources 和 ToolSearch 等工具；内建与 MCP 工具合并时先按 deny rules 过滤、按名称去重，并为 prompt cache 稳定性分区排序。见 `参考/claudecode_src/tools.ts:193-250`、`:253-327`、`:329-367`。

权限不是 extension 示例，而是运行时主路径：`canUseTool` 先得到 `allow/deny/ask` 决策，再根据 coordinator、swarm worker、classifier、interactive/bridge/channel 等路径解析；权限规则支持 allow/deny/ask、tool 内容匹配、`dontAsk`、`auto`、`acceptEdits`、`bypassPermissions` 等模式，并可由 `PermissionRequest` hook 决策。见 `参考/claudecode_src/hooks/useCanUseTool.tsx:27-180`、`参考/claudecode_src/utils/permissions/permissions.ts:473-945`、`:1062-1304`。

`AgentTool` 还原生支持同步/后台 sub-agent、fork worker、team teammate、remote/worktree isolation、agent 类型过滤与独立 transcript。子 agent 复用同一 `query()`，可继承或裁剪父上下文，并拥有 agent-specific tools、MCP 和权限状态。见 `参考/claudecode_src/tools/AgentTool/AgentTool.tsx:110-191`、`:245-360`，以及 `参考/claudecode_src/tools/AgentTool/runAgent.ts:248-378`、`:655-754`。

### 9.5 Hook 和扩展模型不同

Claude Code 暴露结构化生命周期 hooks，包括 `PreToolUse`、`PostToolUse`、`PermissionRequest`、`SessionStart`、`SubagentStart`、`Stop/SubagentStop`、`PreCompact/PostCompact` 和 `SessionEnd`；hook 可补充上下文、改写 MCP tool output、改写 tool input，或对权限作 allow/deny。见 `参考/claudecode_src/types/hooks.ts:65-163`、`参考/claudecode_src/utils/hooks.ts:3594-3683`、`:3961-4131`。

pi 的 extension API 更像一个进程内应用框架：可信 TypeScript 可以注册/替换 tool、provider、command、UI，也可以拦截 context 和 provider payload。它更自由、更适合做产品变体；代价是扩展与宿主同权限，且 MCP、sub-agent、plan 和 permission UX 没有统一的 core 语义。Claude Code 则以较强的内建语义和配置化 hook/plugin/skill seam 为主。

### 9.6 两者都有追加式 transcript 与分支，不能说 Claude Code“没有树”

Claude Code 的本地 transcript 也是 JSONL：每条 transcript message 带 `parentUuid`，compact boundary 会断开物理 parent 并保留 `logicalParentUuid`；写入通过按文件排序的 queue 批量 `appendFile`。见 `参考/claudecode_src/utils/sessionStorage.ts:606-675`、`:993-1082`。源码还明确处理 rewind/重试留下的 dead fork branches，并说明一个 Session 文件可能有多个 leaf；`/branch` 则复制当前 conversation chain 到新 Session。见 `参考/claudecode_src/utils/sessionStorage.ts:3227-3237`、`参考/claudecode_src/commands/branch/branch.ts:58-159`。

因此准确差异是：pi 把 `id/parentId + leafId` 公开为一等 Session tree API，并提供 `/tree` 导航与 `branch_summary`；Claude Code 快照也保留 parent chain 和分支，但产品操作同时包含原 Session 内 rewind/dead branches、文件快照 rewind，以及创建新 Session 的 `/branch`，组织方式不同，不是线性对树形的二分。

### 9.7 Claude Code 的持久化修复更复杂，但也不是本仓库 ADR 所要求的事务日志

`QueryEngine` 对 assistant/user/compact boundary 记录 transcript；assistant 采用保序队列的 fire-and-forget 写入，compact boundary 前会先 flush preserved tail，避免恢复时 boundary 指向未落盘消息。见 `参考/claudecode_src/QueryEngine.ts:675-732`。模型 fallback、异常或取消时，query 会补 synthetic missing tool results 或 tombstone，避免 `tool_use/tool_result` 失配。见 `参考/claudecode_src/query.ts:863-897`、`:1083-1107`、`:1182-1205`、`:1227-1253`。

这些机制明显比 pi 当前“`message_end` 后追加完成消息”的恢复修补多，但从可见 schema 仍不能推出它在外部副作用工具执行前后拥有持久化 begin/commit、幂等键或 exactly-once 恢复。换言之，两者都不能直接替代本仓库 ADR-0001/0005 所描述的 Durable Session History 与 Replay-safe Tool 协议。

### 9.8 Context 管理策略更深，但核心原则相似

Claude Code 在下一次模型调用前做主动 auto-compact，也能在真实 413 后做 reactive compact；除此之外还有 microcompact、snip、context collapse、max-output-token continuation、压缩失败断路器以及压缩前后 hooks。auto-compact 阈值、连续失败上限和 session-memory 优先路径见 `参考/claudecode_src/services/compact/autoCompact.ts:28-93`、`:147-239`、`:241-349`；查询中的主动和响应式恢复见 `参考/claudecode_src/query.ts:433-640`、`:1296-1444`。

压缩会生成 boundary/summary、保留近期片段，并重新注入 file references、skills、plan/context attachments 和 hook results；JSONL 中的旧消息仍用于完整 transcript/恢复逻辑，而 query 的内存视图在 boundary 后释放旧前缀。见 `参考/claudecode_src/services/compact/compact.ts:122-130`、`:634-746`，以及 `参考/claudecode_src/QueryEngine.ts:917-940`。

两者的共同原则是“压缩 Effective Context，不静默删除原始 Session 历史”。区别在于 Claude Code 已把更多超限类型和缓存/工具一致性边界产品化；pi 的实现更容易读懂和替换，且 extension 可以完全定制 summary。

### 9.9 Provider 抽象范围

Claude Code 参考实现通过 Anthropic SDK 访问 first-party、Bedrock、Vertex 和 Foundry；这些是不同托管入口，但仍围绕 Claude/Anthropic Messages 语义。见 `参考/claudecode_src/services/api/client.ts:88-100`、`:153-219`、`:221-315`。pi-ai 则统一 Claude、OpenAI、Google、Mistral、OpenRouter、Copilot 和 OpenAI-compatible 等不同模型家族，因此 provider/model 可替换性是 pi 的核心优势。

## 10. 最终差异矩阵

| 维度 | pi 0.80.10 | 本地 Claude Code 参考实现 | 影响 |
|---|---|---|---|
| 设计中心 | 小 core + 强进程内 extension；当前生产路径为 `AgentSession → Agent → runAgentLoop` | 集成式 coding-agent runtime，query 内建大量产品策略 | pi 适合二次开发；Claude Code 默认能力与行为一致性更强 |
| 新通用编排层 | `AgentHarness` 已有 phase/snapshot/save-point 基础，但尚未迁移 coding-agent | 可见 `query/QueryEngine` 已是成熟生产主路径 | 不能拿 AgentHarness 的规划项与 Claude Code 已交付能力直接比较 |
| 模型循环 | 完整 assistant stream 结束后执行工具 | feature gate 开启时，stream 中收到 tool block 即可启动工具 | Claude Code 可隐藏部分工具延迟，但需要更复杂的 fallback/孤儿结果处理 |
| 多工具并发 | 默认批内并行；任一 sequential tool 可使整批串行 | streaming executor + `runTools`，带 completed/remaining/discard 生命周期 | pi 策略更简单显式；Claude Code 优化更激进 |
| 默认工具面 | 默认 `read/bash/edit/write`；另有 `grep/find/ls` | 文件、shell、web、skill、plan、todo/task、Agent、MCP、ToolSearch 等 | Claude Code 开箱能力远多于 pi |
| MCP | 不内建，交给 extension/package | 原生 MCP clients/tools/resources、动态刷新和权限过滤 | 需要标准 MCP 互操作时，pi 要额外选择实现 |
| 子代理/后台任务 | 不内建；官方建议 extension、tmux 或 package | `AgentTool` 原生支持 sync/background/fork/team/remote/worktree | Claude Code 有统一生命周期、权限和 transcript；pi 允许自选语义但缺默认协议 |
| Plan/Todo | 不内建 | 内建 plan mode、Todo/Task 工具和专用权限/UI | pi 更小；Claude Code 工作流更统一 |
| 权限 | 无内建逐次权限或 sandbox；project trust 只是资源加载门 | allow/deny/ask rules、多 permission modes、交互/自动分类/hook | 这是两者最大的安全产品差异；pi 必须靠 OS sandbox 或自建 extension |
| 扩展 | 同进程可信 TypeScript，可注册 tool/provider/UI、改 context/payload | plugin/skill/agent/MCP + 结构化 hooks | pi seam 更宽；Claude Code seam 更受约束但核心语义稳定 |
| Session 结构 | 单 JSONL 内一等 `id/parentId` 树和 leaf，公开 `/tree`/branch summary | JSONL `parentUuid` chain，同文件可有 rewind 分支；也支持新 Session `/branch` | 两者都不是纯线性日志，分支操作和公开 API 不同 |
| 持久化时点 | 完成消息在 `message_end` 后同步追加 | transcript queue 保序追加；assistant 可 fire-and-forget，boundary 前补 flush | 两者都不等同于本仓库要求的外部副作用事务日志 |
| 压缩 | structured summary + recent tail；threshold/overflow，overflow 最多 compact-and-retry 一次 | auto/reactive/micro/snip/collapse 等多层策略，含 hooks 和恢复断路器 | Claude Code 对极端长 Session 更成熟；pi 更透明、可替换 |
| Provider | 多模型家族统一 API，Session 中可切 provider/model | Anthropic/Claude 模型语义，支持 first-party/Bedrock/Vertex/Foundry | 多模型产品优先选 pi seam；Claude 优化优先选 Claude Code seam |
| 同一会话并发 | 一个 `Agent` 一个 active run；steering/follow-up 在安全点排队 | 顶层 query 串行递进，同时可运行后台 sub-agent/task | pi 默认更接近单 lane；Claude Code 的 agent/task 并发需单独建模 |

## 11. 对 RS_agent 的直接启示与 ADR 对照

### 11.1 可借鉴 pi 的地方

1. **保持模型适配层与 Agent 编排层分离。** `pi-ai / Agent / AgentSession` 的分层非常清楚，适合本项目继续隔离 Spring AI provider adapter、Agent loop 与 Durable Session History。
2. **把模型可见上下文明确做成 Session 历史的投影。** pi 的 active branch + compaction entry，Claude Code 的 compact boundary，都支持本项目 `Durable Session History ≠ Effective Context` 的术语与 ADR-0001/0004。
3. **采用 turn snapshot/save point 思路，但不要把未完成的 AgentHarness 当参考实现。** 它与 ADR-0002/0003 的“运行时重新注入、只在 Safe Compaction Boundary 切换”方向一致；真正迁移前仍要自行补完生命周期证明。
4. **工具执行策略显式化。** pi 的 parallel/sequential 声明简单；Claude Code 的 streaming execution 展示了进一步降延迟的方向，但在第一版 Replay-safe Tool 和持久化协议尚未稳定前，不值得先引入孤儿结果/fallback 复杂度。

### 11.2 不应直接照搬的地方

- **ADR-0001（Scylla 权威、MySQL 投影、Redis 热状态）：**pi 与 Claude Code 的本地 JSONL 都是单机产品 transcript，不具备本项目实例无关 Session 的权威分工，不能替代既定存储设计。
- **ADR-0002（checkpoint 不固化运行时注入）：**两者都在模型调用前重建 system/tool/resource 输入，方向一致；本项目仍应只在 Trace 中记录某次实际注入版本，而不把它固化进 Context Checkpoint。
- **ADR-0003（Safe Compaction Boundary）：**Claude Code 的主动压缩位于下一模型调用前，pi 当前多在 `agent_end`/新 prompt 前，二者都给了安全点示例；本项目还允许 Turn 中间 `TOOL_RESULT` 后压缩，必须以事件已持久化且无未完成工具为硬条件，不能照搬 UI 生命周期事件名。
- **ADR-0004（可审计有损裁剪）：**两者都保留原始 transcript，但 Claude Code 有更多 last-resort truncation/response recovery。RS_agent 必须继续持久化裁剪范围和原因，不能只留下 summary/boundary。
- **ADR-0005（第一版只执行 Replay-safe Tool）：**pi 默认提供 Bash/Edit/Write 且无内建权限；Claude Code 也执行写文件、shell、网络和多代理工具。两者的产品工具面都比本项目第一版授权范围大，不能反推“已有 agent 都这样做所以可安全重放”。
- **ADR-0006（Session 内串行）：**pi 的单 `activeRun` 是很好的进程内 guard，但不是跨实例 Session Execution Lane；Claude Code 的后台 sub-agent/task 也不等于允许同一顶层 Session 的用户 Turn 并发提交。
- **ADR-0007（一个活跃 Agent 实例）：**pi 默认无 sub-agent 更接近第一版约束；Claude Code 的 AgentTool/teams/remote 路径明确超出当前范围。若以后借鉴，必须先完成 fencing 和持久化追加协议，而不是先复制 AgentTool。
- **ADR-0008（Java virtual thread）：**两份 TypeScript 实现依赖 Node async I/O，不能作为虚拟线程选择的正反证；本 ADR 应继续依据 Java 运行时实测。

## 12. 结论

一句话概括：**pi 是“可嵌入、多模型、把工作流留给可信扩展的最小 agent harness”；本地 Claude Code 是“围绕 Claude 深度优化、把权限/MCP/子代理/计划/长上下文恢复内建进生产 query engine 的完整 coding-agent 产品”。**

如果目的是为 RS_agent 选架构参考，建议组合而不是二选一：采用 pi 的清晰分层、模型抽象和 Session→Context 投影；采用 Claude Code 对 tool pairing、权限决策、压缩失败与 stream fallback 的防御性设计；但继续以本仓库 ADR 的持久事件、Replay-safe Tool、Session Execution Lane 和单活约束作为正确性底线。
