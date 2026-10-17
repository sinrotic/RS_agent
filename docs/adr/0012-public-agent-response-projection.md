# ADR-0012：Java Agent 公开响应投影

## 状态

已接受（2026-08-08）。

## 决策

模型产生的 `emit_final_answer.blocks` 不再直接作为 SSE `answer_block` payload 输出。`PublicAgentResponseProjector` 是唯一公开投影入口：它先校验输出类型位于固定的公开类型集合，再校验该类型位于当前 Runtime Profile 的输出 allowlist，最后仅构造前端 wire contract 所需字段。

支持的公开类型是 `text`、`product_cards`、`comparison_table` 与 `followup_question`。公开字段限于 `type`、`content`、`card_set_id`、`item_ids`、`layout`，并且对字符串长度、商品 id 列表类型和列表数量实施边界校验。未在公开字段 allowlist 中的字段一律丢弃；未知类型、越权类型或畸形公开字段明确失败。

## 后果

- Capability payload、trace、diagnostics、raw path、ranking/retrieval evidence 与模型内部元数据不能通过模型参数进入用户可见 SSE payload；
- 已有四类公开 answer block 的字段形状保持不变，前端无需适配；
- 新增公开 block 或字段必须同时更新投影器、Runtime tool schema、Profile allowlist 与契约测试。

## A2UI 扩展（2026-10-09）

公开类型集合增加 `a2ui`，其公开字段为 `type` 和 `messages`。购物 Profile 允许该类型；`messages` 使用 A2UI v0.9 的四种消息，并限定到本应用的购物组件目录。服务端校验协议版本、目录、组件参数、数据路径、消息大小、界面生命周期与组件循环；前端复用现有商品卡片并渲染目录内的组件。

`emit_ui` 是可重放的展示工具，发布校验后的 `answer_block` 并继续 Agent Loop。`emit_final_answer` 完成 Turn。REST 响应新增 `answer_blocks`；公开 SSE 的 `done.response` 提供最终响应必要字段而不包含内部 `tool_calls`。用户确认的查询文字与当前界面状态通过下一次聊天请求回传，商品事实仍由 Catalog Item hydration 提供。
