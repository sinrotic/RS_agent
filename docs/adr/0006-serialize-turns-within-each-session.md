# Session 内串行执行，Session 间并行执行

每个 Session 只有一个 Session Execution Lane，同一时刻最多执行一个 Turn；后续 Turn 必须等待前一 Turn 完成或失败，不同 Session 可以并行。该模型为 Session Event 提供确定顺序，避免 Redis Effective Context 和 Context Checkpoint 被并发覆盖，并与现有按 Session 加锁、使用虚拟线程承载等待的执行方式一致。
