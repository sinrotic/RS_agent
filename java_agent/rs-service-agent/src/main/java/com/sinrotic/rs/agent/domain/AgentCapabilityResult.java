package com.sinrotic.rs.agent.domain;

import java.util.Map;
import java.util.Objects;

public record AgentCapabilityResult(
        String capabilityId,
        String status,
        Map<String, Object> payload,
        String errorCode,
        String errorMessage
) {

    public AgentCapabilityResult {
        if (capabilityId == null || capabilityId.isBlank()) {
            throw new IllegalArgumentException("capability id must not be blank");
        }
        if (status == null || status.isBlank()) {
            throw new IllegalArgumentException("capability status must not be blank");
        }
        payload = Map.copyOf(Objects.requireNonNull(payload, "payload must not be null"));
    }

    public static AgentCapabilityResult success(String capabilityId, Map<String, Object> payload) {
        return new AgentCapabilityResult(capabilityId, "SUCCESS", payload, "", "");
    }

    public static AgentCapabilityResult failure(String capabilityId, String errorCode, String errorMessage) {
        return new AgentCapabilityResult(capabilityId, "FAILED", Map.of(), errorCode, errorMessage);
    }
}
