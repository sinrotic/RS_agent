package com.sinrotic.rs.agent.domain.memory;

import java.time.Instant;
import java.util.Map;

public record AgentMemoryItem(
        String tenantId,
        String profileUserId,
        String memoryId,
        String type,
        String name,
        String summary,
        String confidence,
        int importance,
        String status,
        String content,
        String sourceSessionId,
        Map<String, Object> metadata,
        int version,
        String contentHash,
        Instant updatedAt
) {

    public AgentMemoryItem {
        tenantId = tenantId == null ? "" : tenantId;
        profileUserId = profileUserId == null ? "" : profileUserId;
        memoryId = memoryId == null ? "" : memoryId;
        type = type == null ? "" : type;
        name = name == null ? "" : name;
        summary = summary == null ? "" : summary;
        confidence = confidence == null ? "" : confidence;
        status = status == null ? "" : status;
        content = content == null ? "" : content;
        sourceSessionId = sourceSessionId == null ? "" : sourceSessionId;
        metadata = metadata == null ? Map.of() : Map.copyOf(metadata);
        contentHash = contentHash == null ? "" : contentHash;
        updatedAt = updatedAt == null ? Instant.EPOCH : updatedAt;
    }
}
