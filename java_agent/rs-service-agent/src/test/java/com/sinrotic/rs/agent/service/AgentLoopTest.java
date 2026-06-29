package com.sinrotic.rs.agent.service;

import com.sinrotic.rs.agent.domain.dto.AgentChatRequestDTO;
import com.sinrotic.rs.agent.domain.vo.AgentStreamEventVO;
import com.sinrotic.rs.agent.service.impl.AgentLoop;
import com.sinrotic.rs.agent.service.impl.AgentLoopResult;
import com.sinrotic.rs.agent.service.impl.AgentModelStreamEvent;
import com.sinrotic.rs.agent.service.impl.AgentProfile;
import com.sinrotic.rs.agent.service.impl.InMemoryAgentRuntimeConfigurationService;
import com.sinrotic.rs.agent.service.impl.RsAgentLoop;
import com.sinrotic.rs.agent.service.impl.VirtualThreadAgentToolUseExecutor;
import org.junit.jupiter.api.Test;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.concurrent.atomic.AtomicBoolean;

import static org.assertj.core.api.Assertions.assertThat;

class AgentLoopTest {

    @Test
    void subclassCanProvideAgentProfileAndCustomToolServices() {
        TestAgentLoop loop = new TestAgentLoop();
        List<AgentStreamEventVO> events = new ArrayList<>();

        AgentLoopResult result = loop.run(new AgentChatRequestDTO(
                "sess_custom_agent",
                "A1XYZ",
                "Run custom tool",
                1,
                Map.of("scene", "custom")
        ), events::add);

        assertThat(result.agentName()).isEqualTo("test_agent");
        assertThat(result.assistantMessage()).isEqualTo("custom answer");
        assertThat(result.toolCalls()).hasSize(1);
        assertThat(result.toolCalls().getFirst().toolName()).isEqualTo("custom_lookup");
        assertThat(result.toolCalls().getFirst().service()).isEqualTo("rs-service-custom");
        assertThat(events).extracting(AgentStreamEventVO::event)
                .containsSequence("tool_use", "tool_result", "token", "done");
    }

    @Test
    void emitFinalAnswerProducesUserVisibleAnswerBlocksAndStopsLoop() {
        AtomicBoolean internalExecutorCalled = new AtomicBoolean(false);
        AgentLoop loop = new AgentLoop(
                new AgentProfile("test_agent", "Structured answer test agent.", Map.of(
                        "emit_final_answer", "rs-service-agent"
                )),
                new InMemoryAgentRuntimeConfigurationService(),
                new VirtualThreadAgentToolUseExecutor(event -> {
                    internalExecutorCalled.set(true);
                    return Map.of("status", "SHOULD_NOT_RUN");
                }),
                (requestId, request, consumer) -> consumer.accept(AgentModelStreamEvent.toolUse(
                        "emit_final_answer",
                        Map.of("blocks", List.of(
                                Map.of("type", "text", "content", "我建议先看这两款。"),
                                Map.of("type", "product_cards", "card_set_id", "cards_001"),
                                Map.of("type", "text", "content", "第一款更适合通勤，第二款更适合防水。")
                        ))
                ))
        ) {
        };
        List<AgentStreamEventVO> events = new ArrayList<>();

        AgentLoopResult result = loop.run(new AgentChatRequestDTO(
                "sess_blocks",
                "A1XYZ",
                "推荐通勤包",
                2,
                Map.of()
        ), events::add);

        assertThat(internalExecutorCalled).isFalse();
        assertThat(result.assistantMessage()).isEqualTo("我建议先看这两款。\n第一款更适合通勤，第二款更适合防水。");
        assertThat(result.toolCalls()).isEmpty();
        assertThat(events).extracting(AgentStreamEventVO::event)
                .containsExactly("answer_block", "answer_block", "answer_block", "done");
        assertThat(events.get(0).data())
                .containsEntry("type", "text")
                .containsEntry("content", "我建议先看这两款。");
        assertThat(events.get(1).data())
                .containsEntry("type", "product_cards")
                .containsEntry("card_set_id", "cards_001");
    }

    @Test
    void rsAgentLoopMapsSpecificRecommendToolsToRecommendService() {
        AgentLoop loop = new RsAgentLoop(
                new InMemoryAgentRuntimeConfigurationService(),
                new VirtualThreadAgentToolUseExecutor(event -> Map.of("status", "SUCCESS")),
                new SingleToolThenDoneModelStreamClient("recommend_semantic_recall")
        );
        List<AgentStreamEventVO> events = new ArrayList<>();

        AgentLoopResult result = loop.run(new AgentChatRequestDTO(
                "sess_recommend_tool",
                "A1XYZ",
                "recommend portable staplers",
                1,
                Map.of()
        ), events::add);

        assertThat(result.toolCalls()).hasSize(1);
        assertThat(result.toolCalls().getFirst().toolName()).isEqualTo("recommend_semantic_recall");
        assertThat(result.toolCalls().getFirst().service()).isEqualTo("rs-service-recommend");
    }

    private static class TestAgentLoop extends AgentLoop {

        TestAgentLoop() {
            super(
                    new AgentProfile(
                            "test_agent",
                            "Agent used to prove subclass-specific tool registration.",
                            Map.of("custom_lookup", "rs-service-custom")
                    ),
                    new InMemoryAgentRuntimeConfigurationService(),
                    new VirtualThreadAgentToolUseExecutor(event -> Map.of("status", "SUCCESS")),
                    new TestModelStreamClient()
            );
        }
    }

    private static class TestModelStreamClient implements AgentModelStreamClient {

        private int calls;

        @Override
        public void streamAssistantEvents(
                String requestId,
                AgentChatRequestDTO request,
                java.util.function.Consumer<AgentModelStreamEvent> consumer
        ) {
            if (++calls == 1) {
                consumer.accept(AgentModelStreamEvent.toolUse("custom_lookup", Map.of("key", "value")));
                return;
            }
            consumer.accept(AgentModelStreamEvent.token("custom answer"));
            consumer.accept(AgentModelStreamEvent.done());
        }
    }

    private static class SingleToolThenDoneModelStreamClient implements AgentModelStreamClient {

        private final String toolName;

        private int calls;

        SingleToolThenDoneModelStreamClient(String toolName) {
            this.toolName = toolName;
        }

        @Override
        public void streamAssistantEvents(
                String requestId,
                AgentChatRequestDTO request,
                java.util.function.Consumer<AgentModelStreamEvent> consumer
        ) {
            if (++calls == 1) {
                consumer.accept(AgentModelStreamEvent.toolUse(toolName, Map.of("query", "portable staplers")));
                return;
            }
            consumer.accept(AgentModelStreamEvent.token("done"));
            consumer.accept(AgentModelStreamEvent.done());
        }
    }
}
