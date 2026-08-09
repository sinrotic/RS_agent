package com.sinrotic.rs.agent.service.impl;

import com.sinrotic.rs.agent.domain.AgentCapabilityRequest;
import com.sinrotic.rs.agent.domain.AgentCapabilityResult;
import com.sinrotic.rs.agent.domain.AgentRuntimeProfile;
import com.sinrotic.rs.agent.service.AgentCapabilityRegistry;
import com.sinrotic.rs.agent.service.AgentCapabilityToolMapping;
import com.sinrotic.rs.agent.service.AgentRuntimeConfigurationService;
import com.sinrotic.rs.agent.service.AgentToolUseExecutor;

import java.util.LinkedHashMap;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.CompletableFuture;

/**
 * Enforces the server-owned profile allowlist before a model tool call can reach application code.
 */
public final class AgentCapabilityToolUseExecutor implements AgentToolUseExecutor {

    private final AgentToolUseExecutor delegate;

    private final AgentCapabilityRegistry capabilityRegistry;

    private final AgentRuntimeConfigurationService runtimeConfigurationService;

    public AgentCapabilityToolUseExecutor(
            AgentToolUseExecutor delegate,
            AgentCapabilityRegistry capabilityRegistry,
            AgentRuntimeConfigurationService runtimeConfigurationService
    ) {
        this.delegate = delegate;
        this.capabilityRegistry = capabilityRegistry;
        this.runtimeConfigurationService = runtimeConfigurationService;
    }

    @Override
    public CompletableFuture<Map<String, Object>> execute(AgentModelStreamEvent event) {
        return AgentCapabilityToolMapping.capabilityForTool(event.toolName())
                .map(capabilityId -> executeCapability(event, capabilityId))
                .orElseGet(() -> executeInternalTool(event));
    }

    private CompletableFuture<Map<String, Object>> executeCapability(
            AgentModelStreamEvent event,
            String capabilityId
    ) {
        AgentRuntimeProfile profile = runtimeConfigurationService.defaultProfile();
        AgentCapabilityResult result = capabilityRegistry.execute(profile, new AgentCapabilityRequest(
                requestId(event),
                profile.id(),
                capabilityId,
                event.arguments()
        ));
        return CompletableFuture.completedFuture(toToolResult(result));
    }

    private CompletableFuture<Map<String, Object>> executeInternalTool(AgentModelStreamEvent event) {
        boolean registered = runtimeConfigurationService.tools().stream()
                .anyMatch(tool -> tool.enabled() && tool.name().equals(event.toolName()));
        if (!registered) {
            return CompletableFuture.completedFuture(Map.of(
                    "status", "FAILED",
                    "tool_name", event.toolName(),
                    "error_code", "TOOL_NOT_REGISTERED",
                    "error_message", "tool is not registered: " + event.toolName()
            ));
        }
        return delegate.execute(event);
    }

    private String requestId(AgentModelStreamEvent event) {
        if (event.toolCallId() != null && !event.toolCallId().isBlank()) {
            return event.toolCallId();
        }
        return "cap_" + UUID.randomUUID();
    }

    private Map<String, Object> toToolResult(AgentCapabilityResult result) {
        Map<String, Object> toolResult = new LinkedHashMap<>();
        toolResult.put("status", result.status());
        toolResult.put("capability_id", result.capabilityId());
        toolResult.put("payload", result.payload());
        if (result.errorCode() != null && !result.errorCode().isBlank()) {
            toolResult.put("error_code", result.errorCode());
        }
        if (result.errorMessage() != null && !result.errorMessage().isBlank()) {
            toolResult.put("error_message", result.errorMessage());
        }
        return Map.copyOf(toolResult);
    }
}
