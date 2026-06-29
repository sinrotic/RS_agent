package com.sinrotic.rs.agent.service.impl;

import com.sinrotic.rs.agent.domain.dto.AgentChatRequestDTO;
import com.sinrotic.rs.agent.service.AgentModelStreamClient;

import java.util.function.Consumer;

public class MockAgentModelStreamClient implements AgentModelStreamClient {

    @Override
    public void streamAssistantEvents(
            String requestId,
            AgentChatRequestDTO request,
            Consumer<AgentModelStreamEvent> consumer
    ) {
        consumer.accept(AgentModelStreamEvent.token("I "));
        consumer.accept(AgentModelStreamEvent.token("will "));
        consumer.accept(AgentModelStreamEvent.token("prioritize commuter backpack recommendations."));
        consumer.accept(AgentModelStreamEvent.done());
    }
}
