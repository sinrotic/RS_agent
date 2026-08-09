# ADR-0015：Agent 推荐适配器按对话查询选择接口

## 状态

已接受

## 背景

真实推荐服务提供候选接口与语义召回接口。仅调用候选接口不会携带用户在对话中的具体需求，无法充分利用 `recommend` Capability 的查询参数。

## 决策

- `AgentChatRequestDTO.userMessage` 非空时，HTTP 推荐适配器调用 `/agent/recommend/semantic-recall`；
- 请求携带 `query`、`session_id`、用户、场景、约束和受限 `return_count`；
- 空查询仍调用 `/agent/recommend/candidates`，保持无查询场景的兼容行为；
- 两种下游响应均在适配器中归一为 `AgentRecommendedItemVO`，不改变 Capability 或公开输出边界。

## 后果

Agent 模板的 `recommend` 能力可以基于对话问题触发真实语义召回；推荐服务的排序实现仍独立演进。
