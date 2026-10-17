# Pi Agent 核心实现研究（v0.80.10）

更新时间：2026-07-21  
研究对象：本机安装的 `@earendil-works/pi-coding-agent@0.80.10` 及其依赖 `pi-agent-core@0.80.10`、`pi-ai@0.80.10`  
官方源码基线：tag `v0.80.10`，commit [`8dc78834cde4e329284cf505f9e3f99763df5529`](https://github.com/earendil-works/pi/commit/8dc78834cde4e329284cf505f9e3f99763df5529)

## 结论先行

Pi 不是“靠一段很长的提示词模拟 Agent”，而是一个分层的 TypeScript/Node.js 运行时：

```text
pi CLI / TUI / print / RPC
        │
        ▼
pi-coding-agent: AgentSession
  提示词、项目资源、工具注册、Session、压缩、重试、扩展
        │
        ▼
pi-agent-core: Agent + runAgentLoop
  内存状态、消息事件、LLM→工具→LLM 循环、队列、取消
        │
        ▼
pi-ai: Models / Provider / API adapter
  认证、模型目录、统一流式协议、OpenAI/Anthropic/Google 等适配
```

官方根 README 对三层的定义就是“交互式 coding agent CLI / 带工具调用和状态管理的 Agent runtime / 多供应商统一 LLM API”。见 [README L13-L32](https://github.com/earendil-works/pi/blob/8dc78834cde4e329284cf505f9e3f99763df5529/README.md#L13-L32)。

最容易误读的一点是：**当前 v0.80.10 的 CLI 生产路径仍然是 `AgentSession → Agent → runAgentLoop`。** `packages/agent/src/harness/` 下虽然已经有新的 `AgentHarness`，但官方迁移文档仍把 coding-agent migration 标为 `Planned`，自动压缩与自动重试决策也尚未移入它。见 [agent-harness.md L218-L218](https://github.com/earendil-works/pi/blob/8dc78834cde4e329284cf505f9e3f99763df5529/packages/agent/docs/agent-harness.md#L218-L218) 和 [L397-L425](https://github.com/earendil-works/pi/blob/8dc78834cde4e329284cf505f9e3f99763df5529/packages/agent/docs/agent-harness.md#L397-L425)。`createAgentSession()` 实际仍实例化 `Agent`，再交给 `AgentSession`：[sdk.ts L289-L385](https://github.com/earendil-works/pi/blob/8dc78834cde4e329284cf505f9e3f99763df5529/packages/coding-agent/src/core/sdk.ts#L289-L385)。

## 研究方法与本机校验

本报告只使用一手来源：

- 本机 npm 安装包：`C:\Users\luo\AppData\Roaming\npm\node_modules\@earendil-works\pi-coding-agent`。
- 本机 `dist/*.js.map` 中包含完整 `sourcesContent`，可还原发布包对应的 TypeScript 源码；例如 `dist/main.js.map` 指向 `../src/main.ts`。
- 对 CLI、SDK、Agent、主循环、模型与工具等 10 个关键文件，将 source map 的 `sourcesContent` 与官方 `v0.80.10` 源文件逐一做 SHA-256 比对，结果全部一致。
- 官方 GitHub tag `v0.80.10`。本机三个包的 `package.json` 均为 `0.80.10`，且 coding-agent 的依赖明确指向同版本 `pi-agent-core` 与 `pi-ai`：[package.json L1-L10](https://github.com/earendil-works/pi/blob/8dc78834cde4e329284cf505f9e3f99763df5529/packages/coding-agent/package.json#L1-L10)、[L41-L44](https://github.com/earendil-works/pi/blob/8dc78834cde4e329284cf505f9e3f99763df5529/packages/coding-agent/package.json#L41-L44)。

下文链接全部固定到该 tag 对应 commit，避免 `main` 后续变化造成行号漂移。

## 1. CLI 入口如何启动

### 1.1 npm 命令入口

`@earendil-works/pi-coding-agent/package.json` 把命令 `pi` 映射为 `dist/cli.js`：[package.json L9-L11](https://github.com/earendil-works/pi/blob/8dc78834cde4e329284cf505f9e3f99763df5529/packages/coding-agent/package.json#L9-L11)。源码入口 `src/cli.ts` 做的事情很少：设置进程名和 `PI_CODING_AGENT=true`，抑制 warning，先配置全局 HTTP dispatcher，然后调用 `main(process.argv.slice(2))`：[cli.ts L1-L20](https://github.com/earendil-works/pi/blob/8dc78834cde4e329284cf505f9e3f99763df5529/packages/coding-agent/src/cli.ts#L1-L20)。

### 1.2 `main()` 负责装配，不负责 Agent 算法

`main()` 的职责是：

1. 解析参数、环境变量、stdin 和特殊命令；根据 TTY/参数决定 interactive、print、JSON 或 RPC 模式：[main.ts L472-L540](https://github.com/earendil-works/pi/blob/8dc78834cde4e329284cf505f9e3f99763df5529/packages/coding-agent/src/main.ts#L472-L540)。
2. 创建或打开 `SessionManager`，处理 `--session`、`--continue`、`--resume`、`--fork` 等入口。
3. 为目标 cwd 创建 `SettingsManager`、`ModelRuntime` 和 `DefaultResourceLoader`，并处理项目 trust；随后调用 `createAgentSessionFromServices()`：[main.ts L613-L743](https://github.com/earendil-works/pi/blob/8dc78834cde4e329284cf505f9e3f99763df5529/packages/coding-agent/src/main.ts#L613-L743)。
4. 最后把同一个 `AgentSessionRuntime` 交给 RPC、TUI 或 print mode：[main.ts L809-L855](https://github.com/earendil-works/pi/blob/8dc78834cde4e329284cf505f9e3f99763df5529/packages/coding-agent/src/main.ts#L809-L855)。

因此 CLI、TUI、RPC 不是三套 Agent；它们是同一个 session/runtime 上的不同交互外壳。

## 2. Agent 主循环、消息流和 LLM stream

### 2.1 `Agent` 是有状态外壳

`pi-agent-core` 的 `Agent` 保存 system prompt、模型、thinking level、工具和消息；同时持有 steering/follow-up 队列、stream function、工具前后置 hook 和一个活动 `AbortController`。默认 stream function 是 `pi-ai` 的 `streamSimple`，默认多工具执行模式是 `parallel`：[agent.ts L171-L229](https://github.com/earendil-works/pi/blob/8dc78834cde4e329284cf505f9e3f99763df5529/packages/agent/src/agent.ts#L171-L229)。

一次 `prompt()` 只允许一个活动 run；忙时再次调用会抛错，调用者必须 steer、follow-up 或等待。`Agent` 为本次 run 创建 context 快照和 loop config，然后调用 `runAgentLoop()`；`continue()` 则调用 `runAgentLoopContinue()`：[agent.ts L334-L430](https://github.com/earendil-works/pi/blob/8dc78834cde4e329284cf505f9e3f99763df5529/packages/agent/src/agent.ts#L334-L430)。

### 2.2 `runAgentLoop()` 是真正的 LLM→工具→LLM 循环

新 prompt 会先进入当前 context，并发出：

```text
agent_start
turn_start
message_start(user)
message_end(user)
```

然后进入双层循环：[agent-loop.ts L95-L143](https://github.com/earendil-works/pi/blob/8dc78834cde4e329284cf505f9e3f99763df5529/packages/agent/src/agent-loop.ts#L95-L143)。内层每次完成：

1. 注入待处理 steering 消息；
2. 调用一次模型流；
3. 若 assistant 包含 tool calls，执行整批工具并追加 tool results；
4. 发出 `turn_end`；
5. 刷新下一 turn 的 context/model/thinking；
6. 再检查 steering。

没有工具和 steering 后，外层才检查 follow-up；仍为空则发 `agent_end`。完整控制流见 [agent-loop.ts L155-L275](https://github.com/earendil-works/pi/blob/8dc78834cde4e329284cf505f9e3f99763df5529/packages/agent/src/agent-loop.ts#L155-L275)。这里的一个 `turn` 是“一次模型响应 + 它的工具批次”，所以一次用户 prompt 可能产生多个 turn。

### 2.3 消息只在 LLM 边界转换

core 内部一直使用可扩展的 `AgentMessage[]`。每次请求模型前依次执行：

```text
AgentMessage[]
  → transformContext()       // 扩展可修剪/注入
  → convertToLlm()           // 过滤 UI-only/custom 消息
  → { systemPrompt, messages, tools }
  → streamFn(model, context, options)
```

见 [agent-loop.ts L281-L314](https://github.com/earendil-works/pi/blob/8dc78834cde4e329284cf505f9e3f99763df5529/packages/agent/src/agent-loop.ts#L281-L314)。模型流事件被规整为 `start`、text/thinking/toolcall 的 start/delta/end、`done/error`；partial assistant message 会在 context 尾部不断替换，最终以 `message_end` 固化：[agent-loop.ts L316-L373](https://github.com/earendil-works/pi/blob/8dc78834cde4e329284cf505f9e3f99763df5529/packages/agent/src/agent-loop.ts#L316-L373)。

`Agent.processEvents()` 先更新内存状态，再按订阅顺序逐个 `await` listener。因此 `AgentSession` 的持久化和扩展 hook 是 run settlement 的一部分；甚至 `agent_end` listener 没结束时，`waitForIdle()` 也不会完成：[agent.ts L519-L573](https://github.com/earendil-works/pi/blob/8dc78834cde4e329284cf505f9e3f99763df5529/packages/agent/src/agent.ts#L519-L573)。

### 2.4 `pi-ai` 怎样接住 stream

coding-agent 给 `Agent` 注入的 `streamFn` 最终调用 `ModelRuntime.streamSimple()`，同时加入超时、provider 重试参数、归因 header，以及扩展的 provider request/header/response hooks：[sdk.ts L297-L355](https://github.com/earendil-works/pi/blob/8dc78834cde4e329284cf505f9e3f99763df5529/packages/coding-agent/src/core/sdk.ts#L297-L355)。

`pi-ai` 的 `Models` 层负责找到 model 所属 provider、解析认证、合并 base URL/header/env，再把请求分派给 provider 的 `streamSimple()`：[models.ts L455-L517](https://github.com/earendil-works/pi/blob/8dc78834cde4e329284cf505f9e3f99763df5529/packages/ai/src/models.ts#L455-L517)。provider 再按 `model.api` 选择具体 API adapter；缺少对应实现时返回流式错误，而不是在装配阶段硬编码某一家 SDK：[models.ts L550-L622](https://github.com/earendil-works/pi/blob/8dc78834cde4e329284cf505f9e3f99763df5529/packages/ai/src/models.ts#L550-L622)。

例如你当前使用的 `openai-completions` 最终调用 OpenAI SDK 的 `chat.completions.create(...).withResponse()`，并把同一个 `AbortSignal` 传给 SDK 请求：[openai-completions.ts L181-L227](https://github.com/earendil-works/pi/blob/8dc78834cde4e329284cf505f9e3f99763df5529/packages/ai/src/api/openai-completions.ts#L181-L227)。

## 3. 系统提示词及 AGENTS.md / CLAUDE.md 装载

### 3.1 默认提示词很短，核心能力不靠“魔法长 prompt”

默认提示词主体只是：你是运行在 pi 中的 coding assistant；列出当前工具及简短说明；要求简洁、清晰展示路径；附上 Pi 自身文档位置。具体模板在 [system-prompt.ts L79-L138](https://github.com/earendil-works/pi/blob/8dc78834cde4e329284cf505f9e3f99763df5529/packages/coding-agent/src/core/system-prompt.ts#L79-L138)。

提示词是动态构造的：活动工具的 `promptSnippet` 和 `promptGuidelines` 会加入模板；工具切换后重新生成。`AgentSession` 从 resource loader 取自定义 system prompt、追加 prompt、skills 和 context files，再调用 `buildSystemPrompt()`：[agent-session.ts L1009-L1042](https://github.com/earendil-works/pi/blob/8dc78834cde4e329284cf505f9e3f99763df5529/packages/coding-agent/src/core/agent-session.ts#L1009-L1042)。

覆盖顺序是：

1. 默认 prompt，或 `.pi/SYSTEM.md` / `~/.pi/agent/SYSTEM.md` 完全替换默认；
2. `.pi/APPEND_SYSTEM.md` / 全局同名文件追加；
3. `<project_context>` 中加入项目指令文件；
4. 有 `read` 工具时加入 skills 索引；
5. 加当前 cwd。

自定义 `SYSTEM.md` 只替换默认主体，项目 context、skills 与 cwd 仍会追加。见 [system-prompt.ts L41-L71](https://github.com/earendil-works/pi/blob/8dc78834cde4e329284cf505f9e3f99763df5529/packages/coding-agent/src/core/system-prompt.ts#L41-L71) 和 [L140-L161](https://github.com/earendil-works/pi/blob/8dc78834cde4e329284cf505f9e3f99763df5529/packages/coding-agent/src/core/system-prompt.ts#L140-L161)。

### 3.2 AGENTS.md 与 CLAUDE.md 的精确规则

每个目录只取第一个匹配文件，候选优先级是：

```text
AGENTS.md → AGENTS.MD → CLAUDE.md → CLAUDE.MD
```

见 [resource-loader.ts L67-L83](https://github.com/earendil-works/pi/blob/8dc78834cde4e329284cf505f9e3f99763df5529/packages/coding-agent/src/core/resource-loader.ts#L67-L83)。这意味着**同一目录若同时存在 `AGENTS.md` 和 `CLAUDE.md`，Pi 只自动注入 `AGENTS.md`**；若 `AGENTS.md` 要求再读 `CLAUDE.md`，需要模型随后用 `read` 工具执行，而不是 loader 同时自动装入。

搜索范围与顺序是：

1. 先找全局 agentDir（默认 `~/.pi/agent`）中的一份；
2. 再从 cwd 一直向文件系统根目录查找；
3. 祖先目录结果用 `unshift` 排成“根 → cwd”的顺序；
4. 全局文件排最前，并对同一路径去重。

见 [resource-loader.ts L85-L119](https://github.com/earendil-works/pi/blob/8dc78834cde4e329284cf505f9e3f99763df5529/packages/coding-agent/src/core/resource-loader.ts#L85-L119)。最终它们按带路径的 `<project_instructions>` XML 块拼入 system prompt：[system-prompt.ts L144-L151](https://github.com/earendil-works/pi/blob/8dc78834cde4e329284cf505f9e3f99763df5529/packages/coding-agent/src/core/system-prompt.ts#L144-L151)。项目级资源还受 project trust 控制；`--no-context-files` 可完全关闭。

### 3.3 扩展还能逐次改提示词

每次真正启动 agent 前，`AgentSession` 发出 `before_agent_start`。扩展可注入 custom messages 或替换本次 system prompt；本次 run 结束后 override 清除：[agent-session.ts L1212-L1252](https://github.com/earendil-works/pi/blob/8dc78834cde4e329284cf505f9e3f99763df5529/packages/coding-agent/src/core/agent-session.ts#L1212-L1252)。所以静态文件给出 base prompt，extension 则可做每次请求的动态注入。

## 4. 工具注册、执行和取消

### 4.1 注册层

内置定义共有 `read/bash/edit/write/grep/find/ls`，默认激活前四个。`AgentSession` 先创建全部内置 `ToolDefinition`，再合并 extension tools 和 SDK custom tools；同名后注册项覆盖前项。定义随后被包装成 `AgentTool`，放入 `_toolRegistry`，最后按 allowlist/denylist/活动名称写入 `agent.state.tools`：[agent-session.ts L2430-L2520](https://github.com/earendil-works/pi/blob/8dc78834cde4e329284cf505f9e3f99763df5529/packages/coding-agent/src/core/agent-session.ts#L2430-L2520)。`ToolDefinition → AgentTool` 的包装只是把 schema、执行模式和 `AbortSignal/onUpdate` 原样桥接：[tool-definition-wrapper.ts L4-L27](https://github.com/earendil-works/pi/blob/8dc78834cde4e329284cf505f9e3f99763df5529/packages/coding-agent/src/core/tools/tool-definition-wrapper.ts#L4-L27)。

### 4.2 执行层

模型输出完整 assistant message 后，core 才取出其中全部 tool calls。若全局模式为 sequential，或本批任一工具声明 `executionMode: "sequential"`，整批串行；否则先依次做 preflight，再并发执行。并发完成事件按实际完成顺序发出，但最终 tool result messages 仍按 assistant 源顺序加入 transcript：[agent-loop.ts L413-L427](https://github.com/earendil-works/pi/blob/8dc78834cde4e329284cf505f9e3f99763df5529/packages/agent/src/agent-loop.ts#L413-L427)、[L491-L555](https://github.com/earendil-works/pi/blob/8dc78834cde4e329284cf505f9e3f99763df5529/packages/agent/src/agent-loop.ts#L491-L555)。

每个调用的流水线为：

```text
按名称找工具
→ prepareArguments
→ TypeBox 参数校验
→ beforeToolCall（可 block）
→ tool.execute(signal, onUpdate)
→ afterToolCall（可改 content/details/isError/terminate）
→ tool_execution_end
→ toolResult message
```

工具缺失、参数错误、hook 异常、execute 抛错都会变成 `isError: true` 的 tool result 回给模型：[agent-loop.ts L602-L665](https://github.com/earendil-works/pi/blob/8dc78834cde4e329284cf505f9e3f99763df5529/packages/agent/src/agent-loop.ts#L602-L665)、[L668-L755](https://github.com/earendil-works/pi/blob/8dc78834cde4e329284cf505f9e3f99763df5529/packages/agent/src/agent-loop.ts#L668-L755)。如果 assistant 因输出 token 上限被截断，Pi 不执行其中任何工具，以避免截断 JSON 恰好通过校验后产生副作用：[agent-loop.ts L376-L407](https://github.com/earendil-works/pi/blob/8dc78834cde4e329284cf505f9e3f99763df5529/packages/agent/src/agent-loop.ts#L376-L407)。

### 4.3 取消层

`Agent.abort()` 对当前 run 的 `AbortController` 发信号；同一 signal 传给 provider stream、before/after hook 和所有工具：[agent.ts L304-L320](https://github.com/earendil-works/pi/blob/8dc78834cde4e329284cf505f9e3f99763df5529/packages/agent/src/agent.ts#L304-L320)。工具是否及时停止取决于实现是否遵守 signal。内置 bash 明确监听 abort，并调用 `killProcessTree(child.pid)`；timeout 也走同一进程树终止路径：[bash.ts L82-L145](https://github.com/earendil-works/pi/blob/8dc78834cde4e329284cf505f9e3f99763df5529/packages/coding-agent/src/core/tools/bash.ts#L82-L145)。

内置 edit 工具也在文件操作前后检查 signal，并让文件 mutation queue 的锁保持到操作真正结束，以避免 UI 已显示取消、后台写盘却稍后发生的竞态：[edit.ts L308-L348](https://github.com/earendil-works/pi/blob/8dc78834cde4e329284cf505f9e3f99763df5529/packages/coding-agent/src/core/tools/edit.ts#L308-L348)。但自定义工具的取消是协作式的：core 只能传 signal，扩展工具若忽略它，JavaScript 运行时不会强制抢占其任意异步工作。

Pi 默认没有逐工具 permission engine；扩展可通过 `tool_call` hook 实现确认或阻止。官方也明确说明默认继承启动用户/进程的文件、进程、网络和凭据权限：[README L37-L40](https://github.com/earendil-works/pi/blob/8dc78834cde4e329284cf505f9e3f99763df5529/README.md#L37-L40)。

## 5. Provider 与 models.json 如何合成

### 5.1 `pi-ai` 的 provider 是运行时基本单位

一个 provider 同时拥有 id/name/base metadata、认证、模型目录、可选动态刷新和 `stream/streamSimple`。`Models` 只负责 provider 集合、认证应用和请求分派：[models.ts L66-L125](https://github.com/earendil-works/pi/blob/8dc78834cde4e329284cf505f9e3f99763df5529/packages/ai/src/models.ts#L66-L125)。内置 provider 在 `builtinProviders()` 中统一注册：[providers/all.ts L77-L125](https://github.com/earendil-works/pi/blob/8dc78834cde4e329284cf505f9e3f99763df5529/packages/ai/src/providers/all.ts#L77-L125)。

### 5.2 `ModelRuntime` 组合三层来源

coding-agent 的 `ModelRuntime.create()`：

1. 加载 `auth.json` 对应的 credential store；
2. 默认读取 `~/.pi/agent/models.json`；
3. 创建模型缓存 `models-store.json`；
4. 加入所有内置 provider；
5. 合成 provider 并刷新动态模型目录。

见 [model-runtime.ts L92-L164](https://github.com/earendil-works/pi/blob/8dc78834cde4e329284cf505f9e3f99763df5529/packages/coding-agent/src/core/model-runtime.ts#L92-L164)。每个 provider 的来源集合是：

```text
builtin provider
  + models.json provider config
  + extension registerProvider config
  + models.json modelOverrides（模型级最高层）
```

若完全没有 overlay，直接使用原始 builtin，保留它精确的登录和 stream 行为；否则调用 `composeModelProvider()`：[model-runtime.ts L184-L215](https://github.com/earendil-works/pi/blob/8dc78834cde4e329284cf505f9e3f99763df5529/packages/coding-agent/src/core/model-runtime.ts#L184-L215)。

精确合成语义如下：

- `models.json.models` 对 builtin 模型按 `id` upsert；新模型缺省值会从同 provider 已有模型或默认值继承。
- extension 未提供 `models` 时只覆盖配置项；提供 `models` 时用 extension 列表替换此前列表。
- `models.json.modelOverrides[modelId]` 最后应用，因此是模型元数据的最高用户层。
- base URL、认证/header 由 extension → models.json → builtin 的对应字段组合；`authHeader` 可把解析后的 key 转成 Bearer header。
- stream 优先用 extension 自定义 `streamSimple`；否则若 builtin 支持该 model.api，沿用 builtin；再否则查询全局 API adapter。

证据见 [provider-composer.ts L161-L228](https://github.com/earendil-works/pi/blob/8dc78834cde4e329284cf505f9e3f99763df5529/packages/coding-agent/src/core/provider-composer.ts#L161-L228)、[L293-L381](https://github.com/earendil-works/pi/blob/8dc78834cde4e329284cf505f9e3f99763df5529/packages/coding-agent/src/core/provider-composer.ts#L293-L381) 和 [L411-L498](https://github.com/earendil-works/pi/blob/8dc78834cde4e329284cf505f9e3f99763df5529/packages/coding-agent/src/core/provider-composer.ts#L411-L498)。

`models.json` 先去除 JSON 注释，再经 TypeBox schema 校验，并 clone + deep-freeze 为一次不可变快照；失败时保留错误而不是使用半解析配置：[model-config.ts L225-L285](https://github.com/earendil-works/pi/blob/8dc78834cde4e329284cf505f9e3f99763df5529/packages/coding-agent/src/core/model-config.ts#L225-L285)。provider/model 可配字段的 schema 见 [model-config.ts L148-L198](https://github.com/earendil-works/pi/blob/8dc78834cde4e329284cf505f9e3f99763df5529/packages/coding-agent/src/core/model-config.ts#L148-L198)。

## 6. 会话持久化、分支、压缩和重试

### 6.1 JSONL 追加树

`SessionManager` 把 session 表示成 JSONL 追加树。header 包含版本、session id、时间、cwd 和可选 parent session；每个 entry 有 `id/parentId/timestamp`。entry 类型包括 message、model/thinking change、compaction、branch summary、extension custom/custom message、label 和 session info：[session-manager.ts L32-L168](https://github.com/earendil-works/pi/blob/8dc78834cde4e329284cf505f9e3f99763df5529/packages/coding-agent/src/core/session-manager.ts#L32-L168)。

`leafId` 指向当前分支尾部；追加 entry 时把当前 leaf 写为 `parentId`，然后推进 leaf。新 session 默认放在 `~/.pi/agent/sessions/<编码后的 cwd>/`：[session-manager.ts L468-L484](https://github.com/earendil-works/pi/blob/8dc78834cde4e329284cf505f9e3f99763df5529/packages/coding-agent/src/core/session-manager.ts#L468-L484)。

`AgentSession` 订阅 core 的事件，在 `message_end` 才同步追加完整 user/assistant/toolResult；custom message 单独持久化。因此 partial stream 不会逐 token 写 session：[agent-session.ts L573-L645](https://github.com/earendil-works/pi/blob/8dc78834cde4e329284cf505f9e3f99763df5529/packages/coding-agent/src/core/agent-session.ts#L573-L645)。新 session 文件会延迟到出现第一条 assistant message 才完整创建，之后采用 appendFile 追加：[session-manager.ts L946-L979](https://github.com/earendil-works/pi/blob/8dc78834cde4e329284cf505f9e3f99763df5529/packages/coding-agent/src/core/session-manager.ts#L946-L979)。

### 6.2 分支不是复制整段内存数组

同一 session 内 branch 只移动 `leafId` 到旧 entry；下一次 append 自然形成新 child，旧分支不删不改：[session-manager.ts L1283-L1294](https://github.com/earendil-works/pi/blob/8dc78834cde4e329284cf505f9e3f99763df5529/packages/coding-agent/src/core/session-manager.ts#L1283-L1294)。可选的 `branchWithSummary()` 会在新 leaf 下追加 abandoned path 摘要。若用户执行 fork/clone，则 `createBranchedSession()` 提取根到指定 leaf 的路径，重链接 label，写成新 session 文件，并在 header 记录 `parentSession`：[session-manager.ts L1305-L1413](https://github.com/earendil-works/pi/blob/8dc78834cde4e329284cf505f9e3f99763df5529/packages/coding-agent/src/core/session-manager.ts#L1305-L1413)。

恢复上下文时只沿当前 leaf 的 parent 链回到根，同时扫描 model/thinking change；不是简单读取文件中所有行：[session-manager.ts L321-L372](https://github.com/earendil-works/pi/blob/8dc78834cde4e329284cf505f9e3f99763df5529/packages/coding-agent/src/core/session-manager.ts#L321-L372)。

### 6.3 压缩只改变 Effective Context，不删除历史

压缩 entry 保存 structured summary、`firstKeptEntryId`、压缩前 token 数和可选扩展 details。构造 LLM context 时找到当前路径中最新 compaction，只投影为：

```text
compaction summary + firstKeptEntryId 起的保留尾部 + compaction 后的新消息
```

原始旧 entries 仍留在 JSONL 中：[session-manager.ts L406-L465](https://github.com/earendil-works/pi/blob/8dc78834cde4e329284cf505f9e3f99763df5529/packages/coding-agent/src/core/session-manager.ts#L406-L465)。

默认压缩预留 16,384 tokens、保留约 20,000 recent tokens；`prepareCompaction()` 在 turn 边界附近找 cut point，支持迭代更新旧 summary，若一个 turn 本身过大则单独总结被切掉的前缀。见 [compaction.ts L102-L109](https://github.com/earendil-works/pi/blob/8dc78834cde4e329284cf505f9e3f99763df5529/packages/coding-agent/src/core/compaction/compaction.ts#L102-L109)、[L633-L708](https://github.com/earendil-works/pi/blob/8dc78834cde4e329284cf505f9e3f99763df5529/packages/coding-agent/src/core/compaction/compaction.ts#L633-L708)。

自动压缩有两种触发：模型返回 context overflow，或估算 token 超过 `contextWindow - reserveTokens`。overflow 会移除活动内存里的 error assistant、压缩后自动 `continue()`；同一轮 compact-and-retry 最多尝试一次。阈值压缩通常不自动重发已完成回答：[agent-session.ts L1924-L2023](https://github.com/earendil-works/pi/blob/8dc78834cde4e329284cf505f9e3f99763df5529/packages/coding-agent/src/core/agent-session.ts#L1924-L2023)。压缩前后还有 `session_before_compact/session_compact` hook，扩展可取消或完全提供自定义 summary：[agent-session.ts L2029-L2169](https://github.com/earendil-works/pi/blob/8dc78834cde4e329284cf505f9e3f99763df5529/packages/coding-agent/src/core/agent-session.ts#L2029-L2169)。

### 6.4 两层重试

应区分：

- provider/API 层重试：`sdk.ts` 把 `maxRetries/maxRetryDelayMs/timeoutMs` 传给 `pi-ai` API adapter，处理单次 HTTP/stream 请求的可重试故障。
- AgentSession 层重试：一个 core run 已经产生 error assistant 后，判断是否 retryable；错误消息仍保存在 session 历史，但从活动 context 尾部移除，按 `baseDelayMs * 2^(attempt-1)` 可取消等待，再调用 `agent.continue()`。[agent-session.ts L1049-L1090](https://github.com/earendil-works/pi/blob/8dc78834cde4e329284cf505f9e3f99763df5529/packages/coding-agent/src/core/agent-session.ts#L1049-L1090)、[L2603-L2677](https://github.com/earendil-works/pi/blob/8dc78834cde4e329284cf505f9e3f99763df5529/packages/coding-agent/src/core/agent-session.ts#L2603-L2677)。

## 7. 扩展机制在哪里插入

### 7.1 加载与注册

扩展是可信任的 TypeScript/JavaScript 模块。loader 用 `jiti` 直接 import，不要求用户预编译；模块 default export 必须是 factory，Pi 创建 `ExtensionAPI` 后 `await factory(api)`：[extensions/loader.ts L390-L415](https://github.com/earendil-works/pi/blob/8dc78834cde4e329284cf505f9e3f99763df5529/packages/coding-agent/src/core/extensions/loader.ts#L390-L415)、[L441-L465](https://github.com/earendil-works/pi/blob/8dc78834cde4e329284cf505f9e3f99763df5529/packages/coding-agent/src/core/extensions/loader.ts#L441-L465)。factory 可注册 event handler、tool、command、shortcut、flag、renderer 和 provider：[extensions/loader.ts L217-L275](https://github.com/earendil-works/pi/blob/8dc78834cde4e329284cf505f9e3f99763df5529/packages/coding-agent/src/core/extensions/loader.ts#L217-L275)、[L350-L376](https://github.com/earendil-works/pi/blob/8dc78834cde4e329284cf505f9e3f99763df5529/packages/coding-agent/src/core/extensions/loader.ts#L350-L376)。

provider 注册发生得较早时会先进入 pending queue；`ExtensionRunner.bindCore()` 在 model registry 可用后 flush，之后注册/注销立即生效，不必 reload：[extensions/runner.ts L311-L382](https://github.com/earendil-works/pi/blob/8dc78834cde4e329284cf505f9e3f99763df5529/packages/coding-agent/src/core/extensions/runner.ts#L311-L382)。

### 7.2 插入点

扩展不是只加命令，它横切整个 AgentSession：

| 阶段 | 典型插入点 | 作用 |
|---|---|---|
| 启动/资源 | `session_start`、`resources_discover` | 动态加入 skills/prompts/themes，并重建 system prompt |
| prompt 前 | `before_agent_start` | 注入 custom message、修改本次 system prompt |
| 上下文 | `context` | 在 `convertToLlm` 前替换 `AgentMessage[]` |
| provider | `before_provider_headers/request`、`after_provider_response` | 改 headers/payload，观察响应 |
| 工具 | `tool_call`、`tool_result` | block 调用或改写结果 |
| 消息/生命周期 | `message_end`、turn/agent events | 改写同角色消息、记录或触发后续行为 |
| Session | switch/fork/tree/compact 前后事件 | 取消结构操作或自定义摘要 |

`context` handlers 按扩展顺序链式处理 cloned messages：[extensions/runner.ts L937-L967](https://github.com/earendil-works/pi/blob/8dc78834cde4e329284cf505f9e3f99763df5529/packages/coding-agent/src/core/extensions/runner.ts#L937-L967)。provider payload/header 也按顺序处理：[extensions/runner.ts L969-L1032](https://github.com/earendil-works/pi/blob/8dc78834cde4e329284cf505f9e3f99763df5529/packages/coding-agent/src/core/extensions/runner.ts#L969-L1032)。工具 hook 则由 `AgentSession` 映射到 core 的 `beforeToolCall/afterToolCall`：[agent-session.ts L441-L497](https://github.com/earendil-works/pi/blob/8dc78834cde4e329284cf505f9e3f99763df5529/packages/coding-agent/src/core/agent-session.ts#L441-L497)。

`/reload` 会清 extension cache、重读 settings/resources、重建 runner 和工具 registry，再发新的 session start/resource discover；旧 extension context 会失效：[agent-session.ts L2577-L2600](https://github.com/earendil-works/pi/blob/8dc78834cde4e329284cf505f9e3f99763df5529/packages/coding-agent/src/core/agent-session.ts#L2577-L2600)。

## 8. 一次请求的完整时序

```text
用户输入
  │
  ├─ prompt template / slash command 展开
  ├─ before_agent_start 扩展：改 prompt / 注入消息
  ▼
Agent.prompt()
  ├─ 创建 AbortController
  ├─ agent_start / turn_start / user message_end
  ▼
runAgentLoop
  ├─ extension context transform
  ├─ convertToLlm
  ├─ ModelRuntime：合成 provider/auth/header
  ├─ pi-ai API adapter 流式返回 text/thinking/toolCall delta
  ├─ assistant message_end → AgentSession 写 JSONL
  ├─ tool preflight → 扩展 tool_call → execute → tool_result
  ├─ toolResult message_end → 写 JSONL
  └─ 如有 tool calls，再请求模型；否则 agent_end
        │
        ▼
AgentSession 后处理
  ├─ 可重试错误：指数退避后 continue
  ├─ overflow/threshold：压缩 context，必要时 continue
  └─ agent_end hook 新排入消息：continue
```

## 9. 对“核心是如何实现的”的一句话回答

Pi 的核心不是复杂 planner，也没有内置子代理/计划模式。它是一个**事件驱动、单 active-run、可取消的流式状态机**：模型每次看到 `systemPrompt + 当前分支投影出的 messages + 活动 tools`；输出完整 tool calls 后执行工具，将 tool results 追加回上下文，再调用模型，直到没有工具、steering 和 follow-up。`pi-coding-agent` 在这个极小循环外，通过同步事件订阅组合出 JSONL Session、分支、压缩、重试、动态提示词和可信 TypeScript 扩展；`pi-ai` 则把不同供应商收敛为统一的流式消息协议。
