package com.sinrotic.rs.agent.service.impl;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.sinrotic.rs.agent.domain.vo.AgentRuntimeToolVO;
import com.sinrotic.rs.agent.service.AgentRuntimeConfigurationService;
import org.springframework.ai.tool.ToolCallback;
import org.springframework.ai.tool.function.FunctionToolCallback;
import org.springframework.core.ParameterizedTypeReference;

import java.util.LinkedHashMap;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Set;
import java.util.HashSet;

public class SpringAiAgentToolCallbackFactory {

    private static final int MAX_CACHED_TOOLS = 128;

    private static final Map<String, Object> BUILT_IN_FINAL_SCHEMA = new InMemoryAgentRuntimeConfigurationService()
            .tools().stream().filter(tool -> "emit_final_answer".equals(tool.name())).findFirst().orElseThrow().parametersSchema();

    private static final Map<String, Object> BUILT_IN_SKILL_SCHEMA = Map.of("type", "object",
            "properties", Map.of("skill_name", Map.of("type", "string")));

    private final AgentRuntimeConfigurationService runtimeConfigurationService;

    private final ObjectMapper objectMapper = new ObjectMapper();

    private final LinkedHashMap<String, PreparedTool> preparedTools = new LinkedHashMap<>(16, .75f, true);

    public SpringAiAgentToolCallbackFactory(AgentRuntimeConfigurationService runtimeConfigurationService) {
        this.runtimeConfigurationService = runtimeConfigurationService;
    }

    public List<ToolCallback> createToolCallbacks() {
        return createToolCallbacks(false);
    }

    public List<ToolCallback> createToolCallbacks(boolean finalAnswerOnly) {
        return createToolCallbacks(finalAnswerOnly, List.of());
    }

    public List<ToolCallback> createToolCallbacks(boolean finalAnswerOnly, List<?> completedToolResults) {
        if (runtimeConfigurationService == null) {
            return List.of();
        }
        Set<String> loaded = completedSkills(completedToolResults);
        return runtimeConfigurationService.toolsForProfile(runtimeConfigurationService.defaultProfile()).stream()
                .filter(tool -> !finalAnswerOnly || "emit_final_answer".equals(tool.name()))
                .map(tool -> skillCallback(tool, loaded))
                .filter(Objects::nonNull)
                .toList();
    }

    private Set<String> completedSkills(List<?> results) {
        var loaded = new HashSet<String>();
        for (Object value : results) {
            if (!(value instanceof Map<?, ?> result) || !"load_skill".equals(result.get("tool_name"))
                    || !"SUCCESS".equals(result.get("status")) || !(result.get("metadata") instanceof Map<?, ?> metadata)
                    || !Boolean.TRUE.equals(metadata.get("loaded"))) continue;
            for (var skill : runtimeConfigurationService.skills()) {
                if (skill.enabled() && skill.name().equals(metadata.get("skill_name"))
                        && skill.content().equals(metadata.get("content"))) loaded.add(skill.name());
            }
        }
        return Set.copyOf(loaded);
    }

    private ToolCallback skillCallback(AgentRuntimeToolVO tool, Set<String> loaded) {
        if (loaded.isEmpty() || !"load_skill".equals(tool.name())
                || !tool.parametersSchema().equals(BUILT_IN_SKILL_SCHEMA)) return toToolCallback(tool);
        var remaining = runtimeConfigurationService.skills().stream().filter(skill -> skill.enabled())
                .map(skill -> skill.name()).filter(name -> !loaded.contains(name)).toList();
        if (remaining.isEmpty()) return null;
        // 请求自己的不可变 schema，不能修改其他用户或前一轮的工具快照。
        String schema = writeJson(Map.of("type", "object", "additionalProperties", false,
                "properties", Map.of("skill_name", Map.of("type", "string", "enum", remaining)),
                "required", List.of("skill_name")));
        return buildToolCallback(tool, schema);
    }

    private ToolCallback toToolCallback(AgentRuntimeToolVO tool) {
        // Serialize before checking the cache so nested schema edits are visible too.
        String schema = writeJson(tool.parametersSchema());
        synchronized (preparedTools) {
            PreparedTool prepared = preparedTools.get(tool.name());
            if (prepared != null && prepared.schema.equals(schema)
                    && Objects.equals(prepared.description, tool.description())) {
                return prepared.callback;
            }
            ToolCallback callback = buildToolCallback(tool, schema);
            preparedTools.put(tool.name(), new PreparedTool(callback, schema, tool.description()));
            if (preparedTools.size() > MAX_CACHED_TOOLS) {
                preparedTools.remove(preparedTools.keySet().iterator().next());
            }
            return callback;
        }
    }

    public List<Map<String, Object>> strictToolDefinitions(List<ToolCallback> callbacks) {
        return callbacks.stream().map(this::strictToolDefinition).toList();
    }

    public List<Map<String, Object>> strictToolDefinitions(List<ToolCallback> callbacks, boolean compactNullFields) {
        return callbacks.stream().map(callback -> strictToolDefinition(callback, compactNullFields)).toList();
    }

    private Map<String, Object> strictToolDefinition(ToolCallback callback) {
        return strictToolDefinition(callback, false);
    }

    private Map<String, Object> strictToolDefinition(ToolCallback callback, boolean compactNullFields) {
        synchronized (preparedTools) {
            PreparedTool prepared = preparedTools.get(callback.getToolDefinition().name());
            if (prepared != null && prepared.callback == callback) {
                if (compactNullFields) {
                    if (prepared.compactDefinition == null) prepared.compactDefinition = buildStrictDefinition(callback, true);
                    return prepared.compactDefinition;
                }
                if (prepared.strictDefinition == null) {
                    prepared.strictDefinition = buildStrictDefinition(callback);
                }
                return prepared.strictDefinition;
            }
        }
        // A request can still use its snapshot after a concurrent update or eviction.
        return buildStrictDefinition(callback, compactNullFields);
    }

    private Map<String, Object> buildStrictDefinition(ToolCallback callback) {
        return buildStrictDefinition(callback, false);
    }

    @SuppressWarnings("unchecked")
    private Map<String, Object> buildStrictDefinition(ToolCallback callback, boolean compactNullFields) {
        var definition = callback.getToolDefinition();
        try {
            Map<String, Object> parameters = objectMapper.readValue(definition.inputSchema(),
                    new com.fasterxml.jackson.core.type.TypeReference<Map<String, Object>>() {});
            // Spring AI 2.0.0 puts strict inside parameters; vLLM expects function.strict.
            parameters.remove("strict");
            // 仅优化未修改的内置最终答案。按区块类型约束必要字段，省略不适用的 null。
            // 各类型能力和大小限制保持不变；外层仍校验完整 UI、商品交付及字符串语义。
            if (compactNullFields && "emit_final_answer".equals(definition.name()) && parameters.equals(BUILT_IN_FINAL_SCHEMA)) {
                var properties = (Map<String, Object>) parameters.get("properties");
                var blocks = (Map<String, Object>) properties.get("blocks");
                var item = (Map<String, Object>) blocks.get("items");
                blocks.put("items", compactBlockSchema(item));
            }
            return Map.of("type", "function", "function", Map.of(
                    "name", definition.name(), "description", definition.description(),
                    "strict", true, "parameters", immutableJson(parameters)));
        } catch (JsonProcessingException error) {
            throw new IllegalStateException("invalid constrained tool schema", error);
        }
    }

    @SuppressWarnings("unchecked")
    private Map<String, Object> compactBlockSchema(Map<String, Object> original) {
        var properties = (Map<String, Object>) original.get("properties");
        return Map.of("anyOf", List.of(
                compactBlock(properties, List.of("text", "followup_question"), List.of("content"), "content"),
                compactBlock(properties, List.of("product_cards"), List.of("card_set_id", "item_ids", "layout"), "card_set_id"),
                compactBlock(properties, List.of("product_cards"), List.of("card_set_id", "item_ids", "layout"), "item_ids"),
                compactBlock(properties, List.of("comparison_table"), List.of("content", "item_ids", "layout"), "content"),
                compactBlock(properties, List.of("comparison_table"), List.of("content", "item_ids", "layout"), "item_ids"),
                compactBlock(properties, List.of("a2ui"), List.of("messages"), "messages")));
    }

    @SuppressWarnings("unchecked")
    private Map<String, Object> compactBlock(Map<String, Object> original, List<String> types,
                                              List<String> fields, String requiredField) {
        var properties = new LinkedHashMap<String, Object>();
        properties.put("type", Map.of("type", "string", "enum", types));
        fields.forEach(field -> properties.put(field, original.get(field)));
        var required = new LinkedHashMap<>((Map<String, Object>) properties.get(requiredField));
        if ("messages".equals(requiredField)) {
            required = new LinkedHashMap<>((Map<String, Object>) ((List<?>) required.get("anyOf")).getFirst());
        } else {
            required.put("type", "item_ids".equals(requiredField) ? "array" : "string");
            if (!"item_ids".equals(requiredField)) required.put("minLength", 1);
        }
        properties.put(requiredField, required);
        return Map.of("type", "object", "additionalProperties", false, "properties", properties,
                "required", List.of("type", requiredField));
    }

    private static Object immutableJson(Object value) {
        if (value instanceof Map<?, ?> map) {
            Map<Object, Object> copy = new LinkedHashMap<>();
            map.forEach((key, nested) -> copy.put(key, immutableJson(nested)));
            return Collections.unmodifiableMap(copy);
        }
        if (value instanceof List<?> list) {
            List<Object> copy = new ArrayList<>(list.size());
            list.forEach(nested -> copy.add(immutableJson(nested)));
            return Collections.unmodifiableList(copy);
        }
        return value;
    }

    private ToolCallback buildToolCallback(AgentRuntimeToolVO tool, String schema) {
        return FunctionToolCallback.builder(tool.name(), (Map<String, Object> arguments) -> deferredResult(tool, arguments))
                .description(tool.description())
                .inputSchema(schema)
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

    private static final class PreparedTool {
        private final ToolCallback callback;
        private final String schema;
        private final String description;
        private Map<String, Object> strictDefinition;

        private Map<String, Object> compactDefinition;

        private PreparedTool(ToolCallback callback, String schema, String description) {
            this.callback = callback;
            this.schema = schema;
            this.description = description;
        }
    }
}
