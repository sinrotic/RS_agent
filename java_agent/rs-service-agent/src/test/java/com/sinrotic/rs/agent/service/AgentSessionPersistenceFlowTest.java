package com.sinrotic.rs.agent.service;

import com.sinrotic.rs.agent.domain.dto.AgentChatRequestDTO;
import com.sinrotic.rs.agent.domain.session.AgentTranscriptEntry;
import com.sinrotic.rs.agent.service.impl.DefaultAgentSessionJournal;
import com.sinrotic.rs.agent.service.impl.InMemoryAgentHotSessionStore;
import com.sinrotic.rs.agent.service.impl.InMemoryAgentOrchestrationService;
import com.sinrotic.rs.agent.service.impl.InMemoryAgentRuntimeConfigurationService;
import com.sinrotic.rs.agent.service.impl.InMemoryAgentTranscriptEntryStore;
import com.sinrotic.rs.agent.service.impl.NoopAgentSessionProjectionStore;
import com.sinrotic.rs.agent.service.impl.RsAgentLoop;
import com.sinrotic.rs.agent.service.impl.VirtualThreadAgentToolUseExecutor;
import org.junit.jupiter.api.Test;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicInteger;

import static org.assertj.core.api.Assertions.assertThat;

class AgentSessionPersistenceFlowTest {

    @Test
    void retryableTurnReusesHistoryForContextAndSequenceWithoutDuplicatingRetry() {
        var entries = org.mockito.Mockito.spy(new InMemoryAgentTranscriptEntryStore());
        var hot = new InMemoryAgentHotSessionStore();
        var journal = new DefaultAgentSessionJournal(entries, new NoopAgentSessionProjectionStore(), hot);
        var modelCalls = new AtomicInteger();
        var service = service(entries, hot, journal, (id, request, consumer) -> {
            modelCalls.incrementAndGet();
            consumer.accept(com.sinrotic.rs.agent.service.impl.AgentModelStreamEvent.token("answer"));
            consumer.accept(com.sinrotic.rs.agent.service.impl.AgentModelStreamEvent.done());
        }, new VirtualThreadAgentToolUseExecutor(event -> Map.of()));
        service.setTranscriptRecoveryService(new com.sinrotic.rs.agent.service.impl.DefaultAgentTranscriptRecoveryService(
                new com.sinrotic.rs.agent.service.impl.InMemoryAgentTranscriptCheckpointStore(), entries));
        var first = new AgentChatRequestDTO("reuse", "user_001", "hello", 2, Map.of("client_turn_id", "first"));
        service.chat(first);
        org.mockito.Mockito.verify(entries, org.mockito.Mockito.times(1)).latest("reuse");
        org.mockito.Mockito.verify(entries, org.mockito.Mockito.times(1)).tailAfter("reuse", 0);
        var replay = service.chat(first);
        assertThat(replay.turnIndex()).isEqualTo(1);
        assertThat(modelCalls).hasValue(1);
        var second = service.chat(new AgentChatRequestDTO("reuse", "user_001", "next", 2, Map.of("client_turn_id", "second")));
        assertThat(second.turnIndex()).isEqualTo(2);
        assertThat(modelCalls).hasValue(2);
        assertThat(entries.tailAfter("reuse", 0)).extracting(AgentTranscriptEntry::seq).containsExactly(1L, 2L, 3L, 4L);
        assertThat(service.sessionTurns("reuse", "user_001").turns()).hasSize(2);
    }

    @Test
    void restartRecoversHistoryAndRejectsAnotherProfileBeforeCallingRecommendation() {
        var entries = new InMemoryAgentTranscriptEntryStore();
        var originalHot = new InMemoryAgentHotSessionStore();
        var originalJournal = new DefaultAgentSessionJournal(entries, new NoopAgentSessionProjectionStore(), originalHot);
        AgentModelStreamClient model = (id, request, consumer) -> {
            consumer.accept(com.sinrotic.rs.agent.service.impl.AgentModelStreamEvent.token("saved answer"));
            consumer.accept(com.sinrotic.rs.agent.service.impl.AgentModelStreamEvent.done());
        };
        var first = service(entries, originalHot, originalJournal, model,
                new VirtualThreadAgentToolUseExecutor(event -> Map.of()));
        first.streamChat(request("session-restart"), event -> { });
        var restartedHot = new InMemoryAgentHotSessionStore();
        var restarted = service(entries, restartedHot,
                new DefaultAgentSessionJournal(entries, new NoopAgentSessionProjectionStore(), restartedHot),
                model, new VirtualThreadAgentToolUseExecutor(event -> Map.of()));
        var recommendationCalls = new AtomicInteger();
        restarted.setRecommendationService(request -> { recommendationCalls.incrementAndGet(); return List.of(); });
        assertThat(restarted.sessionTurns("session-restart", "user_001").turns())
                .hasSize(1).first().extracting(com.sinrotic.rs.agent.domain.vo.AgentTurnVO::assistantMessage)
                .isEqualTo("saved answer");
        org.junit.jupiter.api.Assertions.assertThrows(AgentSessionNotFoundException.class,
                () -> restarted.streamChat(new AgentChatRequestDTO("session-restart", "other-user", "hello", 1, Map.of()), event -> { }));
        assertThat(recommendationCalls).hasValue(0);
        assertThat(entries.tailAfter("session-restart", 0)).hasSize(2);
    }

    @Test
    void persistsUserBeforeModelAndFinalBeforeDoneWithoutPersistingTokenDeltas() {
        InMemoryAgentTranscriptEntryStore entryStore = new InMemoryAgentTranscriptEntryStore();
        InMemoryAgentHotSessionStore hotStore = new InMemoryAgentHotSessionStore();
        DefaultAgentSessionJournal journal = new DefaultAgentSessionJournal(
                entryStore,
                new NoopAgentSessionProjectionStore(),
                hotStore
        );
        AtomicBoolean userWasDurableBeforeModel = new AtomicBoolean();
        AtomicBoolean finalWasDurableBeforeDone = new AtomicBoolean();
        InMemoryAgentOrchestrationService service = service(
                entryStore,
                hotStore,
                journal,
                (requestId, request, consumer) -> {
                    userWasDurableBeforeModel.set(entryStore.latest(request.sessionId())
                            .map(entry -> entry.entryType().equals("USER_MESSAGE")
                                    && entry.requestId().equals(requestId))
                            .orElse(false));
                    consumer.accept(com.sinrotic.rs.agent.service.impl.AgentModelStreamEvent.token("hello"));
                    consumer.accept(com.sinrotic.rs.agent.service.impl.AgentModelStreamEvent.done());
                },
                new VirtualThreadAgentToolUseExecutor(event -> Map.of("status", "SUCCESS"))
        );

        service.streamChat(request("sess_persist_order"), event -> {
            if (event.event().equals("done")) {
                finalWasDurableBeforeDone.set(entryStore.latest("sess_persist_order")
                        .map(entry -> entry.entryType().equals("ASSISTANT_FINAL"))
                        .orElse(false));
            }
        });

        assertThat(userWasDurableBeforeModel).isTrue();
        assertThat(finalWasDurableBeforeDone).isTrue();
        assertThat(entryStore.tailAfter("sess_persist_order", 0))
                .extracting(AgentTranscriptEntry::entryType)
                .containsExactly("USER_MESSAGE", "ASSISTANT_FINAL")
                .doesNotContain("MODEL_TOKEN", "AGENT_DONE");
    }

    @Test
    void persistsToolUseBeforeExecutionAndToolResultBeforeNextModelCall() {
        InMemoryAgentTranscriptEntryStore entryStore = new InMemoryAgentTranscriptEntryStore();
        InMemoryAgentHotSessionStore hotStore = new InMemoryAgentHotSessionStore();
        DefaultAgentSessionJournal journal = new DefaultAgentSessionJournal(
                entryStore,
                new NoopAgentSessionProjectionStore(),
                hotStore
        );
        AtomicInteger modelCalls = new AtomicInteger();
        AtomicBoolean toolUseWasDurableBeforeExecution = new AtomicBoolean();
        AtomicBoolean toolResultWasDurableBeforeNextModelCall = new AtomicBoolean();
        VirtualThreadAgentToolUseExecutor toolExecutor = new VirtualThreadAgentToolUseExecutor(event -> {
            toolUseWasDurableBeforeExecution.set(entryStore.latest("sess_tool_boundary")
                    .map(entry -> entry.entryType().equals("TOOL_USE"))
                    .orElse(false));
            return Map.of("status", "SUCCESS", "items", List.of("B001"));
        });
        InMemoryAgentOrchestrationService service = service(
                entryStore,
                hotStore,
                journal,
                (requestId, request, consumer) -> {
                    if (modelCalls.incrementAndGet() == 1) {
                        consumer.accept(com.sinrotic.rs.agent.service.impl.AgentModelStreamEvent.toolUse(
                                "call_001",
                                "recommend_candidates",
                                Map.of("limit", 1)
                        ));
                        return;
                    }
                    toolResultWasDurableBeforeNextModelCall.set(entryStore.latest(request.sessionId())
                            .map(entry -> entry.entryType().equals("TOOL_RESULT"))
                            .orElse(false));
                    consumer.accept(com.sinrotic.rs.agent.service.impl.AgentModelStreamEvent.token("answer"));
                    consumer.accept(com.sinrotic.rs.agent.service.impl.AgentModelStreamEvent.done());
                },
                toolExecutor
        );

        service.streamChat(request("sess_tool_boundary"), ignored -> {
        });

        assertThat(toolUseWasDurableBeforeExecution).isTrue();
        assertThat(toolResultWasDurableBeforeNextModelCall).isTrue();
        assertThat(entryStore.tailAfter("sess_tool_boundary", 0))
                .extracting(AgentTranscriptEntry::entryType)
                .containsExactly("USER_MESSAGE", "TOOL_USE", "TOOL_RESULT", "ASSISTANT_FINAL");
    }

    private InMemoryAgentOrchestrationService service(
            InMemoryAgentTranscriptEntryStore entryStore,
            InMemoryAgentHotSessionStore hotStore,
            DefaultAgentSessionJournal journal,
            AgentModelStreamClient modelClient,
            AgentToolUseExecutor toolExecutor
    ) {
        return new InMemoryAgentOrchestrationService(
                new RsAgentLoop(
                        new InMemoryAgentRuntimeConfigurationService(),
                        toolExecutor,
                        modelClient
                ),
                event -> {
                },
                hotStore,
                null,
                null,
                journal
        );
    }

    private AgentChatRequestDTO request(String sessionId) {
        return new AgentChatRequestDTO(
                sessionId,
                "user_001",
                "Find headphones",
                2,
                Map.of("scene", "chat")
        );
    }
}
