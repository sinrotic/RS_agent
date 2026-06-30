package com.sinrotic.rs.agent.service.impl;

import com.sinrotic.rs.agent.domain.session.AgentSessionEvent;
import com.sinrotic.rs.agent.domain.session.AgentSessionSnapshot;
import com.sinrotic.rs.agent.service.AgentColdSessionArchiveStore;
import org.springframework.stereotype.Service;

import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ConcurrentMap;

@Service
public class InMemoryAgentColdSessionArchiveStore implements AgentColdSessionArchiveStore {

    private final ConcurrentMap<String, List<AgentSessionEvent>> events = new ConcurrentHashMap<>();

    private final ConcurrentMap<String, List<AgentSessionSnapshot>> snapshots = new ConcurrentHashMap<>();

    @Override
    public void archiveEvents(List<AgentSessionEvent> archivedEvents) {
        for (AgentSessionEvent event : archivedEvents == null ? List.<AgentSessionEvent>of() : archivedEvents) {
            events.compute(event.sessionId(), (sessionId, current) -> {
                List<AgentSessionEvent> next = current == null ? new ArrayList<>() : new ArrayList<>(current);
                next.add(event);
                return next;
            });
        }
    }

    @Override
    public void archiveSnapshot(AgentSessionSnapshot snapshot) {
        snapshots.compute(snapshot.sessionId(), (sessionId, current) -> {
            List<AgentSessionSnapshot> next = current == null ? new ArrayList<>() : new ArrayList<>(current);
            next.add(snapshot);
            return next;
        });
    }

    @Override
    public List<AgentSessionEvent> events(String sessionId) {
        return List.copyOf(events.getOrDefault(sessionId, List.of()));
    }

    @Override
    public List<AgentSessionSnapshot> snapshots(String sessionId) {
        return List.copyOf(snapshots.getOrDefault(sessionId, List.of()));
    }
}
