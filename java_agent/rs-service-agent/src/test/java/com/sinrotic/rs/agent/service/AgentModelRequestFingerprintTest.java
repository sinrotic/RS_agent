package com.sinrotic.rs.agent.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.sinrotic.rs.agent.config.AgentModelProviderProperties;
import com.sinrotic.rs.agent.domain.dto.*;
import com.sinrotic.rs.agent.domain.vo.AgentStreamEventVO;
import com.sinrotic.rs.agent.service.impl.*;
import org.junit.jupiter.api.Test;
import org.springframework.ai.chat.messages.AssistantMessage;
import org.springframework.ai.chat.model.*;
import org.springframework.ai.chat.prompt.Prompt;
import org.springframework.ai.openai.OpenAiChatOptions;
import reactor.core.publisher.Flux;

import java.util.*;
import java.util.concurrent.atomic.AtomicReference;

import static org.assertj.core.api.Assertions.*;

class AgentModelRequestFingerprintTest {
    @Test
    void strictFingerprintDescribesThePreparedToolsInsteadOfTheRuntimeSourceSchema() {
        var runtime = new InMemoryAgentRuntimeConfigurationService();
        var captured = new AtomicReference<Prompt>();
        var client = new SpringAiAgentModelStreamClient(model(captured), runtime, null, true, null, 128, true);
        var first = observe(client, request(runtime, "private-user-query", Map.of()));
        assertThat(first).containsEntry("fingerprint_status", "observed")
                .containsEntry("fingerprint_scope", "spring_ai_prepared_request")
                .containsEntry("model_identity_status", "configured_alias");
        assertThat(first.get("tools_sha256")).isNotEqualTo(AgentModelRequestFingerprint.sha256(runtime.tools()));
        assertThat(first.toString()).doesNotContain("private-user-query", "test-declared-model");
        var changedQuestion = observe(client, request(runtime, "another-private-query", Map.of()));
        assertThat(changedQuestion.get("request_sha256")).isNotEqualTo(first.get("request_sha256"));
        for (String field : List.of("prompt_sha256", "tools_sha256", "skills_sha256", "request_options_sha256"))
            assertThat(changedQuestion.get(field)).as(field).isEqualTo(first.get(field));
        var finalOnly = observe(client, request(runtime, "private-user-query", Map.of("final_answer_only", true)));
        assertThat(finalOnly.get("tools_sha256")).isNotEqualTo(first.get("tools_sha256"));
        assertThat(finalOnly.get("request_options_sha256")).isNotEqualTo(first.get("request_options_sha256"));
    }

    @Test
    void runtimeEditsAndLoadedSkillContentChangeTheirOwnFingerprints() {
        var runtime = new InMemoryAgentRuntimeConfigurationService();
        var client = new SpringAiAgentModelStreamClient(model(new AtomicReference<>()), runtime);
        var before = observe(client, request(runtime, "需求", Map.of("server_loaded_skills", List.of(Map.of("name", "skill", "content", "version-one")))));
        var loaded = observe(client, request(runtime, "需求", Map.of("server_loaded_skills", List.of(Map.of("name", "skill", "content", "version-two")))));
        assertThat(loaded.get("skills_sha256")).isNotEqualTo(before.get("skills_sha256"));
        assertThat(loaded.get("prompt_sha256")).isEqualTo(before.get("prompt_sha256"));
        runtime.updateSystemPrompt(new AgentRuntimeSystemPromptUpdateDTO("updated", "新提示词规则"));
        var promptChanged = observe(client, request(runtime, "需求", Map.of()));
        assertThat(promptChanged.get("prompt_sha256")).isNotEqualTo(before.get("prompt_sha256"));
        var tool = runtime.tools().stream().filter(value -> value.name().equals("load_skill")).findFirst().orElseThrow();
        runtime.upsertTool(tool.name(), new AgentRuntimeToolUpsertDTO(tool.service(), "新工具说明", true, tool.parametersSchema()));
        var toolChanged = observe(client, request(runtime, "需求", Map.of()));
        assertThat(toolChanged.get("tools_sha256")).isNotEqualTo(promptChanged.get("tools_sha256"));
    }

    @Test
    void realLoopAttachesMetadataToTheAttemptWithoutExposingItAsBusinessEvents() {
        var runtime = new InMemoryAgentRuntimeConfigurationService();
        var client = new SpringAiAgentModelStreamClient(model(new AtomicReference<>()), runtime);
        var events = new ArrayList<AgentStreamEventVO>();
        var loop = new RsAgentLoop(runtime, event -> { throw new AssertionError("No business tool expected"); }, client);
        assertThat(loop.run(request(runtime, "请求内容", Map.of()), events::add).finishReason()).isEqualTo(AgentFinishReason.FINAL_ANSWER);
        var completed = events.stream().filter(event -> event.event().equals("model_call_completed")).findFirst().orElseThrow();
        assertThat(completed.data()).containsEntry("fingerprint_status", "observed");
        assertThat(completed.data().get("request_sha256")).asString().matches("[a-f0-9]{64}");
        assertThat(events).extracting(AgentStreamEventVO::event).doesNotContain("request_observation", "request_metadata");
    }

    @Test
    void httpAdaptersHashTheirOwnPayloadsWithoutClaimingRemoteModelInputs() throws Exception {
        var payload = new AtomicReference<String>();
        var http = new AgentModelProviderHttpClient() {
            @Override public String postJson(String url, String body, String accept) { throw new AssertionError(); }
            @Override public void streamJson(String url, String body, String accept, java.util.function.Consumer<String> sink) { payload.set(body); }
        };
        var props = new AgentModelProviderProperties();
        var request = request(new InMemoryAgentRuntimeConfigurationService(), "secret", Map.of());
        var python = observe(new PythonAgentApiModelStreamClient(props, http), request);
        assertThat(python).containsEntry("fingerprint_scope", "python_agent_adapter_request").containsEntry("model_identity_status", "unknown");
        assertThat(python.get("request_sha256")).isEqualTo(AgentModelRequestFingerprint.sha256(new ObjectMapper().readValue(payload.get(), Map.class)));
        var local = observe(new SelfHostedModelStreamClient(props, http), request);
        assertThat(local).containsEntry("fingerprint_scope", "self_hosted_adapter_request");
        assertThat(local.get("request_sha256")).isEqualTo(AgentModelRequestFingerprint.sha256(new ObjectMapper().readValue(payload.get(), Map.class)));
    }

    @Test
    void canonicalizationPreservesListOrderAndObservationFailuresLeaveGenerationWorking() {
        var a = new LinkedHashMap<String, Object>(); a.put("b", 1); a.put("a", Map.of("z", 2, "x", 3));
        var b = new LinkedHashMap<String, Object>(); b.put("a", Map.of("x", 3, "z", 2)); b.put("b", 1);
        assertThat(AgentModelRequestFingerprint.sha256(a)).isEqualTo(AgentModelRequestFingerprint.sha256(b));
        assertThat(AgentModelRequestFingerprint.sha256(List.of(1, 2))).isNotEqualTo(AgentModelRequestFingerprint.sha256(List.of(2, 1)));
        var observed = new AtomicReference<Map<String, Object>>();
        AgentModelRequestFingerprint.publish(observed::set, () -> { throw new IllegalStateException("private-error"); });
        assertThat(observed.get()).containsEntry("fingerprint_status", "unavailable").doesNotContainKey("error");
        var output = new ArrayList<AgentModelStreamEvent>();
        var client = new SpringAiAgentModelStreamClient(model(new AtomicReference<>()));
        assertThatCode(() -> client.streamAssistantEvents("turn", request(new InMemoryAgentRuntimeConfigurationService(), "需求", Map.of()),
                output::add, null, value -> { throw new IllegalStateException("observation failure"); })).doesNotThrowAnyException();
        assertThat(output).anyMatch(AgentModelStreamEvent::isToolUse);
    }

    private static AgentChatRequestDTO request(InMemoryAgentRuntimeConfigurationService runtime, String message, Map<String, Object> extra) {
        var context = new LinkedHashMap<>(runtime.modelContext()); context.putAll(extra);
        return new AgentChatRequestDTO("session", "profile", message, 1, context);
    }

    private static Map<String, Object> observe(AgentModelStreamClient client, AgentChatRequestDTO request) {
        var observation = new AtomicReference<Map<String, Object>>();
        client.streamAssistantEvents("turn", request, event -> { }, null, observation::set);
        return observation.get();
    }

    private static ChatModel model(AtomicReference<Prompt> captured) {
        return new ChatModel() {
            @Override public ChatResponse call(Prompt prompt) { throw new AssertionError("Streaming required"); }
            @Override public OpenAiChatOptions getDefaultOptions() { return OpenAiChatOptions.builder().model("test-declared-model").temperature(.2).build(); }
            @Override public Flux<ChatResponse> stream(Prompt prompt) {
                captured.set(prompt);
                return Flux.just(new ChatResponse(List.of(new Generation(AssistantMessage.builder().content("").toolCalls(List.of(
                        new AssistantMessage.ToolCall("final", "function", "emit_final_answer", "{\"blocks\":[{\"type\":\"text\",\"content\":\"完成\"}]}"))).build()))));
            }
        };
    }
}
