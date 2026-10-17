package com.sinrotic.rs.agent.service;

import com.sinrotic.rs.agent.service.impl.AgentModelStreamEvent;

import java.util.List;
import java.util.Map;

public interface AgentToolUseOrchestrator {

    Run start();

    interface Run {

        void submit(String toolCallId, AgentModelStreamEvent event);

        void complete(String toolCallId, AgentModelStreamEvent event, Map<String, Object> metadata);

        List<AgentToolUseResult> awaitResults();

        boolean hasSubmittedTools();

        void cancel();
    }
}
