package com.sinrotic.rs.agent.service.impl;

import com.sinrotic.rs.agent.domain.AgentCapabilityDescriptor;
import com.sinrotic.rs.agent.domain.AgentCapabilityRequest;
import com.sinrotic.rs.agent.domain.AgentCapabilityResult;
import com.sinrotic.rs.agent.domain.session.AgentSessionEvent;
import com.sinrotic.rs.agent.service.AgentCapability;
import com.sinrotic.rs.agent.service.AgentCapabilityDefinitions;
import com.sinrotic.rs.agent.service.AgentHotSessionStore;

import java.util.List;
import java.util.Map;

public class AgentSessionMemoryCapability implements AgentCapability {

    private final AgentHotSessionStore hotSessionStore;

    public AgentSessionMemoryCapability(AgentHotSessionStore hotSessionStore) {
        this.hotSessionStore = hotSessionStore;
    }

    @Override
    public AgentCapabilityDescriptor descriptor() {
        return AgentCapabilityDefinitions.byId("session-memory");
    }

    @Override
    public AgentCapabilityResult execute(AgentCapabilityRequest request) {
        Object sessionIdValue = request.arguments().get("session_id");
        if (!(sessionIdValue instanceof String sessionId) || sessionId.isBlank()) {
            return AgentCapabilityResult.failure(descriptor().id(), "INVALID_ARGUMENTS", "session_id is required");
        }
        List<AgentSessionEvent> events = hotSessionStore.events(sessionId);
        return AgentCapabilityResult.success(descriptor().id(), Map.of(
                "session_id", sessionId,
                "event_count", events.size(),
                "events", events
        ));
    }
}
