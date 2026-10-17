package com.sinrotic.rs.agent.service.impl;

import com.sinrotic.rs.agent.domain.session.AgentSessionEvent;
import com.sinrotic.rs.agent.domain.session.AgentTranscriptCheckpoint;
import com.sinrotic.rs.agent.domain.session.AgentTranscriptEntry;
import com.sinrotic.rs.agent.service.AgentSessionProjectionStore;

public class NoopAgentSessionProjectionStore implements AgentSessionProjectionStore {

    @Override
    public void recordSessionEvent(AgentSessionEvent event) {
    }

    @Override
    public void recordTranscriptEntry(AgentTranscriptEntry entry) {
    }

    @Override
    public void recordCheckpoint(AgentTranscriptCheckpoint checkpoint) {
    }
}
