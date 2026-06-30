package com.sinrotic.rs.agent.service.impl;

import com.sinrotic.rs.agent.domain.session.AgentSessionEvent;
import com.sinrotic.rs.agent.domain.session.AgentSessionSnapshot;
import com.sinrotic.rs.agent.service.AgentHotSessionStore;
import org.springframework.stereotype.Service;

import java.util.ArrayList;
import java.util.List;
import java.util.Optional;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ConcurrentMap;

@Service
public class InMemoryAgentHotSessionStore implements AgentHotSessionStore {

    private final ConcurrentMap<String, List<AgentSessionEvent>> events = new ConcurrentHashMap<>();

    private final ConcurrentMap<String, AgentSessionSnapshot> snapshots = new ConcurrentHashMap<>();

    @Override
    public void append(AgentSessionEvent event) {
        events.compute(event.sessionId(), (sessionId, current) -> {
            List<AgentSessionEvent> next = current == null ? new ArrayList<>() : new ArrayList<>(current);
            next.add(event);
            return next;
        });
    }

    @Override
    public List<AgentSessionEvent> events(String sessionId) {
        return List.copyOf(events.getOrDefault(sessionId, List.of()));
    }

    @Override
    public void replaceEvents(String sessionId, List<AgentSessionEvent> replacement) {
        events.put(sessionId, List.copyOf(replacement == null ? List.of() : replacement));
    }

    @Override
    public void storeSnapshot(AgentSessionSnapshot snapshot) {
        snapshots.put(snapshot.sessionId(), snapshot);
    }

    @Override
    public Optional<AgentSessionSnapshot> latestSnapshot(String sessionId) {
        return Optional.ofNullable(snapshots.get(sessionId));
    }
}
