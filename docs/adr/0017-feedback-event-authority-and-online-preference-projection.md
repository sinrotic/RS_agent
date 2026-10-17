# ADR-0017：推荐反馈事件与在线偏好投影的权威来源

- 状态：已接受
- 日期：2026-08-24

推荐反馈闭环以 MySQL 中追加保存的 Recommendation Feedback Event 为权威事实，并以数据库唯一约束提供跨实例幂等；Redis 只保存可由这些事件重建的 Session Preference 与 Profile Preference 在线投影。反馈写入事务同时分配 Preference Version 并登记投影任务，事务提交后再更新 Redis；因此 MySQL 成功而 Redis 暂时失败时，接口必须区分“事件已持久化”和“偏好已在线生效”。第一版不要求 Kafka 参与正确性，后续离线训练或流处理可通过 Outbox 异步接入而不改变反馈契约。
