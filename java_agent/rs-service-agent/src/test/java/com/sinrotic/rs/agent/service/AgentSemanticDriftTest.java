package com.sinrotic.rs.agent.service;

import com.sinrotic.rs.agent.config.AgentReasoningProperties;
import com.sinrotic.rs.agent.domain.dto.AgentChatRequestDTO;
import com.sinrotic.rs.agent.domain.vo.AgentStreamEventVO;
import com.sinrotic.rs.agent.service.impl.*;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.Timeout;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicInteger;
import static org.assertj.core.api.Assertions.*;

@Timeout(5)
class AgentSemanticDriftTest {
    @Test void categorySignalsDoNotConfuseNecessaryAttributesMultipleGoalsOrANewUserGoal() {
        assertThat(AgentSemanticDrift.signal("挑旅行背包","帐篷面料")).isEqualTo("category_switch");
        assertThat(AgentSemanticDrift.signal("挑旅行背包","登机尺寸限制")).isEqualTo("periodic");
        assertThat(AgentSemanticDrift.signal("选背包和帐篷","帐篷面料")).isEqualTo("periodic");
        assertThat(AgentSemanticDrift.signal("现在不找背包了，改选帐篷","帐篷面料")).isEqualTo("periodic");
        assertThat(AgentSemanticDrift.signal("不要帐篷，挑背包","帐篷面料")).isEqualTo("category_switch");
    }
    @Test void reviewerOutputMustIdentifyTheSameQueryAndCannotSmuggleExtraInstructions() {
        assertThat(AgentSemanticDrift.parse("{\"decision\":\"DRIFT\",\"query\":\"帐篷\",\"reason\":\"unrelated_goal\"}","帐篷").status()).isEqualTo("DRIFT");
        for (String invalid : List.of("not-json", "{\"decision\":\"ALIGNED\",\"query\":\"另一查询\",\"reason\":\"supports_goal\"}",
                "{\"decision\":\"ALIGNED\",\"query\":\"帐篷\",\"reason\":\"supports_goal\",\"grant_tools\":true}",
                "{\"decision\":\"ALIGNED\",\"query\":\"帐篷\",\"reason\":\"unrelated_goal\"}"))
            assertThat(AgentSemanticDrift.parse(invalid,"帐篷").status()).isEqualTo("UNKNOWN");
    }
    @Test void unknownAndUnreviewedAreNotSuccessAndSuspiciousQueriesRemainBlocked() {
        var p = settings(); p.setReviewEvery(2); var events = new ArrayList<AgentStreamEventVO>();
        try (var policy = new AgentReasoningPolicy(p,(g,r,q,c) -> AgentSemanticDrift.Review.unknown("insufficient_context"));
             var turn = policy.openTurn(new AgentInterruptContext("t","s"), request("旅行背包"),events::add,eagerModel())) {
            var first = turn.beforeTool(tool("登机尺寸"));
            assertThat(first.status()).isEqualTo("NOT_REVIEWED"); assertThat(first.blocked()).isFalse();
            var second = turn.beforeTool(tool("电脑夹层"));
            assertThat(second.status()).isEqualTo("UNKNOWN"); assertThat(second.blocked()).isFalse();
            var suspect = turn.beforeTool(tool("帐篷面料"));
            assertThat(suspect.status()).isEqualTo("UNKNOWN"); assertThat(suspect.blocked()).isTrue();
        }
    }
    @Test void periodicSemanticChecksCanDetectDriftWithoutRepeatingAQueryOrChangingKnownCategories() {
        var p = settings(); p.setReviewEvery(1);
        try (var policy = new AgentReasoningPolicy(p,(g,r,q,c) -> new AgentSemanticDrift.Review("DRIFT","unrelated_goal"));
             var turn = policy.openTurn(new AgentInterruptContext("t","s"),request("给孩子选可带上飞机的背包"),e -> {},eagerModel())) {
            var decision = turn.beforeTool(tool("为电竞比赛定制背包广告文案"));
            assertThat(decision.signal()).isEqualTo("periodic"); assertThat(decision.blocked()).isTrue(); assertThat(decision.status()).isEqualTo("DRIFT");
        }
    }
    @Test void failedReviewDoesNotGrantPermissionAndIsBoundedByItsOwnDeadline() throws Exception {
        var p = settings(); p.setReviewTimeoutMs(40); var entered = new CountDownLatch(1); var stopped = new CountDownLatch(1);
        try (var policy = new AgentReasoningPolicy(p,(g,r,q,c) -> {
            entered.countDown(); try { new CountDownLatch(1).await(); return new AgentSemanticDrift.Review("ALIGNED","supports_goal"); }
            catch (InterruptedException interrupted) { stopped.countDown(); throw new CancellationException(); }
        }); var turn = policy.openTurn(new AgentInterruptContext("t","s"),request("旅行背包"),e -> {},eagerModel())) {
            var decision = turn.beforeTool(tool("帐篷"));
            assertThat(entered.await(1,TimeUnit.SECONDS)).isTrue(); assertThat(stopped.await(1,TimeUnit.SECONDS)).isTrue();
            assertThat(decision.status()).isEqualTo("UNKNOWN"); assertThat(decision.reason()).isEqualTo("review_timeout"); assertThat(decision.blocked()).isTrue();
        }
    }
    @Test void driftEnforcementStopsFurtherToolsInTheSameStreamButStillAllowsAFinalAnswer() {
        var p = settings(); var reviews = new AtomicInteger(); var tools = new AtomicInteger(); var rounds = new AtomicInteger();
        try (var policy = new AgentReasoningPolicy(p,(g,r,q,c) -> { reviews.incrementAndGet(); return new AgentSemanticDrift.Review("DRIFT","unrelated_goal"); })) {
            AgentModelStreamClient model = new AgentModelStreamClient() {
                @Override public AgentReasoningPolicy reasoningPolicy() { return policy; }
                @Override public void streamAssistantEvents(String id, AgentChatRequestDTO req, java.util.function.Consumer<AgentModelStreamEvent> sink) {
                    if (rounds.incrementAndGet() == 1) { sink.accept(tool("帐篷")); sink.accept(tool("键盘")); sink.accept(tool("背包")); }
                    else sink.accept(AgentModelStreamEvent.toolUse("emit_final_answer",Map.of("blocks",List.of(Map.of("type","text","content","依据现有证据结束")))));
                }
            };
            var loop = new RsAgentLoop(new InMemoryAgentRuntimeConfigurationService(),e -> { tools.incrementAndGet(); return CompletableFuture.completedFuture(Map.of("status","SUCCESS")); },model);
            var events = new ArrayList<AgentStreamEventVO>(); var result = loop.run(request("旅行背包"),events::add);
            assertThat(result.finishReason()).isEqualTo(AgentFinishReason.FINAL_ANSWER); assertThat(tools.get()).isZero(); assertThat(reviews.get()).isEqualTo(2);
            assertThat(events).anySatisfy(e -> { assertThat(e.event()).isEqualTo("tool_result"); assertThat(((Map<?,?>)e.data().get("metadata")).get("error_code")).isEqualTo("TOOL_FINAL_ANSWER_ONLY"); });
        }
    }
    @Test void correctedQueryAndNewTurnsDoNotInheritAStaleDriftGoal() {
        var p = settings();
        try (var policy = new AgentReasoningPolicy(p,(g,r,q,c) -> new AgentSemanticDrift.Review(g.contains("帐篷") ? "ALIGNED" : "DRIFT",g.contains("帐篷") ? "supports_goal" : "unrelated_goal"))) {
            try (var first = policy.openTurn(new AgentInterruptContext("a","s"),request("旅行背包"),e -> {},eagerModel())) {
                assertThat(first.beforeTool(tool("帐篷")).blocked()).isTrue(); assertThat(first.beforeTool(tool("背包尺寸")).blocked()).isFalse();
            }
            try (var next = policy.openTurn(new AgentInterruptContext("b","s"),request("现在改选帐篷"),e -> {},eagerModel())) {
                assertThat(next.beforeTool(tool("帐篷")).blocked()).isFalse(); assertThat(next.finalAnswerOnly()).isFalse();
            }
        }
    }
    @Test void observationFailuresCannotAuthorizeAToolOrDisableTheDriftGate() {
        try (var policy = new AgentReasoningPolicy(settings(),(g,r,q,c) -> new AgentSemanticDrift.Review("DRIFT","unrelated_goal"));
             var turn = policy.openTurn(new AgentInterruptContext("t","s"),request("旅行背包"),e -> { throw new IllegalStateException("trace down"); },eagerModel())) {
            assertThat(turn.beforeTool(tool("帐篷")).blocked()).isTrue();
        }
    }
    private static AgentReasoningProperties settings() { var p = new AgentReasoningProperties(); p.setBudgetEnabled(false); return p; }
    private static AgentChatRequestDTO request(String goal) { return new AgentChatRequestDTO("s","p",goal,1,Map.of()); }
    private static AgentModelStreamEvent tool(String query) { return AgentModelStreamEvent.toolUse("recommend_candidates",Map.of("query",query)); }
    private static AgentModelStreamClient eagerModel() { return (id,req,sink) -> { throw new AssertionError("Injected reviewer should be used"); }; }
}
