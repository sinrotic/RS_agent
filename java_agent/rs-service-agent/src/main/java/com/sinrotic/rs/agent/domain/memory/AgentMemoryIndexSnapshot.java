package com.sinrotic.rs.agent.domain.memory;

import java.time.Instant;

public record AgentMemoryIndexSnapshot(
        String tenantId,
        String profileUserId,
        String indexContent,
        long version,
        int memoryCount,
        String contentHash,
        Instant updatedAt
) {

    public AgentMemoryIndexSnapshot {
        tenantId = tenantId == null ? "" : tenantId;
        profileUserId = profileUserId == null ? "" : profileUserId;
        indexContent = indexContent == null ? "" : indexContent;
        contentHash = contentHash == null ? "" : contentHash;
        updatedAt = updatedAt == null ? Instant.EPOCH : updatedAt;
    }
}
