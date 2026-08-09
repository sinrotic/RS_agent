package com.sinrotic.rs.agent.domain;

import java.util.Map;
import java.util.Objects;

public record AgentCapabilityDescriptor(
        String id,
        String description,
        Map<String, Object> inputSchema,
        boolean replaySafe,
        boolean publicVisible
) {

    public AgentCapabilityDescriptor {
        if (id == null || id.isBlank()) {
            throw new IllegalArgumentException("capability id must not be blank");
        }
        if (description == null || description.isBlank()) {
            throw new IllegalArgumentException("capability description must not be blank");
        }
        inputSchema = Map.copyOf(Objects.requireNonNull(inputSchema, "inputSchema must not be null"));
    }
}
