package com.sinrotic.rs.agent.service;

import com.sinrotic.rs.agent.domain.session.AgentSessionEvent;
import com.sinrotic.rs.agent.domain.session.AgentSessionSnapshot;
import com.sinrotic.rs.agent.service.impl.DefaultAgentSessionCompactionService;
import com.sinrotic.rs.agent.service.impl.InMemoryAgentColdSessionArchiveStore;
import com.sinrotic.rs.agent.service.impl.InMemoryAgentHotSessionStore;
import org.junit.jupiter.api.Test;

import java.time.Instant;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;

class AgentSessionCompactionServiceTest {

    @Test
    void compactsEventsBeforeMarkIntoColdArchiveAndKeepsSnapshotPlusEventsAfterMarkHot() {
        InMemoryAgentHotSessionStore hotStore = new InMemoryAgentHotSessionStore();
        InMemoryAgentColdSessionArchiveStore archiveStore = new InMemoryAgentColdSessionArchiveStore();
        DefaultAgentSessionCompactionService service = new DefaultAgentSessionCompactionService(hotStore, archiveStore);

        hotStore.append(event("evt_001", "sess_001", "USER_MESSAGE", "", Map.of("token_count", 12)));
        hotStore.append(event("evt_002", "sess_001", "TOOL_USE", "toolu_001", Map.of("token_count", 8)));
        hotStore.append(event("evt_003", "sess_001", "COMPACTION_MARK", "", Map.of("compaction_id", "cmp_001")));
        hotStore.append(event("evt_004", "sess_001", "USER_MESSAGE", "", Map.of("token_count", 5)));

        AgentSessionSnapshot snapshot = service.compactBeforeMark(
                "sess_001",
                "cmp_001",
                "evt_002",
                Map.of(
                        "summary", "用户正在挑选蓝牙耳机，关注降噪和通勤。",
                        "preferences", Map.of("category", "bluetooth_earbuds")
                )
        );

        assertThat(archiveStore.events("sess_001"))
                .extracting(AgentSessionEvent::eventId)
                .containsExactly("evt_001", "evt_002");
        assertThat(archiveStore.snapshots("sess_001"))
                .extracting(AgentSessionSnapshot::snapshotId)
                .containsExactly(snapshot.snapshotId());
        assertThat(snapshot.compactionId()).isEqualTo("cmp_001");
        assertThat(snapshot.compactBeforeEventId()).isEqualTo("evt_002");
        assertThat(snapshot.sourceEventCount()).isEqualTo(2);
        assertThat(snapshot.sourceTokenCount()).isEqualTo(20);
        assertThat(snapshot.summaryPayload()).containsEntry("summary", "用户正在挑选蓝牙耳机，关注降噪和通勤。");

        assertThat(hotStore.events("sess_001"))
                .extracting(AgentSessionEvent::eventId)
                .containsExactly("evt_004");
        assertThat(hotStore.latestSnapshot("sess_001"))
                .hasValueSatisfying(hotSnapshot -> assertThat(hotSnapshot.snapshotId()).isEqualTo(snapshot.snapshotId()));
    }

    private AgentSessionEvent event(
            String eventId,
            String sessionId,
            String eventType,
            String toolCallId,
            Map<String, Object> payload
    ) {
        return new AgentSessionEvent(
                eventId,
                sessionId,
                "agent_req_001",
                eventType,
                0,
                toolCallId,
                payload,
                "",
                "",
                Instant.parse("2026-06-30T10:00:00Z")
        );
    }
}
