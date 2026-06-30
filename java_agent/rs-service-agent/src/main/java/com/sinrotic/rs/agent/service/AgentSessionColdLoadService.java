package com.sinrotic.rs.agent.service;

import com.sinrotic.rs.agent.domain.session.AgentSessionSnapshot;

import java.util.Optional;

public interface AgentSessionColdLoadService {

    Optional<AgentSessionSnapshot> coldLoad(String sessionId);
}
