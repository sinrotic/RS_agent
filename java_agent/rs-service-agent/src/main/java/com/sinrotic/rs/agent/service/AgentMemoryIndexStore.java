package com.sinrotic.rs.agent.service;

import com.sinrotic.rs.agent.domain.memory.AgentMemoryIndexSnapshot;

import java.util.Optional;

public interface AgentMemoryIndexStore {

    void save(AgentMemoryIndexSnapshot snapshot);

    Optional<AgentMemoryIndexSnapshot> find(String tenantId, String profileUserId);
}
