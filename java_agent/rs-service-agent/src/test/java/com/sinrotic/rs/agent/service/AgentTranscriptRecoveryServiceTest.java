package com.sinrotic.rs.agent.service;

import com.sinrotic.rs.agent.domain.session.AgentRecoveredTranscript;
import com.sinrotic.rs.agent.domain.session.AgentTranscriptCheckpoint;
import com.sinrotic.rs.agent.domain.session.AgentTranscriptEntry;
import com.sinrotic.rs.agent.service.impl.DefaultAgentTranscriptRecoveryService;
import com.sinrotic.rs.agent.service.impl.InMemoryAgentTranscriptCheckpointStore;
import com.sinrotic.rs.agent.service.impl.InMemoryAgentTranscriptEntryStore;
import org.junit.jupiter.api.Test;

import java.time.Instant;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;

class AgentTranscriptRecoveryServiceTest {

    @Test
    void reusedAuthoritativeTranscriptKeepsCheckpointBoundaryWithoutAnotherTailRead() {
        var checkpoints = new InMemoryAgentTranscriptCheckpointStore();
        var entries = org.mockito.Mockito.spy(new InMemoryAgentTranscriptEntryStore());
        checkpoints.save(new AgentTranscriptCheckpoint("checkpoint", "sess_001", 2L,
                List.of(Map.of("role", "system", "content", "summary")),
                List.of(Map.of("role", "assistant", "content", "preserved")), 2, 80, Instant.EPOCH));
        var full = List.of(entry(1, 1, 0, "USER_MESSAGE", "user", "old"),
                entry(2, 1, 1, "ASSISTANT_FINAL", "assistant", "boundary"),
                entry(3, 2, 0, "USER_MESSAGE", "user", "new"));
        var recovered = new DefaultAgentTranscriptRecoveryService(checkpoints, entries).recover("sess_001", full);
        assertThat(recovered.checkpointSeq()).isEqualTo(2L);
        assertThat(recovered.summaryMessages()).hasSize(1);
        assertThat(recovered.preservedEntries()).hasSize(1);
        assertThat(recovered.tailEntries()).containsExactly(full.getLast());
        org.mockito.Mockito.verifyNoInteractions(entries);
    }

    @Test
    void recoversCheckpointSummaryAndOnlyTailEntriesAfterCheckpointSeqInStableOrder() {
        InMemoryAgentTranscriptCheckpointStore checkpointStore = new InMemoryAgentTranscriptCheckpointStore();
        InMemoryAgentTranscriptEntryStore entryStore = new InMemoryAgentTranscriptEntryStore();
        DefaultAgentTranscriptRecoveryService service = new DefaultAgentTranscriptRecoveryService(
                checkpointStore,
                entryStore
        );
        List<Map<String, Object>> summaryMessages = List.of(
                Map.<String, Object>of("role", "system", "content", "user is comparing headphones")
        );
        List<Map<String, Object>> preservedEntries = List.of(
                Map.<String, Object>of("seq", 2L, "assistant_message", "kept verbatim before boundary")
        );

        checkpointStore.save(new AgentTranscriptCheckpoint(
                "cp_001",
                "sess_001",
                2L,
                summaryMessages,
                preservedEntries,
                2,
                80,
                Instant.parse("2026-07-07T00:00:00Z")
        ));
        entryStore.append(entry(1L, 1L, 0, "USER_MESSAGE", "user", "old user"));
        entryStore.append(entry(2L, 1L, 1, "ASSISTANT_MESSAGE", "assistant", "boundary answer"));
        entryStore.append(entry(4L, 2L, 1, "ASSISTANT_MESSAGE", "assistant", "latest answer"));
        entryStore.append(entry(3L, 2L, 0, "USER_MESSAGE", "user", "new user"));

        AgentRecoveredTranscript recovered = service.recover("sess_001");

        assertThat(recovered.sessionId()).isEqualTo("sess_001");
        assertThat(recovered.checkpointId()).isEqualTo("cp_001");
        assertThat(recovered.checkpointSeq()).isEqualTo(2L);
        assertThat(recovered.summaryMessages()).containsExactlyElementsOf(summaryMessages);
        assertThat(recovered.preservedEntries()).containsExactlyElementsOf(preservedEntries);
        assertThat(recovered.tailEntries())
                .extracting(AgentTranscriptEntry::seq)
                .containsExactly(3L, 4L);
    }

    @Test
    void recoversAllEntriesWhenNoCheckpointExists() {
        InMemoryAgentTranscriptCheckpointStore checkpointStore = new InMemoryAgentTranscriptCheckpointStore();
        InMemoryAgentTranscriptEntryStore entryStore = new InMemoryAgentTranscriptEntryStore();
        DefaultAgentTranscriptRecoveryService service = new DefaultAgentTranscriptRecoveryService(
                checkpointStore,
                entryStore
        );

        entryStore.append(entry(2L, 1L, 1, "ASSISTANT_MESSAGE", "assistant", "first answer"));
        entryStore.append(entry(1L, 1L, 0, "USER_MESSAGE", "user", "first user"));

        AgentRecoveredTranscript recovered = service.recover("sess_001");

        assertThat(recovered.checkpointId()).isEmpty();
        assertThat(recovered.checkpointSeq()).isZero();
        assertThat(recovered.summaryMessages()).isEmpty();
        assertThat(recovered.preservedEntries()).isEmpty();
        assertThat(recovered.tailEntries())
                .extracting(AgentTranscriptEntry::seq)
                .containsExactly(1L, 2L);
    }

    private AgentTranscriptEntry entry(long seq, long turnNo, int entryIndex, String entryType, String role, String content) {
        return new AgentTranscriptEntry(
                "sess_001",
                seq,
                turnNo,
                entryIndex,
                "agent_req_" + turnNo,
                entryType,
                role,
                Map.of("content", content),
                Instant.parse("2026-07-07T00:00:00Z").plusSeconds(seq)
        );
    }
}
