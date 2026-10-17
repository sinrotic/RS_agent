package com.sinrotic.rs.agent.service;

import com.sinrotic.rs.agent.domain.session.AgentTranscriptEntry;

import java.util.List;
import java.util.Optional;

public interface AgentTranscriptEntryStore {

    void append(AgentTranscriptEntry entry);

    Optional<AgentTranscriptEntry> latest(String sessionId);

    List<AgentTranscriptEntry> tailAfter(String sessionId, long exclusiveSeq);
}
