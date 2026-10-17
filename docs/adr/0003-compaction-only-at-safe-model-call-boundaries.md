# 只在安全的模型调用边界切换有效上下文

上下文压缩只允许在即将发起模型调用、既有语义事件已经持久化且不存在未完成工具调用的 Safe Compaction Boundary 生效；它可以位于 Turn 中间的 TOOL_RESULT 之后，但不能发生在模型流式输出、工具执行或写队列尚未刷入期间。该约束允许长工具循环及时压缩，同时保证 TOOL_USE 与 TOOL_RESULT 不被拆开，并使 Context Checkpoint 对应可重放的一致状态。
