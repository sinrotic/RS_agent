package com.sinrotic.rs.agent.service;

import com.sinrotic.rs.agent.domain.dto.AgentChatRequestDTO;
import com.sinrotic.rs.agent.service.impl.AgentModelStreamEvent;
import com.sinrotic.rs.agent.service.impl.AgentInterruptContext;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.function.Consumer;

public interface AgentModelStreamClient {

    default com.sinrotic.rs.agent.service.impl.AgentReasoningPolicy reasoningPolicy() {
        return com.sinrotic.rs.agent.service.impl.AgentReasoningPolicy.disabled();
    }

    void streamAssistantEvents(
            String requestId,
            AgentChatRequestDTO request,
            Consumer<AgentModelStreamEvent> consumer
    );

    default void streamAssistantEvents(
            String requestId,
            AgentChatRequestDTO request,
            Consumer<AgentModelStreamEvent> consumer,
            AgentInterruptContext interruptContext
    ) {
        streamAssistantEvents(requestId, request, consumer);
    }

    default List<String> streamAssistantDeltas(String requestId, AgentChatRequestDTO request) {
        List<String> deltas = new ArrayList<>();
        streamAssistantEvents(requestId, request, event -> {
            if (event.isToken() && !event.delta().isBlank()) {
                deltas.add(event.delta());
            }
        });
        return deltas;
    }

    /** 请求组装处提供观测摘要；旧 Adapter 保持兼容，未报告的版本保持未知。 */
    default void streamAssistantEvents(String requestId, AgentChatRequestDTO request,
            Consumer<AgentModelStreamEvent> consumer, AgentInterruptContext interruptContext,
            Consumer<Map<String, Object>> requestObservation) {
        streamAssistantEvents(requestId, request, consumer, interruptContext);
    }
}
