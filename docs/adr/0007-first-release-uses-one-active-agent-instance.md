# 第一版只运行一个活跃的 Agent 实例

第一版将 `rs-service-agent` 限制为单个活跃实例，由进程内 Session Execution Lane 串行执行同一 Session 的 Turn。暂不使用 Redis Lease 充当分布式正确性来源；未来需要水平扩展时，必须同时引入 fencing token 和能够拒绝旧 token 的持久化追加机制，避免暂停后恢复的旧实例继续写入 Session Event。
