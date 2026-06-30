package com.sinrotic.rs.agent.service;

import com.sinrotic.rs.agent.domain.session.AgentSessionSnapshot;

import java.util.Map;

public interface AgentSessionCompactionService {

    AgentSessionSnapshot compactBeforeMark(
            String sessionId,
            String compactionId,
            String compactBeforeEventId,
            Map<String, Object> summaryPayload
    );
}
