package com.sinrotic.rs.agent.service;

import com.sinrotic.rs.agent.domain.session.AgentTranscriptCheckpoint;

import java.util.Optional;

public interface AgentTranscriptCheckpointStore {

    void save(AgentTranscriptCheckpoint checkpoint);

    Optional<AgentTranscriptCheckpoint> latest(String sessionId);
}
