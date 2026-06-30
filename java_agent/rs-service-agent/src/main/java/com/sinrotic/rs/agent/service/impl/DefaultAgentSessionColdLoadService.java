package com.sinrotic.rs.agent.service.impl;

import com.sinrotic.rs.agent.domain.session.AgentSessionEvent;
import com.sinrotic.rs.agent.domain.session.AgentSessionSnapshot;
import com.sinrotic.rs.agent.service.AgentColdSessionArchiveStore;
import com.sinrotic.rs.agent.service.AgentHotSessionStore;
import com.sinrotic.rs.agent.service.AgentSessionColdLoadService;
import org.springframework.stereotype.Service;

import java.util.List;
import java.util.Optional;

@Service
public class DefaultAgentSessionColdLoadService implements AgentSessionColdLoadService {

    private final AgentHotSessionStore hotStore;

    private final AgentColdSessionArchiveStore archiveStore;

    public DefaultAgentSessionColdLoadService(
            AgentHotSessionStore hotStore,
            AgentColdSessionArchiveStore archiveStore
    ) {
        this.hotStore = hotStore;
        this.archiveStore = archiveStore;
    }

    @Override
    public Optional<AgentSessionSnapshot> coldLoad(String sessionId) {
        Optional<AgentSessionSnapshot> snapshot = latestSnapshot(sessionId);
        if (snapshot.isEmpty()) {
            return Optional.empty();
        }
        AgentSessionSnapshot latest = snapshot.get();
        hotStore.storeSnapshot(latest);
        hotStore.replaceEvents(sessionId, eventsAfterBoundary(sessionId, latest.compactBeforeEventId()));
        return snapshot;
    }

    private Optional<AgentSessionSnapshot> latestSnapshot(String sessionId) {
        List<AgentSessionSnapshot> snapshots = archiveStore.snapshots(sessionId);
        if (snapshots.isEmpty()) {
            return Optional.empty();
        }
        return Optional.of(snapshots.get(snapshots.size() - 1));
    }

    private List<AgentSessionEvent> eventsAfterBoundary(String sessionId, String compactBeforeEventId) {
        List<AgentSessionEvent> events = archiveStore.events(sessionId);
        int boundary = -1;
        for (int index = 0; index < events.size(); index++) {
            if (events.get(index).eventId().equals(compactBeforeEventId)) {
                boundary = index;
            }
        }
        if (boundary < 0 || boundary + 1 >= events.size()) {
            return List.of();
        }
        return List.copyOf(events.subList(boundary + 1, events.size()));
    }
}
