package com.sinrotic.rs.agent.service.impl;

import com.sinrotic.rs.agent.domain.session.AgentSessionEvent;
import com.sinrotic.rs.agent.domain.session.AgentSessionSnapshot;
import com.sinrotic.rs.agent.service.AgentColdSessionArchiveStore;
import com.sinrotic.rs.agent.service.AgentHotSessionStore;
import com.sinrotic.rs.agent.service.AgentSessionCompactionService;
import org.springframework.stereotype.Service;

import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.UUID;

@Service
public class DefaultAgentSessionCompactionService implements AgentSessionCompactionService {

    private final AgentHotSessionStore hotStore;

    private final AgentColdSessionArchiveStore archiveStore;

    public DefaultAgentSessionCompactionService(
            AgentHotSessionStore hotStore,
            AgentColdSessionArchiveStore archiveStore
    ) {
        this.hotStore = hotStore;
        this.archiveStore = archiveStore;
    }

    @Override
    public AgentSessionSnapshot compactBeforeMark(
            String sessionId,
            String compactionId,
            String compactBeforeEventId,
            Map<String, Object> summaryPayload
    ) {
        List<AgentSessionEvent> hotEvents = hotStore.events(sessionId);
        int boundaryIndex = boundaryIndex(hotEvents, compactBeforeEventId);
        List<AgentSessionEvent> archivedEvents = List.copyOf(hotEvents.subList(0, boundaryIndex + 1));
        AgentSessionSnapshot snapshot = new AgentSessionSnapshot(
                "snap_" + UUID.randomUUID().toString().substring(0, 8),
                sessionId,
                compactionId,
                compactBeforeEventId,
                archivedEvents.size(),
                sourceTokenCount(archivedEvents),
                summaryPayload,
                Instant.now()
        );

        archiveStore.archiveEvents(archivedEvents);
        archiveStore.archiveSnapshot(snapshot);
        hotStore.storeSnapshot(snapshot);
        hotStore.replaceEvents(sessionId, retainedHotEvents(hotEvents, boundaryIndex));
        return snapshot;
    }

    private int boundaryIndex(List<AgentSessionEvent> events, String compactBeforeEventId) {
        for (int index = 0; index < events.size(); index++) {
            if (events.get(index).eventId().equals(compactBeforeEventId)) {
                return index;
            }
        }
        throw new IllegalArgumentException("compact boundary event not found: " + compactBeforeEventId);
    }

    private List<AgentSessionEvent> retainedHotEvents(List<AgentSessionEvent> events, int boundaryIndex) {
        List<AgentSessionEvent> retained = new ArrayList<>();
        for (int index = boundaryIndex + 1; index < events.size(); index++) {
            AgentSessionEvent event = events.get(index);
            if (!"COMPACTION_MARK".equals(event.eventType())) {
                retained.add(event);
            }
        }
        return retained;
    }

    private int sourceTokenCount(List<AgentSessionEvent> events) {
        return events.stream()
                .map(AgentSessionEvent::payload)
                .map(payload -> payload.get("token_count"))
                .filter(Number.class::isInstance)
                .map(Number.class::cast)
                .mapToInt(Number::intValue)
                .sum();
    }
}
