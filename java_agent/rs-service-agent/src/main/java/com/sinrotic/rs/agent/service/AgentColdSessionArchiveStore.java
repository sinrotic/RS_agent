package com.sinrotic.rs.agent.service;

import com.sinrotic.rs.agent.domain.session.AgentSessionEvent;
import com.sinrotic.rs.agent.domain.session.AgentSessionSnapshot;

import java.util.List;

public interface AgentColdSessionArchiveStore {

    void archiveEvents(List<AgentSessionEvent> events);

    void archiveSnapshot(AgentSessionSnapshot snapshot);

    List<AgentSessionEvent> events(String sessionId);

    List<AgentSessionSnapshot> snapshots(String sessionId);
}
