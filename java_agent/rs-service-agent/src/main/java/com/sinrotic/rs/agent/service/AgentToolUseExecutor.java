package com.sinrotic.rs.agent.service;

import com.sinrotic.rs.agent.service.impl.AgentModelStreamEvent;
import com.sinrotic.rs.agent.service.impl.AgentInterruptContext;

import java.util.Map;
import java.util.concurrent.CompletableFuture;

public interface AgentToolUseExecutor {

    /** 提交后立即返回；阻塞 I/O 在执行器拥有的工作线程中运行。取消需向实际工作任务传播。 */
    CompletableFuture<Map<String, Object>> execute(AgentModelStreamEvent event);

    default Turn openTurn(AgentInterruptContext context) {
        AgentToolUseExecutor owner = this;
        return new Turn() {
            @Override public CompletableFuture<Map<String, Object>> execute(AgentModelStreamEvent event) { return owner.execute(event); }
            @Override public void close() { }
        };
    }

    interface Turn extends AgentToolUseExecutor, AutoCloseable { @Override void close(); }
}
