package com.sinrotic.rs.agent.service.impl;

import com.sinrotic.rs.agent.domain.session.AgentSessionEvent;
import com.sinrotic.rs.agent.service.AgentColdSessionArchiveStore;
import com.sinrotic.rs.agent.service.AgentHotSessionStore;
import com.sinrotic.rs.agent.service.AgentSessionExpirationArchiveService;
import org.springframework.stereotype.Service;

import java.util.List;

@Service
public class DefaultAgentSessionExpirationArchiveService implements AgentSessionExpirationArchiveService {

    private final AgentHotSessionStore hotStore;

    private final AgentColdSessionArchiveStore archiveStore;

    public DefaultAgentSessionExpirationArchiveService(
            AgentHotSessionStore hotStore,
            AgentColdSessionArchiveStore archiveStore
    ) {
        this.hotStore = hotStore;
        this.archiveStore = archiveStore;
    }

    @Override
    public void archiveExpiredSession(String sessionId) {
        List<AgentSessionEvent> hotEvents = hotStore.events(sessionId);
        if (hotEvents.isEmpty()) {
            return;
        }
        archiveStore.archiveEvents(hotEvents);
        hotStore.replaceEvents(sessionId, List.of());
    }
}
