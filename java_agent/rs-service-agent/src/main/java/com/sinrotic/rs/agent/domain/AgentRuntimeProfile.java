package com.sinrotic.rs.agent.domain;

import java.util.List;

public record AgentRuntimeProfile(
        String id,
        String modelRef,
        String systemPromptRef,
        List<String> allowedCapabilities,
        List<AgentPublicOutputBlock> allowedOutputBlocks,
        int maxLoops,
        AgentProfileFailurePolicy failurePolicy
) {

    public AgentRuntimeProfile {
        id = requireText(id, "id");
        modelRef = requireText(modelRef, "modelRef");
        systemPromptRef = requireText(systemPromptRef, "systemPromptRef");
        if (allowedCapabilities == null || allowedCapabilities.isEmpty()) {
            throw new IllegalArgumentException("agent profile allowedCapabilities must not be empty");
        }
        if (allowedOutputBlocks == null || allowedOutputBlocks.isEmpty()) {
            throw new IllegalArgumentException("agent profile allowedOutputBlocks must not be empty");
        }
        if (failurePolicy == null) {
            throw new IllegalArgumentException("agent profile failurePolicy must not be null");
        }
        allowedCapabilities = List.copyOf(allowedCapabilities);
        allowedOutputBlocks = List.copyOf(allowedOutputBlocks);
        if (maxLoops <= 0) {
            throw new IllegalArgumentException("agent profile maxLoops must be positive");
        }
    }

    private static String requireText(String value, String field) {
        if (value == null || value.isBlank()) {
            throw new IllegalArgumentException("agent profile " + field + " must not be blank");
        }
        return value;
    }
}
