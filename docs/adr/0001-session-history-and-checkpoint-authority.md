# 会话历史与上下文检查点的权威来源

会话语义事件和 Context Checkpoint 以 ScyllaDB 中的追加记录为权威事实；MySQL 只保存 Session 管理视图和最新 Checkpoint 的可修复定位投影，Redis 只保存可重建的 Effective Context 与运行状态。这样可以避免重复持久化近期消息，同时允许 Redis 丢失后按 MySQL 点位快速定位、从 ScyllaDB 重建，并在 MySQL 点位缺失或滞后时以 ScyllaDB 为准完成修复。
