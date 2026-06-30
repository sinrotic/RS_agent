package com.sinrotic.rs.agent.service;

import com.sinrotic.rs.agent.domain.session.AgentSessionEvent;
import com.sinrotic.rs.agent.domain.session.AgentSessionSnapshot;

import java.util.List;
import java.util.Optional;

public interface AgentHotSessionStore {

    void append(AgentSessionEvent event);

    List<AgentSessionEvent> events(String sessionId);

    void replaceEvents(String sessionId, List<AgentSessionEvent> events);

    void storeSnapshot(AgentSessionSnapshot snapshot);

    Optional<AgentSessionSnapshot> latestSnapshot(String sessionId);
}
