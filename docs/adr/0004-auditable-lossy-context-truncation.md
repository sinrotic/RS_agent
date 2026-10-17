# 上下文超限时允许可审计的有损裁剪

当常规压缩和强制压缩均无法解除上下文超限时，系统允许在 Safe Compaction Boundary 按完整语义组裁剪 Effective Context 中最旧的内容，保留当前用户消息、当前 Turn、近期上下文以及完整的 TOOL_USE/TOOL_RESULT 配对，并持久化裁剪范围和原因。该兜底只改变模型后续看到的上下文，不删除 ScyllaDB 中的 Durable Session History；最后一次重试仍失败时，本轮明确失败而不无限重试。
