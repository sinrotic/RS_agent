package com.sinrotic.rs.agent.service;

import com.sinrotic.rs.agent.domain.session.AgentSessionEvent;
import com.sinrotic.rs.agent.domain.session.AgentSessionSnapshot;
import com.sinrotic.rs.agent.service.impl.DefaultAgentSessionColdLoadService;
import com.sinrotic.rs.agent.service.impl.InMemoryAgentColdSessionArchiveStore;
import com.sinrotic.rs.agent.service.impl.InMemoryAgentHotSessionStore;
import org.junit.jupiter.api.Test;

import java.time.Instant;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;

class AgentSessionColdLoadServiceTest {

    @Test
    void restoresLatestSnapshotAndOnlyEventsAfterSnapshotBoundaryIntoHotStore() {
        InMemoryAgentHotSessionStore hotStore = new InMemoryAgentHotSessionStore();
        InMemoryAgentColdSessionArchiveStore archiveStore = new InMemoryAgentColdSessionArchiveStore();
        DefaultAgentSessionColdLoadService service = new DefaultAgentSessionColdLoadService(hotStore, archiveStore);

        archiveStore.archiveEvents(List.of(
                event("evt_001", "sess_001", "USER_MESSAGE"),
                event("evt_002", "sess_001", "ASSISTANT_MESSAGE"),
                event("evt_003", "sess_001", "TOOL_USE"),
                event("evt_004", "sess_001", "TOOL_RESULT")
        ));
        AgentSessionSnapshot snapshot = new AgentSessionSnapshot(
                "snap_001",
                "sess_001",
                "cmp_001",
                "evt_002",
                2,
                30,
                Map.of("summary", "用户正在挑选蓝牙耳机。"),
                Instant.parse("2026-06-30T10:00:10Z")
        );
        archiveStore.archiveSnapshot(snapshot);

        service.coldLoad("sess_001");

        assertThat(hotStore.latestSnapshot("sess_001"))
                .hasValueSatisfying(hotSnapshot -> assertThat(hotSnapshot.snapshotId()).isEqualTo("snap_001"));
        assertThat(hotStore.events("sess_001"))
                .extracting(AgentSessionEvent::eventId)
                .containsExactly("evt_003", "evt_004");
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
                Instant.parse("2026-06-30T10:00:00Z")
        );
    }
}
