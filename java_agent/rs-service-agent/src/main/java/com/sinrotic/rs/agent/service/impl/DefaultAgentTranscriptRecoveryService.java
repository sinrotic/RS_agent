package com.sinrotic.rs.agent.service.impl;

import com.sinrotic.rs.agent.domain.session.AgentRecoveredTranscript;
import com.sinrotic.rs.agent.domain.session.AgentTranscriptCheckpoint;
import com.sinrotic.rs.agent.service.AgentTranscriptCheckpointStore;
import com.sinrotic.rs.agent.service.AgentTranscriptEntryStore;
import com.sinrotic.rs.agent.service.AgentTranscriptRecoveryService;

import java.util.List;
import java.util.Optional;

public class DefaultAgentTranscriptRecoveryService implements AgentTranscriptRecoveryService {

    private final AgentTranscriptCheckpointStore checkpointStore;

    private final AgentTranscriptEntryStore entryStore;

    public DefaultAgentTranscriptRecoveryService(
            AgentTranscriptCheckpointStore checkpointStore,
            AgentTranscriptEntryStore entryStore
    ) {
        this.checkpointStore = checkpointStore;
        this.entryStore = entryStore;
    }

    @Override
    public AgentRecoveredTranscript recover(String sessionId) {
        return recover(sessionId, null);
    }

    @Override
    public AgentRecoveredTranscript recover(String sessionId,
            List<com.sinrotic.rs.agent.domain.session.AgentTranscriptEntry> transcript) {
        Optional<AgentTranscriptCheckpoint> checkpoint = checkpointStore.latest(sessionId);
        long checkpointSeq = checkpoint
                .map(AgentTranscriptCheckpoint::checkpointSeq)
                .orElse(0L);
        return new AgentRecoveredTranscript(
                sessionId,
                checkpoint.map(AgentTranscriptCheckpoint::checkpointId).orElse(""),
                checkpointSeq,
                checkpoint.map(AgentTranscriptCheckpoint::summaryMessages).orElse(List.of()),
                checkpoint.map(AgentTranscriptCheckpoint::preservedEntries).orElse(List.of()),
                transcript == null ? entryStore.tailAfter(sessionId, checkpointSeq)
                        : transcript.stream().filter(entry -> entry.seq() > checkpointSeq).toList()
        );
    }
}
