package com.sinrotic.rs.agent.service;

import com.sinrotic.rs.agent.domain.session.AgentSessionEvent;
import com.sinrotic.rs.agent.service.impl.DefaultAgentSessionExpirationArchiveService;
import com.sinrotic.rs.agent.service.impl.InMemoryAgentColdSessionArchiveStore;
import com.sinrotic.rs.agent.service.impl.InMemoryAgentHotSessionStore;
import com.sinrotic.rs.agent.service.impl.RedisAgentSessionTtlExpirationListener;
import org.junit.jupiter.api.Test;

import java.time.Instant;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;

class AgentSessionExpirationArchiveServiceTest {

    @Test
    void archivesHotSessionEventsAndClearsHotStoreWhenSessionTtlMarkerExpires() {
        InMemoryAgentHotSessionStore hotStore = new InMemoryAgentHotSessionStore();
        InMemoryAgentColdSessionArchiveStore archiveStore = new InMemoryAgentColdSessionArchiveStore();
        DefaultAgentSessionExpirationArchiveService service = new DefaultAgentSessionExpirationArchiveService(
                hotStore,
                archiveStore
        );
        hotStore.append(event("evt_001", "sess_001", "USER_MESSAGE"));
        hotStore.append(event("evt_002", "sess_001", "ASSISTANT_MESSAGE"));

        service.archiveExpiredSession("sess_001");

        assertThat(archiveStore.events("sess_001"))
                .extracting(AgentSessionEvent::eventId)
                .containsExactly("evt_001", "evt_002");
        assertThat(hotStore.events("sess_001")).isEmpty();
    }

    @Test
    void redisExpirationListenerParsesOnlySessionTtlMarkerKeys() {
        assertThat(RedisAgentSessionTtlExpirationListener.sessionIdFromExpiredKey("agent:session:sess_001:ttl"))
                .hasValue("sess_001");
        assertThat(RedisAgentSessionTtlExpirationListener.sessionIdFromExpiredKey("agent:session:sess_001:data"))
                .isEmpty();
        assertThat(RedisAgentSessionTtlExpirationListener.sessionIdFromExpiredKey("agent:result:sess_001:toolu_001:meta"))
                .isEmpty();
    }

    private AgentSessionEvent event(String eventId, String sessionId, String eventType) {
        return new AgentSessionEvent(
                eventId,
                sessionId,
                "agent_req_001",
                eventType,
                0,
                "",
                Map.of(),
                "",
                "",
                Instant.parse("2026-07-07T00:00:00Z")
        );
    }
}
