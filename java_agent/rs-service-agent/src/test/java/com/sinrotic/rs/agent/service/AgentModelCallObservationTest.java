package com.sinrotic.rs.agent.service;

import com.sinrotic.rs.agent.domain.dto.AgentChatRequestDTO;
import com.sinrotic.rs.agent.domain.vo.AgentStreamEventVO;
import com.sinrotic.rs.agent.service.impl.*;
import org.junit.jupiter.api.Test;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicLong;

import static org.assertj.core.api.Assertions.*;

class AgentModelCallObservationTest {
    @Test
    void finalSnapshotIsDeduplicatedAndTimingDoesNotDependOnWallClock() {
        var time = new AtomicLong(1_000_000);
        var events = new ArrayList<AgentStreamEventVO>();
        var observation = new AgentModelCallObservation("turn", "session", 0, events::add, time::get);
        observation.record(AgentModelStreamEvent.usage(Map.of("prompt_tokens", 10, "completion_tokens", 2, "total_tokens", 12)));
        time.set(2_000_000);
        observation.record(AgentModelStreamEvent.token("回答"));
        observation.record(AgentModelStreamEvent.usage(Map.of("prompt_tokens", 10, "completion_tokens", 5, "total_tokens", 15,
                "native_usage", Map.of("private_input", "不应导出"))));
        time.set(4_000_000);
        observation.finish("completed", true);
        observation.finish("completed", true);
        assertThat(events).extracting(AgentStreamEventVO::event).containsExactly("model_call_started", "model_call_completed");
        assertThat(events.get(1).data()).containsEntry("latency_ms", 3L).containsEntry("first_token_ms", 1L)
                .containsEntry("usage_final", true).containsEntry("usage_status", "complete")
                .doesNotContainKeys("native_usage", "total_tokens");
        assertThat(events.get(1).data().get("usage"))
                .isEqualTo(Map.of("prompt_tokens", 10, "completion_tokens", 5, "total_tokens", 15));
    }

    @Test
    void earlyExitKeepsUnknownUsageAndDoesNotClaimFullTransport() {
        var events = new ArrayList<AgentStreamEventVO>();
        var observation = new AgentModelCallObservation("turn", "session", 1, events::add);
        observation.finish("answer_emitted", false);
        assertThat(events.getLast().data()).containsEntry("usage", Map.of())
                .containsEntry("usage_status", "missing").containsEntry("usage_final", false)
                .doesNotContainKey("first_token_ms");
    }

    @Test
    void verifiedFinalProviderUsageSurvivesTheFinalAnswerSignal() {
        var events = new ArrayList<AgentStreamEventVO>();
        var observation = new AgentModelCallObservation("turn", "session", 0, events::add);
        observation.record(AgentModelStreamEvent.usage(Map.of("prompt_tokens", 10, "completion_tokens", 5,
                "total_tokens", 15, "usage_final", true)));
        observation.finish("answer_emitted", false);
        assertThat(events.getLast().data()).containsEntry("usage_final", true).containsEntry("transport_finished", false);
    }

    @Test
    void eachLoopAttemptHasItsOwnObservationAndFinalAnswerStillStopsImmediately() {
        var attempts = new AtomicInteger();
        var events = new ArrayList<AgentStreamEventVO>();
        var loop = new RsAgentLoop(new InMemoryAgentRuntimeConfigurationService(),
                new VirtualThreadAgentToolUseExecutor(event -> Map.of("status", "SUCCESS")), (id, request, sink) -> {
            if (attempts.getAndIncrement() == 0) {
                sink.accept(AgentModelStreamEvent.usage(Map.of("prompt_tokens", 20, "completion_tokens", 5, "total_tokens", 25)));
                sink.accept(AgentModelStreamEvent.toolUse("lookup", "recommend_candidates", Map.of("limit", 1)));
                sink.accept(AgentModelStreamEvent.done());
            } else {
                sink.accept(AgentModelStreamEvent.toolUse("emit_final_answer",
                        Map.of("blocks", List.of(Map.of("type", "text", "content", "推荐已完成")))));
                throw new AssertionError("最终回答之后不应等待流式尾部");
            }
        });
        var result = loop.run(new AgentChatRequestDTO("session", "profile", "买一支笔", 1, Map.of()), events::add);
        var calls = events.stream().filter(event -> event.event().equals("model_call_completed")).toList();
        assertThat(result.finishReason()).isEqualTo(AgentFinishReason.FINAL_ANSWER);
        assertThat(calls).hasSize(2);
        assertThat(calls.get(0).data()).containsEntry("loop_index", 0).containsEntry("usage_final", true);
        assertThat(calls.get(1).data()).containsEntry("loop_index", 1).containsEntry("usage_final", false)
                .containsEntry("usage_status", "missing").containsEntry("status", "answer_emitted");
        assertThat(calls.get(0).data().get("model_call_id")).isNotEqualTo(calls.get(1).data().get("model_call_id"));
        assertThat(calls).allSatisfy(call -> assertThat(call.data().get("turn_id")).isEqualTo(result.requestId()));
    }

    @Test
    void failedModelAttemptIsObservedAndOriginalFailureIsPreserved() {
        var events = new ArrayList<AgentStreamEventVO>();
        var original = new IllegalStateException("模拟模型失败");
        var loop = new RsAgentLoop(new InMemoryAgentRuntimeConfigurationService(),
                new VirtualThreadAgentToolUseExecutor(event -> Map.of()), (id, request, sink) -> { throw original; });
        assertThatThrownBy(() -> loop.run(new AgentChatRequestDTO("session", "profile", "需求", 1, Map.of()), events::add))
                .isSameAs(original);
        assertThat(events.stream().filter(event -> event.event().equals("model_call_completed")).findFirst().orElseThrow().data())
                .containsEntry("status", "error").containsEntry("usage_status", "missing");
    }

    @Test
    void observationSinkFailureDoesNotBreakBusinessProcessing() {
        var observation = new AgentModelCallObservation("turn", "session", 0, event -> { throw new IllegalStateException(); });
        assertThatCode(() -> observation.finish("completed", true)).doesNotThrowAnyException();
    }
}
