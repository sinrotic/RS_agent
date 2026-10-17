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
        boolean registered = runtimeConfigurationService.tools().stream().anyMatch(tool -> tool.name().equals(event.toolName()));
        boolean authorized = AgentCapabilityToolMapping.capabilityForTool(event.toolName())
                .map(runtimeConfigurationService.defaultProfile().allowedCapabilities()::contains).orElse(true);
        if (registered && authorized && runtimeConfigurationService.toolsForProfile(runtimeConfigurationService.defaultProfile()).stream()
                .noneMatch(tool -> tool.name().equals(event.toolName()))) {
            return CompletableFuture.completedFuture(Map.of("status", "FAILED", "error_code", "TOOL_UNAVAILABLE",
                    "error_message", "Tool is disabled, unauthorized, or its dependency is not ready"));
        }
        return AgentCapabilityToolMapping.capabilityForTool(event.toolName())
                .map(capabilityId -> executeCapability(event, capabilityId))
                .orElseGet(() -> executeInternalTool(event));
    }

    private CompletableFuture<Map<String, Object>> executeCapability(
            AgentModelStreamEvent event,
            String capabilityId
    ) {
        // 正式装配使用既有虚拟线程执行器，不能在提交工具的模型流线程上等待 HTTP。
        // 自定义执行器继续遵守其原有执行约定。
        if (delegate instanceof VirtualThreadAgentToolUseExecutor virtualThreads) {
            if ("recommend".equals(capabilityId)) {
                return virtualThreads.executeRecommendation(event, ignored -> executeCapabilityNow(event, capabilityId));
            }
            return virtualThreads.execute(event, ignored -> executeCapabilityNow(event, capabilityId));
        }
        return CompletableFuture.completedFuture(executeCapabilityNow(event, capabilityId));
    }

    private Map<String, Object> executeCapabilityNow(AgentModelStreamEvent event, String capabilityId) {
        AgentRuntimeProfile profile = runtimeConfigurationService.defaultProfile();
        AgentCapabilityResult result = capabilityRegistry.execute(profile, new AgentCapabilityRequest(
                requestId(event),
                profile.id(),
                capabilityId,
                event.arguments()
        ));
        return toToolResult(result);
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
