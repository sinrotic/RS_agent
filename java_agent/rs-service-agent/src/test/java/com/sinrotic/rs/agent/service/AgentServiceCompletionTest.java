package com.sinrotic.rs.agent.service;

import com.sinrotic.rs.agent.domain.dto.AgentChatRequestDTO;
import com.sinrotic.rs.agent.domain.vo.AgentRecommendedItemVO;
import com.sinrotic.rs.agent.service.impl.*;
import org.junit.jupiter.api.Test;
import java.util.List;
import java.util.Map;
import java.util.concurrent.atomic.AtomicInteger;
import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class AgentServiceCompletionTest {

    @Test
    void legacyAccountlessHistoryAndCompletedReplayVerifyUserOwnershipWithoutRevivingEndedSession() {
        var calls = new AtomicInteger();
        var ownerChecks = new AtomicInteger();
        var journal = new DefaultAgentSessionJournal(new InMemoryAgentTranscriptEntryStore(),
                new NoopAgentSessionProjectionStore(), new InMemoryAgentHotSessionStore());
        AgentModelStreamClient model = (id, request, consumer) -> {
            calls.incrementAndGet();
            consumer.accept(AgentModelStreamEvent.toolUse("emit_final_answer", Map.of("blocks", List.of(Map.of("type", "text", "content", "已完成")))));
        };
        service(model, journal).chat(new AgentChatRequestDTO("legacy", "profile", "背包", 1, Map.of("client_turn_id", "completed")));
        var restarted = service(model, journal);
        restarted.setSessionAdmissionClient(new AgentSessionAdmissionClient() {
            public void admit(AgentChatRequestDTO request) { throw new org.springframework.web.server.ResponseStatusException(org.springframework.http.HttpStatus.GONE); }
            public void verifyOwner(String accountId, String profileUserId, String sessionId) {
                ownerChecks.incrementAndGet();
                if (!"account".equals(accountId)) throw new org.springframework.web.server.ResponseStatusException(org.springframework.http.HttpStatus.NOT_FOUND);
            }
        });
        assertThat(restarted.chat(new AgentChatRequestDTO("legacy", "profile", "背包", 1,
                Map.of("client_turn_id", "completed", "authenticated_account_id", "account"))).assistantMessage()).isEqualTo("已完成");
        assertThat(restarted.sessionTurns("legacy", "profile", "account").turns()).hasSize(1);
        assertThatThrownBy(() -> restarted.chat(new AgentChatRequestDTO("legacy", "profile", "背包", 1,
                Map.of("client_turn_id", "completed", "authenticated_account_id", "other-account")))).hasMessageContaining("404");
        assertThat(calls).hasValue(1);
        assertThat(ownerChecks).hasValue(3);
    }

    @Test
    void contextLossIsJournaledAndModelIsToldToClarifyMissingConstraints() {
        var journal = new DefaultAgentSessionJournal(new InMemoryAgentTranscriptEntryStore(),
                new NoopAgentSessionProjectionStore(), new InMemoryAgentHotSessionStore());
        AgentModelStreamClient model = (id, request, consumer) -> consumer.accept(AgentModelStreamEvent.toolUse(
                "emit_final_answer", Map.of("blocks", List.of(Map.of("type", "text", "content", "好的")))));
        service(model, journal).chat(new AgentChatRequestDTO("long", "profile", "很长的完整需求".repeat(1000), 1, Map.of()));
        var captured = new java.util.concurrent.atomic.AtomicReference<Map<String, Object>>();
        service((id, request, consumer) -> { captured.set(request.resolvedContext()); model.streamAssistantEvents(id, request, consumer); }, journal)
                .chat(new AgentChatRequestDTO("long", "profile", "继续", 1, Map.of()));
        assertThat(captured.get().get("context_recovery_notice").toString()).contains("澄清");
        assertThat(journal.transcript("long")).filteredOn(entry -> "CONTEXT_TRUNCATED".equals(entry.entryType())).hasSize(1);
    }

    @Test
    void endedSessionIsRejectedBeforeModelRecommendationOrJournalWrites() {
        var calls = new AtomicInteger();
        var journal = new DefaultAgentSessionJournal(new InMemoryAgentTranscriptEntryStore(),
                new NoopAgentSessionProjectionStore(), new InMemoryAgentHotSessionStore());
        var agent = service((id, request, consumer) -> calls.incrementAndGet(), journal);
        agent.setRecommendationService(request -> { calls.incrementAndGet(); return List.of(); });
        agent.setSessionAdmissionClient(request -> { throw new org.springframework.web.server.ResponseStatusException(org.springframework.http.HttpStatus.GONE); });
        assertThatThrownBy(() -> agent.chat(new AgentChatRequestDTO("ended", "profile", "继续", 1, Map.of())))
                .hasMessageContaining("410");
        assertThat(calls).hasValue(0);
        assertThat(journal.transcript("ended")).isEmpty();
    }

    @Test
    void sessionViewsAreBoundedAndEvictionDoesNotLoseHistoryOrOwnership() {
        var journal = new DefaultAgentSessionJournal(new InMemoryAgentTranscriptEntryStore(),
                new NoopAgentSessionProjectionStore(), new InMemoryAgentHotSessionStore());
        var agent = service((id, request, consumer) -> consumer.accept(AgentModelStreamEvent.toolUse("emit_final_answer",
                Map.of("blocks", List.of(Map.of("type", "text", "content", "已记录"))))), journal);
        for (int index = 0; index < 300; index++) agent.chat(new AgentChatRequestDTO("bounded-" + index, "profile", "背包", 1, Map.of()));
        assertThat(agent.retainedSessionCount()).isLessThanOrEqualTo(256);
        assertThat(agent.sessionTurns("bounded-0", "profile").turns()).hasSize(1);
        assertThatThrownBy(() -> agent.chat(new AgentChatRequestDTO("bounded-0", "other", "背包", 1, Map.of())))
                .isInstanceOf(AgentSessionNotFoundException.class);
        assertThat(agent.chat(new AgentChatRequestDTO("bounded-0", "profile", "继续", 1, Map.of())).turnIndex()).isEqualTo(2);
    }
    @Test
    void coldModelContextIncludesEarlierRequirementsWithoutRedisSnapshot() {
        var journal = new DefaultAgentSessionJournal(new InMemoryAgentTranscriptEntryStore(),
                new NoopAgentSessionProjectionStore(), new InMemoryAgentHotSessionStore());
        AgentModelStreamClient reply = (id, request, consumer) -> consumer.accept(AgentModelStreamEvent.toolUse(
                "emit_final_answer", Map.of("blocks", List.of(Map.of("type", "text", "content", "好的")))));
        var first = service(reply, journal);
        first.chat(new AgentChatRequestDTO("cold-session", "profile", "预算五百元，必须防雨", 1, Map.of()));
        first.chat(new AgentChatRequestDTO("cold-session", "profile", "希望轻一些", 1, Map.of()));
        var captured = new java.util.concurrent.atomic.AtomicReference<Map<String, Object>>();
        service((id, request, consumer) -> {
            captured.set(request.resolvedContext()); reply.streamAssistantEvents(id, request, consumer);
        }, journal).chat(new AgentChatRequestDTO("cold-session", "profile", "继续推荐", 1, Map.of()));
        assertThat(String.valueOf(captured.get().get("session_effective_context"))).contains("预算五百元", "必须防雨", "希望轻一些");
    }
    @Test
    void modelFailureBecomesDurablePublicHistoryAndNextTurnCanContinue() {
        var calls = new AtomicInteger();
        AgentModelStreamClient model = (id, request, consumer) -> {
            if (calls.incrementAndGet() == 1) throw new IllegalStateException("private backend credential");
            consumer.accept(AgentModelStreamEvent.toolUse("emit_final_answer", Map.of("blocks", List.of(
                    Map.of("type", "text", "content", "本轮可以继续。")))));
        };
        var journal = new DefaultAgentSessionJournal(new InMemoryAgentTranscriptEntryStore(),
                new NoopAgentSessionProjectionStore(), new InMemoryAgentHotSessionStore());
        var agent = service(model, journal);
        var request = new AgentChatRequestDTO("failure-session", "profile", "选背包", 1, Map.of("client_turn_id", "failed-turn"));
        assertThatThrownBy(() -> agent.chat(request)).isInstanceOf(IllegalStateException.class);
        var restarted = service(model, journal);
        var failed = restarted.sessionTurns("failure-session", "profile").turns().getFirst();
        assertThat(failed.finishReason()).isEqualTo("MODEL_ERROR");
        assertThat(failed.assistantMessage()).contains("本轮未完成").doesNotContain("private", "credential");
        assertThatThrownBy(() -> restarted.chat(request)).hasMessageContaining("409");
        assertThat(restarted.chat(new AgentChatRequestDTO("failure-session", "profile", "选背包", 1,
                Map.of("client_turn_id", "new-turn"))).turnIndex()).isEqualTo(2);
        assertThat(calls).hasValue(2);
    }
    @Test
    void firstStreamEventCanInterruptBeforeAnyModelCall() {
        var interrupter = new InMemoryAgentInterrupter();
        var calls = new AtomicInteger();
        var loop = new RsAgentLoop(new InMemoryAgentRuntimeConfigurationService(), new VirtualThreadAgentToolUseExecutor(),
                (id, request, consumer) -> calls.incrementAndGet(), new NoopAgentLoopHookDispatcher(), interrupter);
        var agent = new InMemoryAgentOrchestrationService(loop);
        agent.setRecommendationService(request -> List.of());
        var interrupted = new java.util.concurrent.atomic.AtomicBoolean();
        agent.streamChat(new AgentChatRequestDTO("stop-session", "profile", "选背包", 1, Map.of()), event -> {
            if ("trace".equals(event.event())) {
                interrupted.set(interrupter.interruptOwned(event.requestId(), "profile", "user_stop"));
            }
        });
        assertThat(interrupted).isTrue();
        assertThat(calls).hasValue(0);
        assertThat(agent.sessionTurns("stop-session", "profile").turns().getFirst().finishReason()).isEqualTo("INTERRUPTED");
    }
    @Test
    void recommendationOutageStillCompletesTextTurnWithPublicDegradation() {
        var calls = new AtomicInteger();
        AgentModelStreamClient model = (id, request, consumer) -> {
            calls.incrementAndGet();
            assertThat(request.resolvedContext().get("recommendation_items")).isEqualTo(List.of());
            consumer.accept(AgentModelStreamEvent.toolUse("emit_final_answer", Map.of("blocks", List.of(
                    Map.of("type", "text", "content", "可以先告诉我容量和预算要求。")))));
        };
        var entries = new InMemoryAgentTranscriptEntryStore();
        var journal = new DefaultAgentSessionJournal(entries, new NoopAgentSessionProjectionStore(), new InMemoryAgentHotSessionStore());
        var agent = service(model, journal);
        agent.setRecommendationService(new HttpAgentRecommendationService(request -> {
            throw new IllegalStateException("HTTP 503 private backend");
        }));
        var result = agent.chat(new AgentChatRequestDTO("offline-session", "profile", "需要背包", 1, Map.of("client_turn_id", "offline-turn")));
        assertThat(result.recommendedItems()).isEmpty();
        assertThat(result.degradationReasons()).containsExactly("recommendation_unavailable");
        assertThat(result.assistantMessage()).contains("预算");
        assertThat(calls).hasValue(1);
        assertThat(service(model, journal).sessionTurns("offline-session", "profile").turns().getFirst().degradationReasons())
                .containsExactly("recommendation_unavailable");
    }
    @Test
    void responseLossRetryAndProcessRecreationReuseDurableAnswerWithoutNewModelCall() {
        var entries = new InMemoryAgentTranscriptEntryStore();
        var journal = new DefaultAgentSessionJournal(entries, new NoopAgentSessionProjectionStore(), new InMemoryAgentHotSessionStore());
        var calls = new AtomicInteger();
        AgentModelStreamClient model = (id, request, consumer) -> {
            calls.incrementAndGet();
            consumer.accept(AgentModelStreamEvent.toolUse("emit_final_answer", Map.of("blocks", List.of(
                    Map.of("type", "text", "content", "推荐这款背包。"),
                    Map.of("type", "followup_question", "content", "需要防雨吗？")))));
        };
        var first = service(model, journal);
        var request = new AgentChatRequestDTO("session", "profile", "选背包", 1, Map.of("client_turn_id", "turn-1"));
        var response = first.chat(request);
        assertThat(first.chat(request).requestId()).isEqualTo(response.requestId());
        var restarted = service(model, journal);
        var replay = restarted.chat(request);
        assertThat(replay.requestId()).isEqualTo(response.requestId());
        assertThat(replay.answerBlocks()).hasSize(2);
        assertThat(replay.recommendedItems()).extracting(AgentRecommendedItemVO::itemId).containsExactly("item");
        assertThat(calls).hasValue(1);
        var history = restarted.sessionTurns("session", "profile").turns();
        assertThat(history).hasSize(1);
        assertThat(history.getFirst().answerBlocks()).hasSize(2);
        assertThat(history.getFirst().cardSetId()).isEqualTo("delivery");
        assertThatThrownBy(() -> restarted.sessionTurns("session", "other-profile")).isInstanceOf(AgentSessionNotFoundException.class);
        assertThatThrownBy(() -> restarted.chat(new AgentChatRequestDTO("session", "profile", "换了消息", 1,
                Map.of("client_turn_id", "turn-1")))).hasMessageContaining("409");
    }

    private InMemoryAgentOrchestrationService service(AgentModelStreamClient model, AgentSessionJournal journal) {
        var loop = new RsAgentLoop(new InMemoryAgentRuntimeConfigurationService(), new VirtualThreadAgentToolUseExecutor(), model);
        var result = new InMemoryAgentOrchestrationService(loop, null, null, null, null, journal);
        result.setRecommendationService(request -> List.of(new AgentRecommendedItemVO("item", "背包", "Bags", .9, "通勤", "delivery")));
        return result;
    }
}
