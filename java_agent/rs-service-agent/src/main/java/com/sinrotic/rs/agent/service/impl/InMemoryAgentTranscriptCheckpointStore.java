package com.sinrotic.rs.agent.service.impl;

import com.sinrotic.rs.agent.domain.session.AgentTranscriptCheckpoint;
import com.sinrotic.rs.agent.service.AgentTranscriptCheckpointStore;

import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import java.util.Optional;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ConcurrentMap;

public class InMemoryAgentTranscriptCheckpointStore implements AgentTranscriptCheckpointStore {

    private final ConcurrentMap<String, List<AgentTranscriptCheckpoint>> checkpoints = new ConcurrentHashMap<>();

    @Override
    public void save(AgentTranscriptCheckpoint checkpoint) {
        checkpoints.compute(checkpoint.sessionId(), (sessionId, current) -> {
            List<AgentTranscriptCheckpoint> next = current == null ? new ArrayList<>() : new ArrayList<>(current);
            next.add(checkpoint);
            return next;
        });
    }

    @Override
    public Optional<AgentTranscriptCheckpoint> latest(String sessionId) {
        return checkpoints.getOrDefault(sessionId, List.of()).stream()
                .max(Comparator
                        .comparingLong(AgentTranscriptCheckpoint::checkpointSeq)
                        .thenComparing(AgentTranscriptCheckpoint::createdAt));
    }
}
