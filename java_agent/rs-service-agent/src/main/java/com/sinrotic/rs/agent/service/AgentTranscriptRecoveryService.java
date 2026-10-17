package com.sinrotic.rs.agent.service;

import com.sinrotic.rs.agent.domain.session.AgentRecoveredTranscript;
import com.sinrotic.rs.agent.domain.session.AgentTranscriptEntry;
import java.util.List;

public interface AgentTranscriptRecoveryService {

    AgentRecoveredTranscript recover(String sessionId);

    /** Reuses a full authoritative transcript read within the current Session Execution Lane. */
    default AgentRecoveredTranscript recover(String sessionId, List<AgentTranscriptEntry> transcript) {
        return recover(sessionId);
    }
}
