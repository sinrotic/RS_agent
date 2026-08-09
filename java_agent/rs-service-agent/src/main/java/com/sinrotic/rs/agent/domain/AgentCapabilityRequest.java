package com.sinrotic.rs.agent.domain;

import java.util.Map;
import java.util.Objects;

public record AgentCapabilityRequest(
        String requestId,
        String profileId,
        String capabilityId,
        Map<String, Object> arguments
) {

    public AgentCapabilityRequest {
        if (requestId == null || requestId.isBlank()) {
            throw new IllegalArgumentException("capability requestId must not be blank");
        }
        if (profileId == null || profileId.isBlank()) {
            throw new IllegalArgumentException("capability profileId must not be blank");
        }
        if (capabilityId == null || capabilityId.isBlank()) {
            throw new IllegalArgumentException("capability id must not be blank");
        }
        arguments = Map.copyOf(Objects.requireNonNull(arguments, "arguments must not be null"));
    }
}
