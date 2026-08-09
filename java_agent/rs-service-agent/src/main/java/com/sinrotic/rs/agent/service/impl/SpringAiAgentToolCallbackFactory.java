package com.sinrotic.rs.agent.service.impl;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.sinrotic.rs.agent.domain.vo.AgentRuntimeToolVO;
import com.sinrotic.rs.agent.service.AgentRuntimeConfigurationService;
import org.springframework.ai.tool.ToolCallback;
import org.springframework.ai.tool.function.FunctionToolCallback;
import org.springframework.core.ParameterizedTypeReference;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

public class SpringAiAgentToolCallbackFactory {

    private final AgentRuntimeConfigurationService runtimeConfigurationService;

    private final ObjectMapper objectMapper = new ObjectMapper();

    public SpringAiAgentToolCallbackFactory(AgentRuntimeConfigurationService runtimeConfigurationService) {
        this.runtimeConfigurationService = runtimeConfigurationService;
    }

    public List<ToolCallback> createToolCallbacks() {
        if (runtimeConfigurationService == null) {
            return List.of();
        }
        return runtimeConfigurationService.toolsForProfile(runtimeConfigurationService.defaultProfile()).stream()
                .map(this::toToolCallback)
                .toList();
    }

    private ToolCallback toToolCallback(AgentRuntimeToolVO tool) {
        return FunctionToolCallback.builder(tool.name(), (Map<String, Object> arguments) -> deferredResult(tool, arguments))
                .description(tool.description())
                .inputSchema(writeJson(tool.parametersSchema()))
                .inputType(new ParameterizedTypeReference<Map<String, Object>>() {
                })
                .build();
    }

    private Map<String, Object> deferredResult(AgentRuntimeToolVO tool, Map<String, Object> arguments) {
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("status", "DEFERRED");
        result.put("tool_name", tool.name());
        result.put("message", "Tool execution is owned by the outer agent loop.");
        result.put("arguments", arguments == null ? Map.of() : arguments);
        return result;
    }

    private String writeJson(Object value) {
        try {
            return objectMapper.writeValueAsString(value == null ? Map.of("type", "object") : value);
        } catch (JsonProcessingException ex) {
            throw new IllegalStateException("failed to serialize spring ai tool schema", ex);
        }
    }
}
