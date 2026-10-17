package com.sinrotic.rs.agent.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.sinrotic.rs.agent.service.impl.InMemoryAgentRuntimeConfigurationService;
import com.sinrotic.rs.agent.service.impl.SpringAiAgentToolCallbackFactory;
import com.sinrotic.rs.agent.config.AgentTemplateProperties;
import com.sinrotic.rs.agent.domain.AgentProfileFailurePolicy;
import com.sinrotic.rs.agent.domain.AgentPublicOutputBlock;
import com.sinrotic.rs.agent.domain.AgentRuntimeProfile;
import com.sinrotic.rs.agent.domain.dto.AgentRuntimeToolUpsertDTO;
import com.sinrotic.rs.agent.domain.vo.AgentRuntimeToolVO;
import org.junit.jupiter.api.Test;
import org.springframework.ai.tool.ToolCallback;

import java.util.List;
import java.util.Map;
import java.util.LinkedHashMap;
import java.util.concurrent.Executors;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.Mockito.CALLS_REAL_METHODS;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

class SpringAiAgentToolCallbackFactoryTest {
    @Test
    void completedSkillCannotBeLoadedAgainButUpdatedContentCan() throws Exception {
        var runtime = new InMemoryAgentRuntimeConfigurationService();
        var factory = new SpringAiAgentToolCallbackFactory(runtime);
        var skill = runtime.skill("explicit-need-recommendation");
        var completed = List.of(Map.of("tool_name", "load_skill", "status", "SUCCESS", "metadata",
                Map.of("loaded", true, "skill_name", skill.name(), "content", skill.content())));
        var oldSnapshot = factory.createToolCallbacks();
        var callbacks = factory.createToolCallbacks(false, completed);
        var callback = callbacks.stream().filter(tool -> "load_skill".equals(tool.getToolDefinition().name())).findFirst().orElseThrow();
        var schema = new ObjectMapper().readTree(callback.getToolDefinition().inputSchema());
        assertThat(schema.path("properties").path("skill_name").path("enum").toString()).doesNotContain(skill.name());
        assertThat(schema.path("properties").path("skill_name").path("enum")).isNotEmpty();
        assertThat(schema.path("required").toString()).isEqualTo("[\"skill_name\"]");
        assertThat(oldSnapshot.stream().filter(tool -> "load_skill".equals(tool.getToolDefinition().name())).findFirst().orElseThrow()
                .getToolDefinition().inputSchema()).doesNotContain("enum");
        runtime.upsertSkill(skill.name(), new com.sinrotic.rs.agent.domain.dto.AgentRuntimeSkillUpsertDTO(
                skill.description(), "updated skill content", true));
        assertThat(factory.createToolCallbacks(false, completed).stream().filter(tool -> "load_skill".equals(tool.getToolDefinition().name())).toList())
                .singleElement().satisfies(tool -> assertThat(tool.getToolDefinition().inputSchema()).doesNotContain("enum"));
    }

    @Test
    void failedSkillLoadsAndCustomSchemasKeepTheOriginalTools() {
        var runtime = new InMemoryAgentRuntimeConfigurationService();
        var factory = new SpringAiAgentToolCallbackFactory(runtime);
        var skill = runtime.skill("explicit-need-recommendation");
        var metadata = Map.of("loaded", true, "skill_name", skill.name(), "content", skill.content());
        var failed = List.of(Map.of("tool_name", "load_skill", "status", "FAILED", "metadata", metadata));
        assertThat(factory.createToolCallbacks(false, failed)).isEqualTo(factory.createToolCallbacks());
        runtime.upsertTool("load_skill", new AgentRuntimeToolUpsertDTO("rs-service-agent", "custom", true,
                Map.of("type", "object", "properties", Map.of("skill_name", Map.of("type", "string")),
                        "required", List.of("skill_name"))));
        var completed = List.of(Map.of("tool_name", "load_skill", "status", "SUCCESS", "metadata", metadata));
        assertThat(factory.createToolCallbacks(false, completed)).isEqualTo(factory.createToolCallbacks());
    }
    @Test
    void compactFinalWireCanOmitUnusedFieldsWithoutRemovingCardOrUiCapabilities() throws Exception {
        var factory = new SpringAiAgentToolCallbackFactory(new InMemoryAgentRuntimeConfigurationService());
        var callbacks = factory.createToolCallbacks(true);
        var mapper = new ObjectMapper();
        var original = mapper.valueToTree(factory.strictToolDefinitions(callbacks).getFirst());
        var compact = mapper.valueToTree(factory.strictToolDefinitions(callbacks, true).getFirst());
        var before = original.path("function").path("parameters").path("properties").path("blocks").path("items");
        var after = compact.path("function").path("parameters").path("properties").path("blocks").path("items");
        assertThat(after.path("anyOf")).hasSize(6);
        for (var variant : after.path("anyOf")) {
            assertThat(variant.path("additionalProperties").asBoolean()).isFalse();
            assertThat(variant.path("required")).hasSize(2);
            assertThat(variant.path("properties").path("type").path("enum")).isNotEmpty();
        }
        assertThat(after.path("anyOf").get(0).path("required").toString()).isEqualTo("[\"type\",\"content\"]");
        assertThat(after.path("anyOf").get(0).path("properties").path("content").path("type").asText()).isEqualTo("string");
        assertThat(after.path("anyOf").get(1).path("required").toString()).isEqualTo("[\"type\",\"card_set_id\"]");
        assertThat(after.path("anyOf").get(2).path("required").toString()).isEqualTo("[\"type\",\"item_ids\"]");
        assertThat(after.path("anyOf").get(2).path("properties").path("item_ids").path("maxItems")).isEqualTo(before.path("properties").path("item_ids").path("maxItems"));
        assertThat(after.path("anyOf").get(5).path("properties").path("messages"))
                .isEqualTo(before.path("properties").path("messages").path("anyOf").get(0));
        assertThat(factory.strictToolDefinitions(callbacks).getFirst()).isEqualTo(mapper.convertValue(original, Map.class));
    }

    @Test
    void compactFinalWirePreservesCustomRequiredFields() {
        var runtime = new InMemoryAgentRuntimeConfigurationService();
        runtime.upsertTool("emit_final_answer", new AgentRuntimeToolUpsertDTO("rs-service-agent", "Custom answer", true,
                Map.of("type", "object", "properties", Map.of("text", Map.of("type", "string")), "required", List.of("text"))));
        var factory = new SpringAiAgentToolCallbackFactory(runtime);
        var callbacks = factory.createToolCallbacks(true);
        assertThat(factory.strictToolDefinitions(callbacks, true)).isEqualTo(factory.strictToolDefinitions(callbacks));
    }

    @Test
    void warmedCacheStillRespectsChangedProfilePermissions() {
        var base = new InMemoryAgentRuntimeConfigurationService();
        var runtime = mock(AgentRuntimeConfigurationService.class, CALLS_REAL_METHODS);
        when(runtime.tools()).thenReturn(base.tools());
        when(runtime.defaultProfile()).thenReturn(base.defaultProfile());
        var factory = new SpringAiAgentToolCallbackFactory(runtime);
        assertThat(factory.createToolCallbacks()).extracting(tool -> tool.getToolDefinition().name())
                .contains("rag_support", "session_memory", "emit_ui");
        when(runtime.defaultProfile()).thenReturn(new AgentRuntimeProfile(
                "recommend-only", "default", "default", List.of("recommend"),
                List.of(AgentPublicOutputBlock.TEXT), 3, AgentProfileFailurePolicy.FAIL_TURN));
        assertThat(factory.createToolCallbacks()).extracting(tool -> tool.getToolDefinition().name())
                .contains("recommend_candidates", "emit_final_answer")
                .doesNotContain("rag_support", "rag_evidence_search", "session_memory", "emit_ui");
        assertThat(factory.createToolCallbacks(true)).extracting(tool -> tool.getToolDefinition().name())
                .containsExactly("emit_final_answer");
    }

    @Test
    void preparedToolsFollowLiveUpdatesAndDisabledToolsDisappear() {
        var runtime = new InMemoryAgentRuntimeConfigurationService();
        var factory = new SpringAiAgentToolCallbackFactory(runtime);
        var first = callback(factory, "load_skill");
        assertThat(callback(factory, "load_skill")).isSameAs(first);
        var original = runtime.tools().stream().filter(tool -> tool.name().equals("load_skill")).findFirst().orElseThrow();
        runtime.upsertTool("load_skill", new AgentRuntimeToolUpsertDTO(original.service(), "updated description", true, original.parametersSchema()));
        assertThat(callback(factory, "load_skill").getToolDefinition().description()).isEqualTo("updated description");
        assertThat(first.getToolDefinition().description()).isEqualTo(original.description());
        runtime.upsertTool("load_skill", new AgentRuntimeToolUpsertDTO(original.service(), "updated description", false, original.parametersSchema()));
        assertThat(factory.createToolCallbacks()).extracting(tool -> tool.getToolDefinition().name()).doesNotContain("load_skill");
    }

    @Test
    @SuppressWarnings("unchecked")
    void nestedSchemaEditsRefreshTheCacheAndOldRequestsKeepTheirSnapshot() {
        var runtime = new InMemoryAgentRuntimeConfigurationService();
        var factory = new SpringAiAgentToolCallbackFactory(runtime);
        Map<String, Object> property = new LinkedHashMap<>(Map.of("type", "string"));
        runtime.upsertTool("load_skill", new AgentRuntimeToolUpsertDTO(null, "load", true,
                Map.of("type", "object", "strict", true, "properties", Map.of("skill_name", property))));
        var first = callback(factory, "load_skill");
        var firstWire = factory.strictToolDefinitions(List.of(first)).getFirst();
        property.put("type", "integer");
        var second = callback(factory, "load_skill");
        assertThat(second.getToolDefinition().inputSchema()).contains("integer");
        assertThat(first.getToolDefinition().inputSchema()).doesNotContain("integer");
        assertThat(factory.strictToolDefinitions(List.of(first)).getFirst()).isEqualTo(firstWire);
        Map<String, Object> function = (Map<String, Object>) firstWire.get("function");
        Map<String, Object> parameters = (Map<String, Object>) function.get("parameters");
        assertThat(function).containsEntry("strict", true);
        assertThat(parameters).doesNotContainKey("strict");
        Map<String, Object> oldProperty = (Map<String, Object>) ((Map<?, ?>) parameters.get("properties")).get("skill_name");
        assertThatThrownBy(() -> oldProperty.put("type", "boolean")).isInstanceOf(UnsupportedOperationException.class);
        assertThat(factory.strictToolDefinitions(List.of(second)).getFirst().toString()).contains("integer");
    }

    @Test
    void requestSnapshotsRemainUsableAfterManyRuntimeDefinitions() {
        var base = new InMemoryAgentRuntimeConfigurationService();
        var runtime = mock(AgentRuntimeConfigurationService.class, CALLS_REAL_METHODS);
        when(runtime.defaultProfile()).thenReturn(base.defaultProfile());
        var factory = new SpringAiAgentToolCallbackFactory(runtime);
        when(runtime.tools()).thenReturn(List.of(new AgentRuntimeToolVO("first", "local", "first", true, Map.of("type", "object"))));
        var first = factory.createToolCallbacks().getFirst();
        var firstWire = factory.strictToolDefinitions(List.of(first));
        for (int i = 0; i < 140; i++) {
            when(runtime.tools()).thenReturn(List.of(new AgentRuntimeToolVO("custom_" + i, "local", "custom", true, Map.of("type", "object"))));
            factory.strictToolDefinitions(factory.createToolCallbacks());
        }
        assertThat(factory.strictToolDefinitions(List.of(first))).isEqualTo(firstWire);
        assertThat(first.call("{}")).contains("DEFERRED").contains("first");
    }

    @Test
    void concurrentRequestsKeepFinalOnlyAndFullToolSetsSeparate() throws Exception {
        var factory = new SpringAiAgentToolCallbackFactory(new InMemoryAgentRuntimeConfigurationService());
        int toolCount = factory.createToolCallbacks().size();
        try (var executor = Executors.newVirtualThreadPerTaskExecutor()) {
            var futures = java.util.stream.IntStream.range(0, 32).mapToObj(index -> executor.submit(() -> {
                for (int turn = 0; turn < 40; turn++) {
                    boolean finalOnly = (index + turn) % 2 == 0;
                    var callbacks = factory.createToolCallbacks(finalOnly);
                    assertThat(callbacks).hasSize(finalOnly ? 1 : toolCount);
                    var wire = factory.strictToolDefinitions(callbacks);
                    assertThat(wire).hasSameSizeAs(callbacks);
                    String marker = "user-" + index + "-turn-" + turn;
                    assertThat(callbacks.getFirst().call("{\"request_marker\":\"" + marker + "\"}"))
                            .contains("\"request_marker\":\"" + marker + "\"")
                            .contains("\"status\":\"DEFERRED\"");
                    if (finalOnly) {
                        assertThat(callbacks.getFirst().getToolDefinition().name()).isEqualTo("emit_final_answer");
                    }
                }
            })).toList();
            for (var future : futures) future.get();
        }
    }

    private static ToolCallback callback(SpringAiAgentToolCallbackFactory factory, String name) {
        return factory.createToolCallbacks().stream().filter(tool -> tool.getToolDefinition().name().equals(name)).findFirst().orElseThrow();
    }

    @Test
    void finalBoundaryOnlyAdvertisesFinalAnswerTool() {
        var factory = new SpringAiAgentToolCallbackFactory(new InMemoryAgentRuntimeConfigurationService());
        assertThat(factory.createToolCallbacks(true)).extracting(callback -> callback.getToolDefinition().name())
                .containsExactly("emit_final_answer");
    }

    @Test
    void createsSpringAiToolCallbacksFromEnabledRuntimeTools() throws Exception {
        SpringAiAgentToolCallbackFactory factory = new SpringAiAgentToolCallbackFactory(
                new InMemoryAgentRuntimeConfigurationService()
        );

        List<ToolCallback> callbacks = factory.createToolCallbacks();

        assertThat(callbacks)
                .extracting(callback -> callback.getToolDefinition().name())
                .contains("load_skill", "call_agent", "emit_final_answer", "emit_ui");
        ToolCallback emitFinalAnswer = callbacks.stream()
                .filter(callback -> "emit_final_answer".equals(callback.getToolDefinition().name()))
                .findFirst()
                .orElseThrow();
        assertThat(emitFinalAnswer.getToolDefinition().description())
                .contains("final answer");
        assertThat(emitFinalAnswer.getToolDefinition().inputSchema())
                .contains("\"blocks\"")
                .contains("\"product_cards\"")
                .contains("\"followup_question\"");
        JsonNode schema = new ObjectMapper().readTree(emitFinalAnswer.getToolDefinition().inputSchema());
        assertThat(schema.path("additionalProperties").asBoolean()).isFalse();
        JsonNode blocks = schema.path("properties").path("blocks");
        assertThat(blocks.path("minItems").asInt()).isEqualTo(1);
        assertThat(blocks.path("maxItems").asInt()).isEqualTo(12);
        JsonNode block = blocks.path("items");
        assertThat(block.path("additionalProperties").asBoolean()).isFalse();
        assertThat(block.path("properties")).hasSize(6);
        assertThat(block.path("properties").has("messages")).isTrue();
        assertThat(block.path("required")).hasSize(6);
    }

    @Test
    void callbackExecutionIsDeferredToAgentLoop() {
        SpringAiAgentToolCallbackFactory factory = new SpringAiAgentToolCallbackFactory(
                new InMemoryAgentRuntimeConfigurationService()
        );

        ToolCallback loadSkill = factory.createToolCallbacks().stream()
                .filter(callback -> "load_skill".equals(callback.getToolDefinition().name()))
                .findFirst()
                .orElseThrow();

        String result = loadSkill.call("{\"skill_name\":\"explicit-need-recommendation\"}");

        assertThat(result)
                .contains("\"status\":\"DEFERRED\"")
                .contains("\"tool_name\":\"load_skill\"")
                .contains("agent loop");
    }

    @Test
    void hidesCapabilitiesThatTheSelectedProfileDoesNotAllow() {
        AgentTemplateProperties.Profile profile = new AgentTemplateProperties.Profile();
        profile.setId("recommend-only");
        profile.setModelRef("default");
        profile.setSystemPromptRef("default");
        profile.setAllowedCapabilities(List.of("recommend"));
        profile.setAllowedOutputBlocks(List.of(AgentPublicOutputBlock.TEXT));
        profile.setMaxLoops(3);
        profile.setFailurePolicy(AgentProfileFailurePolicy.FAIL_TURN);
        AgentTemplateProperties properties = new AgentTemplateProperties();
        properties.setDefaultProfile("recommend-only");
        properties.setProfiles(List.of(profile));
        SpringAiAgentToolCallbackFactory factory = new SpringAiAgentToolCallbackFactory(
                new InMemoryAgentRuntimeConfigurationService(properties)
        );

        assertThat(factory.createToolCallbacks())
                .extracting(callback -> callback.getToolDefinition().name())
                .contains("recommend_candidates")
                .doesNotContain("rag_support", "rag_evidence_search", "session_memory");
    }
}
