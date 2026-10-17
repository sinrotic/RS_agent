package com.sinrotic.rs.agent.service;

import com.sinrotic.rs.agent.domain.dto.AgentChatRequestDTO;
import com.sinrotic.rs.agent.service.impl.AgentModelStreamEvent;
import com.sinrotic.rs.agent.service.impl.AgentInterruptContext;

import java.util.ArrayList;
import java.util.List;
import java.util.function.Consumer;

public interface AgentModelStreamClient {

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
}
