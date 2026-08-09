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
