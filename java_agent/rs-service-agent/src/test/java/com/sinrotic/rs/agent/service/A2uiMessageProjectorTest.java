package com.sinrotic.rs.agent.service;

import com.sinrotic.rs.agent.domain.dto.AgentChatRequestDTO;
import com.sinrotic.rs.agent.domain.dto.AgentRuntimeToolUpsertDTO;
import com.sinrotic.rs.agent.domain.vo.AgentStreamEventVO;
import com.sinrotic.rs.agent.service.impl.AgentModelStreamEvent;
import com.sinrotic.rs.agent.service.impl.InMemoryAgentOrchestrationService;
import com.sinrotic.rs.agent.service.impl.InMemoryAgentRuntimeConfigurationService;
import com.sinrotic.rs.agent.service.impl.VirtualThreadAgentToolUseExecutor;
import org.junit.jupiter.api.Test;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.concurrent.atomic.AtomicInteger;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class A2uiMessageProjectorTest {
    private final A2uiMessageProjector projector = new A2uiMessageProjector();

    static List<Map<String, Object>> initialMessages() {
        return List.of(
                Map.of("version", "v0.9", "createSurface", Map.of("surfaceId", "shopping", "catalogId", A2uiMessageProjector.CATALOG_ID)),
                Map.of("version", "v0.9", "updateComponents", Map.of("surfaceId", "shopping", "components", List.of(
                        Map.of("id", "root", "component", "Text", "text", Map.of("path", "/summary"))))),
                Map.of("version", "v0.9", "updateDataModel", Map.of("surfaceId", "shopping", "value", Map.of("summary", "正在查找"))));
    }

    @Test
    void supportsCreationComponentsDataReplacementAndDeletion() {
        assertThat(projector.project(initialMessages())).hasSize(3);
        assertThat(projector.project(List.of(Map.of("version", "v0.9", "updateDataModel",
                Map.of("surfaceId", "shopping", "path", "/summary"))))).hasSize(1);
        assertThat(projector.project(List.of(Map.of("version", "v0.9", "deleteSurface",
                Map.of("surfaceId", "shopping"))))).hasSize(1);
    }

    @Test
    void rejectsWrongCatalogArbitraryComponentsAndInternalNestedFields() {
        assertThatThrownBy(() -> projector.project(List.of(Map.of("version", "v0.9", "createSurface",
                Map.of("surfaceId", "shopping", "catalogId", "unknown"))))).isInstanceOf(IllegalArgumentException.class);
        for (Map<String, Object> component : List.of(
                Map.<String, Object>of("id", "root", "component", "Script", "code", "alert(1)"),
                Map.<String, Object>of("id", "root", "component", "Text", "text", "公开文字", "trace", "secret"))) {
            assertThatThrownBy(() -> projector.project(List.of(Map.of("version", "v0.9", "updateComponents",
                    Map.of("surfaceId", "shopping", "components", List.of(component))))))
                    .isInstanceOf(IllegalArgumentException.class);
        }
    }

    @Test
    void rejectsInvalidPointersPrototypeKeysAndOversizedBatches() {
        for (String path : List.of("summary", "/a~2b", "/__proto__/polluted")) {
            assertThatThrownBy(() -> projector.project(List.of(Map.of("version", "v0.9", "updateDataModel",
                    Map.of("surfaceId", "shopping", "path", path, "value", "bad")))))
                    .isInstanceOf(IllegalArgumentException.class);
        }
        assertThatThrownBy(() -> projector.project(List.of(Map.of("version", "v0.9", "updateDataModel",
                Map.of("surfaceId", "shopping", "value", Map.of("constructor", "bad"))))))
                .isInstanceOf(IllegalArgumentException.class);
        assertThatThrownBy(() -> projector.project(java.util.Collections.nCopies(33, initialMessages().getFirst())))
                .isInstanceOf(IllegalArgumentException.class);
        assertThatThrownBy(() -> projector.project(List.of(Map.of("version", "v0.9", "updateDataModel",
                Map.of("surfaceId", "shopping", "value", Map.of("details", Map.of("diagnostics", "secret")))))))
                .isInstanceOf(IllegalArgumentException.class);
    }

    @Test
    void skillReceivesTheActualCatalogAndToolSchema() {
        var runtime = new InMemoryAgentRuntimeConfigurationService();
        assertThat(runtime.skill("a2ui-interface").content()).contains(A2uiMessageProjector.CATALOG_ID,
                "ProductCards", "updateDataModel", "emit_ui", "oneOf");
        var tool = runtime.tools().stream().filter(value -> value.name().equals("emit_ui")).findFirst().orElseThrow();
        assertThat(((Map<?, ?>) tool.parametersSchema().get("properties")).get("messages"))
                .isEqualTo(A2uiMessageProjector.messagesSchema());
    }

    @Test
    void validatesLifecycleAndCyclesWithoutCorruptingAcceptedState() {
        var state = new A2uiMessageProjector.State(null);
        var update = Map.of("version", "v0.9", "updateDataModel", Map.of("surfaceId", "shopping", "value", "updated"));
        assertThatThrownBy(() -> state.accept(List.of(update))).hasMessageContaining("created first");
        state.accept(initialMessages());
        assertThatThrownBy(() -> state.accept(List.of(initialMessages().getFirst()))).hasMessageContaining("already exists");
        assertThatThrownBy(() -> state.accept(List.of(Map.of("version", "v0.9", "updateComponents", Map.of(
                "surfaceId", "shopping", "components", List.of(Map.of("id", "root", "component", "Column", "children", List.of("root"))))))))
                .hasMessageContaining("cycle");
        state.accept(List.of(update));
        state.validateComplete();
        state.accept(List.of(Map.of("version", "v0.9", "deleteSurface", Map.of("surfaceId", "shopping"))));
        state.accept(initialMessages());
    }

    @Test
    void validatesRestoredClientStateAndRequiresCompleteTreeAtFinalAnswer() {
        var state = new A2uiMessageProjector.State(List.of(Map.of(
                "surfaceId", "shopping", "catalogId", A2uiMessageProjector.CATALOG_ID,
                "components", List.of(Map.of("id", "root", "component", "Column", "children", List.of("missing"))),
                "data", Map.of("query", "耳机"))));
        assertThatThrownBy(state::validateComplete).hasMessageContaining("child component not found");
        assertThatThrownBy(() -> new A2uiMessageProjector.State(List.of(Map.of("surfaceId", "shopping"))))
                .isInstanceOf(IllegalArgumentException.class);
    }

    @Test
    void publishesUiBeforeFinalAnswerAndPreservesItInRestAndPublicSse() {
        var runtime = new InMemoryAgentRuntimeConfigurationService();
        AtomicInteger calls = new AtomicInteger();
        try (var executor = new VirtualThreadAgentToolUseExecutor(runtime)) {
            var service = new InMemoryAgentOrchestrationService((requestId, request, consumer) -> {
                int call = calls.getAndIncrement();
                if (call == 0) consumer.accept(AgentModelStreamEvent.toolUse("emit_ui", Map.of("messages", initialMessages())));
                else if (call == 1) consumer.accept(AgentModelStreamEvent.toolUse("emit_ui", Map.of("messages", List.of(
                        Map.of("version", "v0.9", "updateDataModel", Map.of("surfaceId", "shopping", "path", "/summary", "value", "查询完成"))))));
                else consumer.accept(AgentModelStreamEvent.toolUse("emit_final_answer", Map.of("blocks", List.of(
                        Map.of("type", "text", "content", "请查看查询结果。")))));
            }, executor, runtime);
            List<AgentStreamEventVO> events = new ArrayList<>();
            service.streamChat(new AgentChatRequestDTO("ui-session", "profile", "帮我选择商品", 5, Map.of()), events::add);
            var publicEvents = events.stream().map(new PublicAgentStreamProjector()::project).flatMap(java.util.Optional::stream).toList();
            assertThat(publicEvents).extracting(AgentStreamEventVO::event)
                    .containsExactly("answer_block", "answer_block", "answer_block", "done");
            Map<?, ?> response = (Map<?, ?>) publicEvents.getLast().data().get("response");
            assertThat(response.get("answer_blocks")).asList().hasSize(3);
            assertThat(response.containsKey("tool_calls")).isFalse();
            assertThat(response.get("assistant_message")).isEqualTo("请查看查询结果。");
            calls.set(0);
            assertThat(service.chat(new AgentChatRequestDTO("rest-ui-session", "profile", "商品", 5, Map.of())).answerBlocks()).hasSize(3);
        }
    }

    @Test
    void disabledUiToolReturnsFailureToModelAndDoesNotPublish() {
        var runtime = new InMemoryAgentRuntimeConfigurationService();
        runtime.upsertTool("emit_ui", new AgentRuntimeToolUpsertDTO("rs-service-agent", "disabled", false, Map.of()));
        AtomicInteger calls = new AtomicInteger();
        try (var executor = new VirtualThreadAgentToolUseExecutor(runtime)) {
            var service = new InMemoryAgentOrchestrationService((requestId, request, consumer) -> {
                if (calls.getAndIncrement() == 0) consumer.accept(AgentModelStreamEvent.toolUse("emit_ui", Map.of("messages", initialMessages())));
                else {
                    assertThat(request.resolvedContext().get("tool_results").toString()).contains("FAILED", "disabled");
                    consumer.accept(AgentModelStreamEvent.toolUse("emit_final_answer", Map.of("blocks", List.of(Map.of("type", "text", "content", "文字回答")))));
                }
            }, executor, runtime);
            assertThat(service.chat(new AgentChatRequestDTO("disabled-ui", "profile", "商品", 5, Map.of())).answerBlocks())
                    .containsExactly(Map.of("type", "text", "content", "文字回答"));
        }
    }
}
