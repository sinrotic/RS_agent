# Claude Code 长期记忆机制源码研究

更新时间：2026-07-22  
研究对象：本仓库 `参考/claudecode_src/` 中的 Claude Code 本地源码快照  
资料边界：只使用该源码快照，不使用第三方文章或网络资料；不修改实现代码。

> 版本说明：`参考/claudecode_src/` 被仓库忽略，目录中没有可验证的发行版清单或上游 commit，因此本文不把结论冒充成某个公开版本的稳定 API。所有结论都只描述这个本地快照，并引用本地源码文件与行号。

## 结论摘要

1. **Claude Code 的“长期记忆”不是数据库或向量库，而是一套项目作用域的 Markdown 文件系统。** 默认目录是 `~/.claude/projects/<sanitized-canonical-git-root>/memory/`，入口为 `MEMORY.md`，具体内容分散在带 YAML frontmatter 的主题文件里；同一 Git 仓库的不同 worktree 共享一个目录。源码也支持受信设置或 Cowork 环境覆盖路径。见 `参考/claudecode_src/memdir/paths.ts:80-93`、`:198-235`、`:253-259`。
2. **写入有两条互补路径。** 主模型的系统提示词始终告诉它何时、如何直接保存；在启用实验开关时，每个完整 query loop 结束后还会启动一个最多 5 turn 的 forked extraction agent，回看自上次游标以来的新消息并补写遗漏。若主模型本轮已经写过自动记忆，后台提取器会跳过该区间，避免重复。见 `参考/claudecode_src/memdir/memdir.ts:187-265`、`参考/claudecode_src/query/stopHooks.ts:133-156`、`参考/claudecode_src/services/extractMemories/extractMemories.ts:329-386`、`:415-435`。
3. **默认读取策略是“两级索引”。** `MEMORY.md` 随 CLAUDE.md 一起自动注入上下文，但最多加载 200 行且不超过 25,000 字符；主题文件不全部注入，模型根据索引链接、描述或搜索提示按需 Read/Grep。见 `参考/claudecode_src/utils/claudemd.ts:979-1007`、`:1153-1195`，以及 `参考/claudecode_src/memdir/memdir.ts:34-38`、`:57-103`、`:221-233`。
4. **`tengu_moth_copse` 打开后，读取策略改为查询时相关性召回。** 此时 `MEMORY.md` 不再注入；系统扫描最多 200 个最近修改的主题 Markdown 文件，只读前 30 行 frontmatter，用 Sonnet 根据当前用户问题从文件名和 `description` 中最多选 5 个，再把正文以隐藏的 `system-reminder` attachment 注入。选择异步预取、零等待，若当前模型迭代结束前未完成则本轮可能不消费。见 `参考/claudecode_src/utils/claudemd.ts:1136-1150`、`参考/claudecode_src/memdir/memoryScan.ts:21-28`、`:35-74`、`参考/claudecode_src/memdir/findRelevantMemories.ts:18-38`、`:39-75`、`参考/claudecode_src/utils/attachments.ts:2334-2423`、`参考/claudecode_src/query.ts:1924-1953`。
5. **Auto Memory 与 Session Memory 必须分开。** Auto Memory 跨会话、按项目积累用户/反馈/项目背景/外部资源指针；Session Memory 是每个 session 的 `summary.md`，周期性记录当前任务、文件、错误、工作日志等，主要服务于压缩后的连续性。后者不是面向未来任意会话的知识库。见 `参考/claudecode_src/memdir/memoryTypes.ts:113-178`、`参考/claudecode_src/services/SessionMemory/sessionMemory.ts:1-4`、`参考/claudecode_src/utils/permissions/filesystem.ts:257-270`、`参考/claudecode_src/services/SessionMemory/prompts.ts:11-41`。
6. **CLAUDE.md 是显式、规范性的指令层；Auto Memory 是模型维护的经验层。** 自动记忆提示明确禁止重复保存已经写在 CLAUDE.md 中的内容；`/remember` 只提出把稳定规则提升到 `CLAUDE.md`/`CLAUDE.local.md` 的建议，未经用户批准不得改文件。源码没有实现一个按 key 合并并裁决冲突的规则引擎，最终仍是把多份文本按顺序拼进上下文，再依赖提示词要求模型验证新状态、删除过期记忆。见 `参考/claudecode_src/memdir/memoryTypes.ts:180-202`、`参考/claudecode_src/skills/bundled/remember.ts:9-61`、`参考/claudecode_src/utils/claudemd.ts:1153-1195`。

## 1. 先区分三类“记忆”

| 机制 | 作用域与寿命 | 磁盘形态 | 主要用途 |
|---|---|---|---|
| CLAUDE.md / rules | managed、用户全局、项目共享、项目本地；跨会话 | Markdown | 明确指令、约定、规则 |
| Auto Memory | 默认按 canonical Git 仓库；跨会话、跨 worktree | `memory/MEMORY.md` + 主题 Markdown | 用户画像、反馈、非代码可推导的项目背景、外部资源指针 |
| Session Memory | 单 session | `<projectDir>/<sessionId>/session-memory/summary.md` | 当前工作状态与压缩恢复摘要 |

这三者在源码中虽然都可能被 UI 称为 memory，但用途不同。`claudemd.ts` 自己也把 AutoMem/TeamMem 从 `InstructionsLoaded` hook 中排除，称它们是独立的 memory system，而不是 CLAUDE.md/rules 意义上的 instructions。见 `参考/claudecode_src/utils/claudemd.ts:1042-1068`。

会话 transcript 又是第四种持久化：`~/.claude/projects/<sanitized-cwd>/<session-id>.jsonl`。它保存对话、attachments 和 compact boundary，是 `/resume` 与兜底历史搜索的数据源，不等于精炼后的长期记忆。见 `参考/claudecode_src/utils/sessionStorage.ts:198-229`、`参考/claudecode_src/memdir/memdir.ts:389-404`。

## 2. Auto Memory 如何生成

### 2.1 主模型直接写：第一责任路径

`loadMemoryPrompt()` 在自动记忆开启时创建 memory 目录，并把完整的行为说明放入 system prompt。说明要求：

- 用户明确说“记住”时立即保存；明确说“忘掉”时查找并删除；
- 每条记忆写成独立主题文件；默认同时向 `MEMORY.md` 增加一行短链接；
- 按主题而不是按日期组织；先更新已有文件，避免重复；
- 发现错误或过期内容时更新或删除。

证据见 `参考/claudecode_src/memdir/memdir.ts:199-265`。该 prompt 由默认系统提示词构造路径加载并做 section cache；`--bare` 会跳过整套默认提示。见 `参考/claudecode_src/constants/prompts.ts:444-495`。

自动记忆默认启用，但存在明确的关闭优先链：`CLAUDE_CODE_DISABLE_AUTO_MEMORY`、`--bare`/`CLAUDE_CODE_SIMPLE`、没有持久存储的 remote 环境、`settings.json:autoMemoryEnabled`，最后才是默认开启。见 `参考/claudecode_src/memdir/paths.ts:21-55`。

### 2.2 后台 extraction agent：补漏路径

启用 `EXTRACT_MEMORIES` 构建能力和 `tengu_passport_quail` gate 后，主线程在一个完整 query loop 的 stop hooks 阶段 fire-and-forget 调用 `executeExtractMemories()`；subagent、remote mode 和关闭 auto-memory 的环境都会跳过。见 `参考/claudecode_src/query/stopHooks.ts:133-153`、`参考/claudecode_src/services/extractMemories/extractMemories.ts:527-567`。

算法如下：

1. 用 `lastMemoryMessageUuid` 作为增量游标，只统计游标之后模型可见的 user/assistant 消息；若 compact 已移除游标，则退化为扫描当前全部可见消息，避免本 session 永久停用提取。见 `参考/claudecode_src/services/extractMemories/extractMemories.ts:74-109`、`:305-307`。
2. 先检测该区间是否已有主模型的 Write/Edit 指向 auto-memory。若有，跳过 fork 并推进游标，主模型与后台 agent 在一个区间内互斥。见同文件 `:112-148`、`:345-360`。
3. 默认每个符合条件的 turn 运行一次；实际间隔可由 `tengu_bramble_lintel` 调整。并发调用不重叠，而是只保留最新 context，当前任务结束后补跑一次 trailing extraction。见同文件 `:312-325`、`:374-386`、`:503-521`、`:554-566`。
4. 扫描现有主题文件 frontmatter 形成 manifest，提前告诉提取 agent 已有哪些记忆，要求优先更新而不是新建重复文件。见同文件 `:395-413` 与 `参考/claudecode_src/services/extractMemories/prompts.ts:26-43`。
5. `runForkedAgent()` 继承主对话前缀和 prompt cache，但不写自己的 transcript，最多 5 turn；只有成功后才推进游标，失败会在下一次重试同一批消息。见 `参考/claudecode_src/services/extractMemories/extractMemories.ts:415-435`。

这不是抽取模型输出 JSON 后由代码落库，而是**让一个受限 forked agent 自己调用 Read/Edit/Write 改 Markdown**。其允许的能力只有 Read/Grep/Glob、只读 Bash、REPL 包装，以及 memory 目录内的 Edit/Write；其他工具和可写 shell 命令被拒绝。见 `参考/claudecode_src/services/extractMemories/extractMemories.ts:166-220`。

### 2.3 保存内容的判定算法

保存判定主要由 prompt 驱动，而不是手写规则分类器。它把内容限制为四类：

- `user`：用户角色、目标、责任、知识与有助于协作的偏好；
- `feedback`：用户纠正过的方法，以及用户明确肯定过的非显然做法；
- `project`：代码和 git 无法推出的工作背景、决定、责任人、原因和期限；
- `reference`：外部系统中最新信息应去哪里查的指针。

类型定义与触发条件见 `参考/claudecode_src/memdir/memoryTypes.ts:113-178`。反馈和项目类还要求正文包含规则/事实、`Why` 和 `How to apply`；相对日期应转换成绝对日期。见同文件 `:133-154`。

以下内容即使用户明确要求保存也应排除：当前代码可推导的架构/模式/路径、git 历史、调试修复配方、CLAUDE.md 已有内容、临时任务状态。对于“保存这周 PR 列表”一类请求，prompt 要求反问其中真正反常或不可推导的部分。见 `参考/claudecode_src/memdir/memoryTypes.ts:180-195`。

### 2.4 跨 session 的自动整理：Auto Dream 与 KAIROS 变体

普通模式还有后台 consolidation：默认至少距离上次整理 24 小时、且有 5 个不含当前 session 的新 session，取得跨进程 lock 后才启动 forked agent；失败或用户终止会回滚 lock 时间，使后续可重试。见 `参考/claudecode_src/services/autoDream/autoDream.ts:1-9`、`:54-100`、`:125-198`、`:224-270`。

KAIROS/长驻 assistant 模式采用另一种写入形态：新记忆追加到 `logs/YYYY/MM/YYYY-MM-DD.md` 的时间戳 bullet，而不是实时维护 `MEMORY.md`；另一个 nightly `/dream` 再把日志蒸馏成主题文件与索引。`MEMORY.md` 仍作为蒸馏后的读取入口。见 `参考/claudecode_src/memdir/paths.ts:237-250`、`参考/claudecode_src/memdir/memdir.ts:318-369`。

## 3. 持久化位置与格式

### 3.1 Auto Memory

默认解析为：

```text
~/.claude/
└── projects/
    └── <sanitize(canonical-git-root-or-project-root)>/
        └── memory/
            ├── MEMORY.md
            ├── user_role.md
            ├── feedback_testing.md
            └── ...
```

`findCanonicalGitRoot()` 让同一仓库的多个 worktree 共用记忆；非 Git 目录退回稳定 `projectRoot`。目录可由 `CLAUDE_COWORK_MEMORY_PATH_OVERRIDE` 或受信设置源的 `autoMemoryDirectory` 覆盖。项目仓库内可提交的 `projectSettings` 被刻意排除，防止恶意仓库把写入目录改成 `~/.ssh`。见 `参考/claudecode_src/memdir/paths.ts:152-185`、`:198-235`。

主题文件格式为：

```markdown
---
name: memory name
description: 用于未来相关性判断的一行具体描述
type: user | feedback | project | reference
---

正文
```

`MEMORY.md` 没有 frontmatter，只是每个主题一行的链接索引，目标长度约低于 150 字符，不应直接放详细记忆。见 `参考/claudecode_src/memdir/memoryTypes.ts:258-271`、`参考/claudecode_src/memdir/memdir.ts:221-233`。

源码中没有为 Auto Memory 建立数据库表、embedding 或向量索引。相关性召回每次直接递归列目录、读取 Markdown 的前 30 行、解析 YAML frontmatter，再调用模型选择；因此其索引本质上是“文件系统 + frontmatter manifest”。见 `参考/claudecode_src/memdir/memoryScan.ts:35-74`、`参考/claudecode_src/memdir/findRelevantMemories.ts:77-140`。

### 3.2 Session Memory 与 transcript

Session Memory 的路径是：

```text
~/.claude/projects/<sanitized-cwd>/<session-id>/session-memory/summary.md
```

目录和文件分别以 `0700`、`0600` 创建。文件固定包含 Session Title、Current State、Task specification、Files and Functions、Workflow、Errors & Corrections、Codebase and System Documentation、Learnings、Key results、Worklog 等区段。见 `参考/claudecode_src/utils/permissions/filesystem.ts:257-270`、`参考/claudecode_src/services/SessionMemory/sessionMemory.ts:183-232`、`参考/claudecode_src/services/SessionMemory/prompts.ts:11-41`。

同一 session 的完整 transcript 位于项目目录根部的 `<session-id>.jsonl`，与 `summary.md` 分开。主题 Auto Memory 不依赖这个 summary 文件，但 memory prompt 会把 JSONL transcript 搜索作为“最后手段”。见 `参考/claudecode_src/utils/sessionStorage.ts:198-229`、`参考/claudecode_src/memdir/memdir.ts:389-404`。

## 4. 会话开始时如何加载和使用

### 4.1 CLAUDE.md 与 Auto Memory 的共同入口

`getUserContext()` 在会话查询装配时调用 `getMemoryFiles()`，再用 `getClaudeMds()` 拼成 `claudeMd` context。`query()` 在每次模型 API 调用前用 `prependUserContext()` 把它放到第一条隐藏 user message 的 `<system-reminder>` 中。`getUserContext()` 是 memoized 的，因此正常情况下会话内复用同一快照。见 `参考/claudecode_src/context.ts:152-188`、`参考/claudecode_src/utils/api.ts:449-474`、`参考/claudecode_src/query.ts:798-807`。

`getMemoryFiles()` 的顺序是：

1. Managed CLAUDE.md/rules；
2. User `~/.claude/CLAUDE.md` 和 `~/.claude/rules/`；
3. 从文件系统根向当前目录逐层加载项目 `CLAUDE.md`、`.claude/CLAUDE.md`、无条件 rules；
4. 同层 `CLAUDE.local.md`；
5. Auto Memory 的 `MEMORY.md`；
6. 若启用，再加入 Team Memory 的 `MEMORY.md`。

实现见 `参考/claudecode_src/utils/claudemd.ts:790-934`、`:979-1007`。文件头的优先级说明只对 Managed/User/Project/Local 指令层给出正式语义：后加载者更高，离 cwd 越近越高。见同文件 `:1-25`。

### 4.2 两种 Auto Memory 加载策略

#### 策略 A：`tengu_moth_copse = false`，索引常驻

`MEMORY.md` 被标记为 `AutoMem`，与 CLAUDE.md 文本一起注入。模型先看到索引，再按链接或系统提示中的 Grep 命令查具体主题文件；系统不会一次加载全部主题文件。见 `参考/claudecode_src/utils/claudemd.ts:979-990`、`:1153-1195`、`参考/claudecode_src/memdir/memdir.ts:372-406`。

优点是稳定、无额外选择模型调用、首轮就有索引；代价是索引常驻 token，且主题是否读取依赖主模型判断。

#### 策略 B：`tengu_moth_copse = true`，相关主题按 query 预取

`filterInjectedMemoryFiles()` 会从开场 context 去掉 AutoMem/TeamMem 索引。每个用户 turn 启动一次异步 selector：忽略单词级短 prompt，排除已在本 session 注入或 Read/Edit/Write 过的文件，Sonnet 最多选 5 个明确相关的主题文件。见 `参考/claudecode_src/utils/claudemd.ts:1136-1150`、`参考/claudecode_src/utils/attachments.ts:2361-2404`、`参考/claudecode_src/memdir/findRelevantMemories.ts:18-24`。

选中的文件以带保存年龄和路径的 `relevant_memories` attachment 注入；attachment 最终也被规范化为隐藏的 `<system-reminder>` user message。见 `参考/claudecode_src/utils/attachments.ts:2196-2242`、`参考/claudecode_src/utils/messages.ts:3708-3721`。

该预取不阻塞主模型。query loop 只在 tool 执行之后的收集点检查 promise 是否已完成；未完成就零等待跳过，若还有下一次迭代再试。因而对“一次模型响应直接结束、无工具迭代”的 turn，相关记忆可能来不及进入本轮模型上下文。见 `参考/claudecode_src/utils/attachments.ts:2334-2344`、`参考/claudecode_src/query.ts:1924-1953`。

## 5. 压缩与恢复

### 5.1 Auto Memory 在 compact 后重新加载

主线程 compact 完成后，`runPostCompactCleanup()` 同时清除外层 `getUserContext` 缓存和内层 `getMemoryFiles` 缓存，并把下一次 instruction load reason 标成 `compact`。所以下一轮会从磁盘重新读取最新 CLAUDE.md 与 `MEMORY.md`，而不是永久沿用 session 开始时的旧快照。subagent compact 不会清主线程的共享缓存。见 `参考/claudecode_src/services/compact/postCompactCleanup.ts:12-39`、`:51-62`、`参考/claudecode_src/utils/claudemd.ts:1088-1130`。

相关性 attachment 的 session 总量计数直接从当前 messages 扫描。compact 后旧 attachment 已离开当前上下文，计数自然归零，已被 compact 掉的主题允许再次召回。见 `参考/claudecode_src/utils/attachments.ts:2244-2265`。

### 5.2 Session Memory 如何生成并替代传统 compact summary

Session Memory 是 gated 实验能力，而且只在主 REPL、非 remote、auto-compact 开启时注册 post-sampling hook。默认阈值是上下文达到 10,000 token 后初始化；之后至少再增长 5,000 token，并满足 3 个 tool call，或处于无 tool call 的自然断点时更新。token 增长阈值始终是必要条件。见 `参考/claudecode_src/services/SessionMemory/sessionMemoryUtils.ts:15-36`、`:169-195`、`参考/claudecode_src/services/SessionMemory/sessionMemory.ts:134-180`、`:272-375`。

更新同样由 forked agent 完成，但权限更窄：只能 Edit 当前 session 的 `summary.md`。prompt 要求只根据真实用户对话更新固定区段，排除 system prompt、CLAUDE.md 和过去摘要，尤其保持 `Current State` 最新。见 `参考/claudecode_src/services/SessionMemory/sessionMemory.ts:302-347`、`:460-478`、`参考/claudecode_src/services/SessionMemory/prompts.ts:43-80`。

当 `tengu_session_memory` 与 `tengu_sm_compact` 同时开启时，compact 优先尝试使用该 Markdown 作为 summary，而不再为摘要额外调用传统 compact LLM：

- 正常情况保留 `lastSummarizedMessageId` 之后的消息，并扩张保留区以满足最小 token/文本消息数及 tool_use/tool_result 完整性；
- resumed session 若磁盘上已有 summary、但进程内游标丢失，则用整个 session memory 作为 summary，并按保留规则选择近期消息；
- 文件缺失、仍为空模板、游标找不到或 compact 后仍超过阈值时，返回 `null`，回退旧 compact 路径。

见 `参考/claudecode_src/services/compact/sessionMemoryCompact.ts:400-432`、`:505-620`。默认保留区配置是至少 10,000 token、至少 5 条带文本消息、硬上限 40,000 token。见同文件 `:45-66`。

### 5.3 `/resume` 和进程恢复

恢复 session 时，旧 JSONL 被还原为 `result.messages`；当前 worktree/cwd 变化会清 CLAUDE.md 文件缓存。新查询仍会经过 `fetchSystemPromptParts() → getUserContext()`，所以长期记忆来自当前磁盘状态，而不是从旧 compact summary 推测。见 `参考/claudecode_src/utils/sessionRestore.ts:332-365`、`:402-410`、`:518-535`、`参考/claudecode_src/utils/queryContext.ts:44-73`。

`relevant_memories` attachments 本身也会被写进 transcript，并在恢复后重新规范化为 API user messages；因此未被 compact 淘汰的已召回正文可随会话恢复。见 `参考/claudecode_src/QueryEngine.ts:829-835`、`参考/claudecode_src/utils/messages.ts:2269-2290`、`:3708-3721`。

这里要注意：Auto Memory 解决“未来会话应该知道什么”，Session Memory/compact summary 解决“同一会话压缩或恢复后怎样继续当前工作”。后者里的临时 worklog、修复步骤等恰恰是 Auto Memory prompt 明确排除的内容。

## 6. CLAUDE.md 与 Auto Memory 的关系、优先级和边界

### 6.1 CLAUDE.md 是用户治理层

`/init` 明确说明 CLAUDE.md 会加载到每个 session，应保持最小化，只保存 Claude 若不知道就会犯错的指令；项目共享内容写根 `CLAUDE.md`，个人项目指令写 `CLAUDE.local.md` 并加入 `.gitignore`，模块规则可拆入 `.claude/rules/`。现有文件只能提议 diff，不可静默覆盖。见 `参考/claudecode_src/commands/init.ts:28-46`、`:95-150`。

明确的指令层优先次序为 Managed → User → Project → Local，后加载、离 cwd 更近的文件优先。项目和本地规则还可用 `paths` frontmatter 懒加载到触及相关文件的 turn。见 `参考/claudecode_src/utils/claudemd.ts:1-25`、`:1240-1318`、`:1344-1396`。

### 6.2 Auto Memory 是模型治理层，但不应复制规范

Auto Memory 只保存未来可能有用、又不能从当前代码/git/CLAUDE.md 得出的背景。它可被主模型和 extraction agent 自动创建、更新、删除；用户可直接要求 remember/forget。见 `参考/claudecode_src/memdir/memdir.ts:239-257`、`参考/claudecode_src/memdir/memoryTypes.ts:180-195`。

`/remember` 的设计体现了两层边界：稳定、团队通用的项目约定建议提升到 `CLAUDE.md`；个人对 Claude 的项目指令建议提升到 `CLAUDE.local.md`；重复项从 Auto Memory 清理；冲突与模糊归属先交用户确认。该命令只报告提案，未获明确批准不得写文件。见 `参考/claudecode_src/skills/bundled/remember.ts:9-61`。

### 6.3 不存在代码级冲突裁决器

`getClaudeMds()` 只是按发现顺序拼接各文件，并统一置于“instructions override default behavior”的上下文前缀下；源码没有按事实 key、时间戳或来源做结构化 merge。Auto Memory 虽在物理列表中追加到 Local 之后，但代码注释并没有把它定义成高于 CLAUDE.md 的规范指令层，因此不应把“追加更晚”直接解释为“自动记忆可以覆盖显式 CLAUDE.md”。见 `参考/claudecode_src/utils/claudemd.ts:89-92`、`:979-1007`、`:1153-1195`。

真正的冲突策略来自 memory prompt：

- 已在 CLAUDE.md 的内容不要另存；
- 记忆只是写入时的事实快照；
- 回答或建议前应检查当前文件/资源；
- 当前观察与记忆冲突时信当前状态，并更新或删除旧记忆；
- 用户要求忽略 memory 时，按 `MEMORY.md` 为空处理，不应用、比较、引用或提及其中内容。

见 `参考/claudecode_src/memdir/memoryTypes.ts:180-220`、`:240-256`。

## 7. 安全、失效与容量策略

### 7.1 路径和工具权限

- Auto-memory 覆盖路径必须是绝对、非根/近根、非 Windows drive root、非 UNC、无 NUL 的规范化路径；`~/` 只允许受信 settings 展开，不能退化为 home 或其父目录。见 `参考/claudecode_src/memdir/paths.ts:95-149`。
- 可提交的 project settings 不能指定 `autoMemoryDirectory`，避免恶意仓库获得敏感目录的静默写权限。见同文件 `:168-185`。
- extraction/auto-dream agent 的写权限只允许 memory 目录；shell 只允许只读命令，MCP、Agent、可写 Bash 等被拒绝。见 `参考/claudecode_src/services/extractMemories/extractMemories.ts:166-220`。
- Session Memory 目录/文件以 `0700`/`0600` 创建，fork 只能编辑精确的 `summary.md`。见 `参考/claudecode_src/services/SessionMemory/sessionMemory.ts:183-206`、`:460-478`。

### 7.2 指令文件 include 边界

CLAUDE.md 支持 `@path` 递归 include，但只允许文本扩展名、做循环去重，最大深度 5；项目文件引用工作目录外部路径时默认不加载，需用户批准。User `~/.claude/CLAUDE.md` 的外部 include 则始终允许，因为它本身属于用户受信源。见 `参考/claudecode_src/utils/claudemd.ts:18-25`、`:94-110`、`:615-684`、`:790-846`。

### 7.3 敏感数据边界

Team Memory prompt 明确禁止共享 API key 或用户凭据。见 `参考/claudecode_src/services/extractMemories/prompts.ts:143-153`。本快照的 individual Auto Memory 四类型 prompt 没有同等具体的“任何敏感数据一律不写”条款；它依赖本地项目作用域、工具权限和其他通用安全规则。因而如果借鉴该设计，建议额外加入 secret/PII 检测与显式禁止策略，而不要把“本地 Markdown”误当成数据分类控制。

### 7.4 截断和总量限制

- `MEMORY.md`：最多注入 200 行和 25,000 字符，先按行、再在换行边界按字符截断，并追加警告；磁盘原文件不被自动裁剪。见 `参考/claudecode_src/memdir/memdir.ts:34-38`、`:49-103`。
- 相关性候选：递归扫描主题文件，但只保留 mtime 最新的 200 个；每文件只读前 30 行 frontmatter。超过 200 个的旧文件仍在磁盘，只是不进入 selector manifest。见 `参考/claudecode_src/memdir/memoryScan.ts:21-28`、`:35-74`。
- 每次召回：最多 5 个文件；每文件最多 200 行和 4,096 字符，因此单 turn 约上限 20 KB。见 `参考/claudecode_src/memdir/findRelevantMemories.ts:18-24`、`参考/claudecode_src/utils/attachments.ts:269-288`、`:2268-2320`。
- 单个未压缩 session 的相关记忆累计注入达到 60 KB 后停止预取；compact 移除旧 attachments 后重新计数。见 `参考/claudecode_src/utils/attachments.ts:279-289`、`:2383-2386`。
- 普通 CLAUDE.md 的 40,000 字符只是“大文件告警”阈值，不是自动截断器。见 `参考/claudecode_src/utils/claudemd.ts:89-92`、`:1132-1134`、`参考/claudecode_src/utils/doctorContextWarnings.ts:44-66`。
- Session Memory prompt 期望每区约不超过 2,000 token、总计不超过 12,000 token；更新时要求主动压缩。用于 compact 时又会硬截每个过大区段，并保留完整文件路径供人工读取。见 `参考/claudecode_src/services/SessionMemory/prompts.ts:8-10`、`:161-195`、`:249-324`、`参考/claudecode_src/services/compact/sessionMemoryCompact.ts:459-474`。

### 7.5 失效、陈旧和失败回退

- 主题文件的 mtime 会转成“today/yesterday/N days ago”；超过 1 天的召回自动加入“这是时间点观察，代码/行号可能过期，应验证”的警告。见 `参考/claudecode_src/memdir/memoryAge.ts:1-41`、`参考/claudecode_src/utils/attachments.ts:2323-2332`。
- memory prompt 要求把当前文件/资源作为权威来源，冲突时修改或删除旧记忆，而不是盲信。见 `参考/claudecode_src/memdir/memoryTypes.ts:197-202`、`:240-256`。
- extraction 是 best-effort：异常只记录，不打断主对话；只有成功才推进游标。并发请求合并成一次 trailing run。见 `参考/claudecode_src/services/extractMemories/extractMemories.ts:429-435`、`:497-522`。
- selector 失败、Abort 或返回不存在的文件名时返回空列表，不阻塞主对话。见 `参考/claudecode_src/memdir/findRelevantMemories.ts:97-140`。
- Session Memory compact 若文件为空、游标不可信或产物仍太大，会回退传统 compact，不拿不完整 summary 强行继续。见 `参考/claudecode_src/services/compact/sessionMemoryCompact.ts:505-620`。

## 8. 关键调用链

### 8.1 会话开始与普通模型调用

```text
QueryEngine.ask
  → fetchSystemPromptParts
      → getSystemPrompt
          → loadMemoryPrompt             # 注入保存/读取行为规则
      → getUserContext
          → getMemoryFiles               # CLAUDE.md + MEMORY.md（视 gate）
          → getClaudeMds
  → query
      → prependUserContext               # 隐藏 user/system-reminder
      → callModel
```

对应源码：`参考/claudecode_src/QueryEngine.ts:284-325`、`参考/claudecode_src/utils/queryContext.ts:44-73`、`参考/claudecode_src/context.ts:152-188`、`参考/claudecode_src/query.ts:798-807`。

### 8.2 每个用户 turn 的相关性召回（`tengu_moth_copse`）

```text
queryLoop entry
  → startRelevantMemoryPrefetch
      → scanMemoryFiles
      → findRelevantMemories / Sonnet sideQuery
      → readMemoriesForSurfacing
  → 主模型流与工具执行并行进行
  → post-tools collect point
      → filterDuplicateMemoryAttachments
      → relevant_memories attachment
      → normalizeAttachmentForAPI
      → <system-reminder> topic contents
```

对应源码：`参考/claudecode_src/query.ts:346-358`、`:1924-1953`，`参考/claudecode_src/utils/attachments.ts:2196-2242`、`:2361-2423`、`:2505-2541`，`参考/claudecode_src/utils/messages.ts:3708-3721`。

### 8.3 turn 结束后的自动提取

```text
handleStopHooks
  → executeExtractMemories
      → hasMemoryWritesSince              # 主模型已写则跳过
      → scanMemoryFiles / manifest
      → runForkedAgent(maxTurns=5)
          → restricted Read/Grep/Glob/Bash/Edit/Write
      → topic Markdown + MEMORY.md
      → memory_saved system message
```

对应源码：`参考/claudecode_src/query/stopHooks.ts:133-156`、`参考/claudecode_src/services/extractMemories/extractMemories.ts:329-435`、`:455-503`。

### 8.4 Session Memory 与 compact

```text
postSamplingHook
  → shouldExtractMemory(tokens/tool calls)
  → setupSessionMemoryFile
  → runForkedAgent(Edit summary.md only)
  → setLastSummarizedMessageId

autoCompact
  → trySessionMemoryCompaction
      → waitForSessionMemoryExtraction
      → getSessionMemoryContent
      → calculateMessagesToKeepIndex
      → processSessionStartHooks("compact")
      → summary + recent preserved messages
      → 失败则 legacy compact
```

对应源码：`参考/claudecode_src/services/SessionMemory/sessionMemory.ts:267-375`、`参考/claudecode_src/services/compact/sessionMemoryCompact.ts:505-620`。

## 9. 对本项目设计长期记忆的可借鉴点

从实现而不是宣传看，Claude Code 的核心取舍是：

1. 用可审计、可手工编辑的 Markdown 作为真源，不把模型记忆藏在不可见数据库里；
2. 用小索引/description 做廉价导航，把正文按需召回；
3. 把“当前任务连续性”与“跨会话稳定知识”拆成 Session Memory 和 Auto Memory；
4. 直接写与 turn-end 补漏互斥，避免两个 agent 重复落盘；
5. 让 CLAUDE.md 承担明确规范，让自动记忆只补不可推导背景，并提供人工提升/清理流程；
6. 把陈旧性、当前状态验证、路径权限、召回预算和失败回退设计成一等机制。

如果在本项目复刻，不应只照搬 `MEMORY.md` 文件名；真正关键的是这几个边界。尤其应补强本快照在 private memory 上不够明确的 secret/PII 策略，并为多个冲突来源增加可测试的、代码级优先级规则，而不是完全依赖模型理解拼接文本。
