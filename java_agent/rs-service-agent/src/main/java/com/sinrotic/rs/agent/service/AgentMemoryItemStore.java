package com.sinrotic.rs.agent.service;

import com.sinrotic.rs.agent.domain.memory.AgentMemoryItem;

import java.util.Optional;

public interface AgentMemoryItemStore {

    void save(AgentMemoryItem item);

    Optional<AgentMemoryItem> findById(String tenantId, String profileUserId, String memoryId);
}
