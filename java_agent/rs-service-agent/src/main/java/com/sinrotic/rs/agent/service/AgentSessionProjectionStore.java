package com.sinrotic.rs.agent.service;

import com.sinrotic.rs.agent.domain.session.AgentSessionEvent;
import com.sinrotic.rs.agent.domain.session.AgentTranscriptCheckpoint;
import com.sinrotic.rs.agent.domain.session.AgentTranscriptEntry;

public interface AgentSessionProjectionStore {

    void recordSessionEvent(AgentSessionEvent event);

    void recordTranscriptEntry(AgentTranscriptEntry entry);

    void recordCheckpoint(AgentTranscriptCheckpoint checkpoint);
}
