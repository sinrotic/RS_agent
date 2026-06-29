package com.sinrotic.rs.agent.service;

import com.sinrotic.rs.agent.service.impl.AgentModelStreamEvent;

import java.util.Map;
import java.util.concurrent.CompletableFuture;

public interface AgentToolUseExecutor {

    CompletableFuture<Map<String, Object>> execute(AgentModelStreamEvent event);
}
