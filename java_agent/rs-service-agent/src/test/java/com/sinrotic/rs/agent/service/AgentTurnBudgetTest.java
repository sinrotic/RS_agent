package com.sinrotic.rs.agent.service;

import com.sinrotic.rs.agent.config.AgentReasoningProperties;
import com.sinrotic.rs.agent.service.impl.*;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.Timeout;
import java.math.BigDecimal;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicInteger;
import static org.assertj.core.api.Assertions.*;

@Timeout(5)
class AgentTurnBudgetTest {
    @Test void parallelWorkersCannotReserveTheSameRemainingTokens() throws Exception {
        var settings = new AgentReasoningProperties(); settings.setMaxTokens(100);
        var ledger = new AgentTurnBudget(settings); var allowed = new AtomicInteger();
        try (var workers = Executors.newVirtualThreadPerTaskExecutor()) {
            var start = new CountDownLatch(1); var futures = new ArrayList<Future<?>>();
            for (int i = 0; i < 8; i++) futures.add(workers.submit(() -> {
                try { start.await(); ledger.reserve("m", "worker", 30, 20); allowed.incrementAndGet(); }
                catch (AgentModelBudgetException exhausted) { assertThat(exhausted.code()).isEqualTo("MODEL_BUDGET_EXHAUSTED"); }
                catch (InterruptedException interrupted) { throw new AssertionError(interrupted); }
            }));
            start.countDown(); for (var future : futures) future.get();
        }
        assertThat(allowed.get()).isEqualTo(2);
        assertThat(ledger.snapshot()).containsEntry("used_or_held_tokens", 100L).containsEntry("in_flight_calls", 2L);
    }

    @Test void atomicFeeReservationAndActualSettlementReleaseOnlyKnownUnusedCost() {
        var settings = priced(); settings.setMaxUsd(new BigDecimal("0.00010"));
        var ledger = new AgentTurnBudget(settings); var first = ledger.reserve("priced", "generation", 40, 10);
        assertThatThrownBy(() -> ledger.reserve("priced", "worker", 50, 10)).hasMessage("MODEL_BUDGET_EXHAUSTED");
        first.settle(usage(10,10), true);
        ledger.reserve("priced", "summary", 50,10);
        assertThat((BigDecimal)ledger.snapshot().get("used_or_held_usd")).isEqualByComparingTo("0.00008");
        assertThat((BigDecimal)ledger.snapshot().get("settled_usd")).isEqualByComparingTo("0.00002");
        assertThatThrownBy(() -> ledger.reserve("other-model", "worker", 1,1)).hasMessage("MODEL_PRICE_UNKNOWN");
    }

    @Test void missingPartialInvalidAndProvisionalUsageCannotRefundTheReservation() {
        for (var usage : List.<Map<String,Object>>of(Map.of(), Map.of("prompt_tokens", 5),
                Map.of("prompt_tokens", -1, "completion_tokens", 3), Map.of("prompt_tokens", 5.0, "completion_tokens", 3),
                Map.of("prompt_tokens", 5, "completion_tokens", 3, "total_tokens", 1))) {
            var settings = new AgentReasoningProperties(); settings.setMaxTokens(100);
            var ledger = new AgentTurnBudget(settings); ledger.reserve("m", "generation", 60,40).settle(usage, true);
            assertThat(ledger.snapshot()).containsEntry("held_tokens",100L).containsEntry("settled_tokens",0L).containsEntry("unknown_usage_calls",1L);
            assertThatThrownBy(() -> ledger.reserve("m","generation",1,1)).hasMessage("MODEL_BUDGET_EXHAUSTED");
        }
        var ledger = new AgentTurnBudget(new AgentReasoningProperties());
        ledger.reserve("m","worker",60,40).settle(usage(5,3),false);
        assertThat(ledger.snapshot()).containsEntry("held_tokens",100L);
    }

    @Test void duplicateFinalReceiptsDoNotDoubleBillAndConflictsBlockNewCalls() {
        var ledger = new AgentTurnBudget(new AgentReasoningProperties()); var call = ledger.reserve("m","worker",40,10);
        call.settle(usage(5,3),true); call.settle(usage(5,3),true);
        assertThat(ledger.snapshot()).containsEntry("settled_tokens",8L).containsEntry("receipt_conflict",false);
        call.settle(usage(8,3),true);
        assertThat(ledger.snapshot()).containsEntry("settled_tokens",8L).containsEntry("receipt_conflict",true);
        assertThatThrownBy(() -> ledger.reserve("m","worker",1,1)).hasMessage("MODEL_BUDGET_EXHAUSTED");
    }

    @Test void closedTurnsAcceptLateUsageButCannotSpendAgainAndOverrunsStayVisible() {
        var settings = new AgentReasoningProperties(); settings.setMaxTokens(100);
        var ledger = new AgentTurnBudget(settings); var call = ledger.reserve("m","generation",40,10);
        call.settle(Map.of(),false); ledger.close(); call.settle(usage(110,10),true);
        assertThat(ledger.snapshot()).containsEntry("settled_tokens",120L).containsEntry("held_tokens",0L).containsEntry("breached",true);
        assertThatThrownBy(() -> ledger.reserve("m","worker",1,1)).hasMessage("MODEL_BUDGET_CLOSED");
        assertThat(new AgentTurnBudget(settings).snapshot()).containsEntry("used_or_held_tokens",0L);
    }

    @Test void feeLimitsRequireConfiguredRatesAndUnknownPricingIsNeverReportedAsFree() {
        var settings = new AgentReasoningProperties(); settings.setMaxUsd(new BigDecimal("0.1"));
        assertThatThrownBy(() -> new AgentTurnBudget(settings)).isInstanceOf(IllegalArgumentException.class);
        var ledger = new AgentTurnBudget(new AgentReasoningProperties()); ledger.reserve("unknown","generation",10,10).settle(usage(5,3),true);
        assertThat(ledger.snapshot()).containsEntry("pricing_status","unknown").doesNotContainKey("settled_usd");
    }

    @Test void modelAttemptsShareTheSameCallLimitIncludingSummaryAndDriftChecks() {
        var settings = new AgentReasoningProperties(); settings.setMaxModelCalls(2);
        var ledger = new AgentTurnBudget(settings);
        ledger.reserve("m","summary",1,1).settle(usage(0,0),true);
        ledger.reserve("m","drift_check",1,1).settle(usage(0,0),true);
        assertThatThrownBy(() -> ledger.reserve("m","generation",1,1)).hasMessage("MODEL_BUDGET_EXHAUSTED");
    }

    private AgentReasoningProperties priced() {
        var p = new AgentReasoningProperties(); p.setPricedModel("priced");
        p.setPricingConfigured(true);
        p.setInputUsdPerMillion(BigDecimal.ONE); p.setOutputUsdPerMillion(BigDecimal.ONE); return p;
    }
    private static Map<String,Object> usage(int input, int output) { return Map.of("prompt_tokens",input,"completion_tokens",output,"total_tokens",input+output); }
}
