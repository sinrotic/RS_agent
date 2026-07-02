package com.sinrotic.rs.platformtrace.service;

import com.sinrotic.rs.platformtrace.domain.vo.AgentSessionTraceVO;
import com.sinrotic.rs.platformtrace.domain.vo.AgentRunMonitorVO;
import com.sinrotic.rs.platformtrace.domain.vo.AgentTraceEventVO;
import com.sinrotic.rs.platformtrace.domain.vo.AgentTurnVO;
import com.sinrotic.rs.platformtrace.domain.vo.PlatformInteractionEventVO;
import com.sinrotic.rs.platformtrace.domain.vo.PlatformAccountProfileVO;
import com.sinrotic.rs.platformtrace.domain.vo.PlatformSessionOverviewVO;
import com.sinrotic.rs.platformtrace.domain.vo.RecommendTraceItemVO;
import com.sinrotic.rs.platformtrace.domain.vo.RecommendTraceVO;
import com.sinrotic.rs.platformtrace.service.client.PlatformTraceDownstreamClient;
import com.sinrotic.rs.platformtrace.service.impl.InMemoryPlatformTraceService;
import org.junit.jupiter.api.Test;

import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.Optional;

import static org.assertj.core.api.Assertions.assertThat;

class InMemoryPlatformTraceServiceTest {

    @Test
    void storesAndReadsAccountRecommendAndAgentTrace() {
        InMemoryPlatformTraceService service = new InMemoryPlatformTraceService();
        service.saveAccountProfile(new PlatformAccountProfileVO(
                "acc_001",
                "A1XYZ",
                "近期偏好通勤包和收纳用品",
                List.of("Backpacks", "Storage"),
                List.of("Urban Carry")
        ));
        service.saveRecommendTrace(new RecommendTraceVO(
                "rec_req_001",
                "sess_001",
                "A1XYZ",
                "home",
                Map.of("recall", 500, "final", 20),
                Map.of("itemcf_strong", 1),
                List.of(new RecommendTraceItemVO("B001", 1, 0.932, List.of("itemcf_strong"), "命中通勤偏好"))
        ));
        service.saveAgentSessionTrace(new AgentSessionTraceVO(
                "sess_001",
                List.of(new AgentTurnVO(
                        "agent_req_001",
                        "推荐一个通勤包",
                        "可以看看 B001",
                        List.of("recommend_candidates"),
                        List.of("B001")
                ))
        ));

        assertThat(service.accountProfile("acc_001").profileUserId()).isEqualTo("A1XYZ");
        assertThat(service.recommendTrace("rec_req_001").items()).hasSize(1);
        assertThat(service.agentSessionTurns("sess_001").turns().getFirst().recommendedItemIds())
                .containsExactly("B001");
    }

    @Test
    void returnsEmptyObjectsForMissingTrace() {
        InMemoryPlatformTraceService service = new InMemoryPlatformTraceService();

        assertThat(service.accountProfile("missing").accountId()).isEqualTo("missing");
        assertThat(service.accountProfile("missing").profileUserId()).isEqualTo("");
        assertThat(service.recommendTrace("missing").requestId()).isEqualTo("missing");
        assertThat(service.recommendTrace("missing").items()).isEmpty();
        assertThat(service.agentSessionTurns("missing").sessionId()).isEqualTo("missing");
        assertThat(service.agentSessionTurns("missing").turns()).isEmpty();
    }

    @Test
    void overviewCombinesProfileAgentTurnsAndSessionRecommendationTraces() {
        InMemoryPlatformTraceService service = new InMemoryPlatformTraceService();
        service.saveAccountProfile(new PlatformAccountProfileVO(
                "acc_001",
                "A1XYZ",
                "近期偏好通勤包",
                List.of("Backpacks"),
                List.of("Urban Carry")
        ));
        service.saveAgentSessionTrace(new AgentSessionTraceVO(
                "sess_001",
                List.of(new AgentTurnVO(
                        "agent_req_001",
                        "推荐一个通勤包",
                        "可以看看 B001",
                        List.of("recommend_candidates"),
                        List.of("B001")
                ))
        ));
        service.saveRecommendTrace(new RecommendTraceVO(
                "rec_req_001",
                "sess_001",
                "A1XYZ",
                "home",
                Map.of("recall", 500, "final", 20),
                Map.of("itemcf_strong", 1),
                List.of(new RecommendTraceItemVO("B001", 1, 0.932, List.of("itemcf_strong"), "命中通勤偏好"))
        ));

        PlatformSessionOverviewVO overview = service.sessionOverview("sess_001", "acc_001", null);

        assertThat(overview.sessionId()).isEqualTo("sess_001");
        assertThat(overview.accountProfile().profileUserId()).isEqualTo("A1XYZ");
        assertThat(overview.agentTrace().turns()).hasSize(1);
        assertThat(overview.recommendTraces()).hasSize(1);
        assertThat(overview.recommendTraces().getFirst().requestId()).isEqualTo("rec_req_001");
    }

    @Test
    void pullsMissingTraceFromDownstreamClientAndCachesIt() {
        PlatformTraceDownstreamClient downstreamClient = new PlatformTraceDownstreamClient() {
            @Override
            public Optional<PlatformAccountProfileVO> fetchAccountProfile(String accountId) {
                return Optional.of(new PlatformAccountProfileVO(
                        accountId,
                        "A1XYZ",
                        "下游画像摘要",
                        List.of("Backpacks"),
                        List.of("Urban Carry")
                ));
            }

            @Override
            public Optional<RecommendTraceVO> fetchRecommendTrace(String requestId) {
                return Optional.of(new RecommendTraceVO(
                        requestId,
                        "sess_001",
                        "A1XYZ",
                        "home",
                        Map.of("final", 20),
                        Map.of("semantic", 1),
                        List.of()
                ));
            }

            @Override
            public Optional<AgentSessionTraceVO> fetchAgentSessionTrace(String sessionId) {
                return Optional.of(new AgentSessionTraceVO(
                        sessionId,
                        List.of(new AgentTurnVO("agent_req_001", "hi", "answer", List.of(), List.of()))
                ));
            }
        };
        InMemoryPlatformTraceService service = new InMemoryPlatformTraceService(downstreamClient);

        PlatformSessionOverviewVO overview = service.sessionOverview("sess_001", "acc_001", "rec_req_001");

        assertThat(overview.accountProfile().profileSummary()).isEqualTo("下游画像摘要");
        assertThat(overview.agentTrace().turns()).hasSize(1);
        assertThat(overview.recommendTraces()).hasSize(1);
        assertThat(service.recommendTrace("rec_req_001").profileUserId()).isEqualTo("A1XYZ");
    }

    @Test
    void overviewIncludesInteractionEventsAndChronologicalTimeline() {
        InMemoryPlatformTraceService service = new InMemoryPlatformTraceService();
        service.saveAgentTraceEvent(new AgentTraceEventVO(
                "agent_evt_001",
                "sess_001",
                "agent_req_001",
                "tool_result",
                "call_001",
                "recommend_candidates",
                "rs_agent",
                "spring_ai",
                "gpt-5",
                52L,
                Map.of("status", "SUCCESS"),
                Instant.parse("2026-06-29T10:00:02Z")
        ));
        service.saveInteractionEvent(new PlatformInteractionEventVO(
                "interaction_evt_001",
                "sess_001",
                "rec_req_001",
                "B001",
                "like",
                1.0,
                Instant.parse("2026-06-29T10:00:03Z"),
                Map.of("source", "mall")
        ));

        PlatformSessionOverviewVO overview = service.sessionOverview("sess_001", "acc_001", "rec_req_001");

        assertThat(overview.interactionEvents()).hasSize(1);
        assertThat(overview.interactionEvents().getFirst().eventType()).isEqualTo("like");
        assertThat(overview.timeline()).extracting("eventType")
                .containsExactly("tool_result", "like");
        assertThat(service.sessionTimeline("sess_001")).extracting("eventId")
                .containsExactly("agent_evt_001", "interaction_evt_001");
    }

    @Test
    void requestMonitorAggregatesEventsPhasesSummaryAndQualitySignals() {
        InMemoryPlatformTraceService service = new InMemoryPlatformTraceService();
        service.saveAgentSessionTrace(new AgentSessionTraceVO(
                "sess_monitor",
                List.of(
                        new AgentTurnVO("agent_req_monitor", "find shoes", "try B001", List.of("recommend_candidates"), List.of("B001")),
                        new AgentTurnVO("agent_req_other", "find bags", "try B002", List.of(), List.of("B002"))
                )
        ));
        service.saveRecommendTrace(new RecommendTraceVO(
                "rec_req_b",
                "sess_monitor",
                "A1XYZ",
                "home",
                Map.of("final", 1),
                Map.of("semantic", 1),
                List.of(new RecommendTraceItemVO("B001", 1, 0.9, List.of("semantic"), "match"))
        ));
        service.saveRecommendTrace(new RecommendTraceVO(
                "rec_req_a",
                "sess_monitor",
                "A1XYZ",
                "home",
                Map.of("final", 1),
                Map.of("itemcf", 1),
                List.of(new RecommendTraceItemVO("B002", 1, 0.8, List.of("itemcf"), "match"))
        ));
        service.saveInteractionEvent(new PlatformInteractionEventVO(
                "interaction_evt_001",
                "sess_monitor",
                "rec_req_a",
                "B001",
                "click",
                1.0,
                Instant.parse("2026-06-29T10:00:05Z"),
                Map.of()
        ));

        service.saveAgentTraceEvent(new AgentTraceEventVO(
                "agent_evt_002",
                "sess_monitor",
                "agent_req_monitor",
                "tool_result",
                "recommend",
                "success",
                "call_001",
                "recommend_candidates",
                "rs_agent",
                "openai",
                "gpt-5",
                200L,
                20,
                10,
                30,
                null,
                null,
                null,
                "recommended candidates",
                Map.of(),
                Instant.parse("2026-06-29T10:00:02Z")
        ));
        service.saveAgentTraceEvent(new AgentTraceEventVO(
                "agent_evt_001",
                "sess_monitor",
                "agent_req_monitor",
                "agent_started",
                "planning",
                "success",
                null,
                null,
                "rs_agent",
                "openai",
                "gpt-5",
                100L,
                11,
                5,
                16,
                null,
                null,
                "user asked for shoes",
                "planned recommend flow",
                Map.of(),
                Instant.parse("2026-06-29T10:00:01Z")
        ));
        service.saveAgentTraceEvent(new AgentTraceEventVO(
                "agent_evt_004",
                "sess_monitor",
                "agent_req_monitor",
                "agent_done",
                "final_answer",
                "success",
                null,
                null,
                "rs_agent",
                "openai",
                "gpt-5",
                300L,
                25,
                15,
                40,
                null,
                null,
                "candidate set",
                "final answer ready",
                Map.of("final_answer_present", true),
                Instant.parse("2026-06-29T10:00:04Z")
        ));
        service.saveAgentTraceEvent(new AgentTraceEventVO(
                "agent_evt_003",
                "sess_monitor",
                "agent_req_monitor",
                "model_error",
                "generation",
                "error",
                null,
                null,
                "rs_agent",
                "openai",
                "gpt-5",
                50L,
                7,
                0,
                7,
                "MODEL_TIMEOUT",
                "model timed out",
                "draft answer",
                null,
                Map.of(),
                Instant.parse("2026-06-29T10:00:03Z")
        ));

        AgentRunMonitorVO monitor = service.agentRequestMonitor("agent_req_monitor");

        assertThat(monitor.sessionId()).isEqualTo("sess_monitor");
        assertThat(monitor.requestId()).isEqualTo("agent_req_monitor");
        assertThat(monitor.status()).isEqualTo("failed");
        assertThat(monitor.events()).extracting("eventId")
                .containsExactly("agent_evt_001", "agent_evt_002", "agent_evt_003", "agent_evt_004");
        assertThat(monitor.summary().totalLatencyMs()).isEqualTo(650L);
        assertThat(monitor.summary().promptTokens()).isEqualTo(63);
        assertThat(monitor.summary().completionTokens()).isEqualTo(30);
        assertThat(monitor.summary().totalTokens()).isEqualTo(93);
        assertThat(monitor.summary().toolCallCount()).isEqualTo(1);
        assertThat(monitor.summary().errorCount()).isEqualTo(1);
        assertThat(monitor.summary().recommendItemCount()).isEqualTo(2);
        assertThat(monitor.summary().hasFinalAnswer()).isTrue();
        assertThat(monitor.summary().modelProvider()).isEqualTo("openai");
        assertThat(monitor.summary().modelName()).isEqualTo("gpt-5");
        assertThat(monitor.phases()).extracting("phase")
                .containsExactly("planning", "recommend", "generation", "final_answer");
        assertThat(monitor.phases()).extracting("status")
                .containsExactly("success", "success", "failed", "success");
        assertThat(monitor.phases()).extracting("eventCount")
                .containsExactly(1, 1, 1, 1);
        assertThat(monitor.qualitySignals()).containsExactly("model_error");
        assertThat(monitor.relatedTraces().agentTurnCount()).isEqualTo(2);
        assertThat(monitor.relatedTraces().recommendRequestIds()).containsExactly("rec_req_a", "rec_req_b");
        assertThat(monitor.relatedTraces().interactionEventCount()).isEqualTo(1);
    }

    @Test
    void sessionMonitorReturnsPartialEmptyViewForMissingEvents() {
        InMemoryPlatformTraceService service = new InMemoryPlatformTraceService();

        AgentRunMonitorVO monitor = service.agentSessionMonitor("sess_missing", "agent_req_missing");

        assertThat(monitor.sessionId()).isEqualTo("sess_missing");
        assertThat(monitor.requestId()).isEqualTo("agent_req_missing");
        assertThat(monitor.status()).isEqualTo("partial");
        assertThat(monitor.summary().totalLatencyMs()).isZero();
        assertThat(monitor.summary().promptTokens()).isZero();
        assertThat(monitor.summary().completionTokens()).isZero();
        assertThat(monitor.summary().totalTokens()).isZero();
        assertThat(monitor.summary().toolCallCount()).isZero();
        assertThat(monitor.summary().errorCount()).isZero();
        assertThat(monitor.summary().recommendItemCount()).isZero();
        assertThat(monitor.summary().hasFinalAnswer()).isFalse();
        assertThat(monitor.phases()).isEmpty();
        assertThat(monitor.events()).isEmpty();
        assertThat(monitor.qualitySignals()).containsExactly("partial_trace");
        assertThat(monitor.relatedTraces()).isEqualTo(com.sinrotic.rs.platformtrace.domain.vo.AgentRunRelatedTraceVO.empty());
    }

    @Test
    void monitorsReturnPartialEmptyViewForNullAndBlankIds() {
        InMemoryPlatformTraceService service = new InMemoryPlatformTraceService();

        assertThat(service.agentRequestMonitor(null).status()).isEqualTo("partial");
        assertThat(service.agentRequestMonitor(" ").status()).isEqualTo("partial");
        assertThat(service.agentSessionMonitor(null, "agent_req_missing").status()).isEqualTo("partial");
        assertThat(service.agentSessionMonitor(" ", null).status()).isEqualTo("partial");
        assertThat(service.agentSessionMonitor(null, "agent_req_missing").sessionId()).isEmpty();
        assertThat(service.agentRequestMonitor(null).requestId()).isEmpty();
    }

    @Test
    void requestMonitorTreatsLegacyDataStatusErrorAsToolError() {
        InMemoryPlatformTraceService service = new InMemoryPlatformTraceService();
        service.saveAgentTraceEvent(new AgentTraceEventVO(
                "agent_evt_legacy_error",
                "sess_legacy_error",
                "agent_req_legacy_error",
                "tool_result",
                "call_legacy",
                "recommend_candidates",
                "rs_agent",
                "openai",
                "gpt-5",
                42L,
                Map.of("status", "ERROR"),
                Instant.parse("2026-06-29T10:00:01Z")
        ));

        AgentRunMonitorVO monitor = service.agentRequestMonitor("agent_req_legacy_error");

        assertThat(monitor.status()).isEqualTo("failed");
        assertThat(monitor.summary().errorCount()).isEqualTo(1);
        assertThat(monitor.qualitySignals()).contains("tool_error");
    }

    @Test
    void agentTraceEventSupportsProducerConstructorWithNormalizedFieldsAfterCacheTokens() {
        AgentTraceEventVO event = new AgentTraceEventVO(
                "agent_evt_producer",
                "sess_producer",
                "agent_req_producer",
                "tool_result",
                "call_producer",
                "recommend_candidates",
                "rs_agent",
                "openai",
                "gpt-5",
                120L,
                10,
                5,
                15,
                2L,
                3L,
                "recommend",
                "error",
                "TOOL_ERROR",
                "tool failed",
                "input",
                "output",
                Map.of("status", "ERROR"),
                Instant.parse("2026-06-29T10:00:01Z")
        );

        assertThat(event.cacheReadInputTokens()).isEqualTo(2L);
        assertThat(event.cacheWriteInputTokens()).isEqualTo(3L);
        assertThat(event.phase()).isEqualTo("recommend");
        assertThat(event.status()).isEqualTo("error");
        assertThat(event.errorCode()).isEqualTo("TOOL_ERROR");
        assertThat(event.errorMessage()).isEqualTo("tool failed");
        assertThat(event.inputSummary()).isEqualTo("input");
        assertThat(event.outputSummary()).isEqualTo("output");
    }

    @Test
    void requestMonitorPrioritizesErrorMessageOverExplicitSuccessStatus() {
        InMemoryPlatformTraceService service = new InMemoryPlatformTraceService();
        service.saveAgentTraceEvent(new AgentTraceEventVO(
                "agent_evt_success_with_error",
                "sess_error_evidence",
                "agent_req_error_evidence",
                "model_result",
                "generation",
                "success",
                null,
                null,
                "rs_agent",
                "openai",
                "gpt-5",
                80L,
                12,
                0,
                12,
                null,
                "timeout",
                "prompt",
                null,
                Map.of(),
                Instant.parse("2026-06-29T10:00:01Z")
        ));

        AgentRunMonitorVO monitor = service.agentRequestMonitor("agent_req_error_evidence");

        assertThat(monitor.status()).isEqualTo("failed");
        assertThat(monitor.summary().errorCount()).isEqualTo(1);
        assertThat(monitor.qualitySignals()).contains("model_error");
        assertThat(monitor.events().getFirst().status()).isEqualTo("error");
    }

    @Test
    void requestMonitorTreatsErrorEventTypeWithoutExplicitStatusAsError() {
        InMemoryPlatformTraceService service = new InMemoryPlatformTraceService();
        service.saveAgentTraceEvent(new AgentTraceEventVO(
                "agent_evt_type_error",
                "sess_type_error",
                "agent_req_type_error",
                "tool_error",
                "call_type_error",
                "recommend_candidates",
                "rs_agent",
                "openai",
                "gpt-5",
                30L,
                Map.of(),
                Instant.parse("2026-06-29T10:00:01Z")
        ));

        AgentRunMonitorVO monitor = service.agentRequestMonitor("agent_req_type_error");

        assertThat(monitor.status()).isEqualTo("failed");
        assertThat(monitor.summary().errorCount()).isEqualTo(1);
        assertThat(monitor.events().getFirst().status()).isEqualTo("error");
    }

    @Test
    void sessionMonitorWithoutRequestFilterUsesLatestNonEmptyRequestId() {
        InMemoryPlatformTraceService service = new InMemoryPlatformTraceService();
        service.saveAgentTraceEvent(new AgentTraceEventVO(
                "agent_evt_old_request",
                "sess_latest_request",
                "agent_req_old",
                "agent_started",
                null,
                null,
                "rs_agent",
                "openai",
                "gpt-5",
                20L,
                Map.of(),
                Instant.parse("2026-06-29T10:00:01Z")
        ));
        service.saveAgentTraceEvent(new AgentTraceEventVO(
                "agent_evt_latest_request",
                "sess_latest_request",
                "agent_req_latest",
                "agent_done",
                null,
                null,
                "rs_agent",
                "openai",
                "gpt-5",
                20L,
                Map.of("final_answer_present", true),
                Instant.parse("2026-06-29T10:00:03Z")
        ));

        AgentRunMonitorVO monitor = service.agentSessionMonitor("sess_latest_request", null);

        assertThat(monitor.requestId()).isEqualTo("agent_req_latest");
        assertThat(monitor.events()).extracting("requestId")
                .containsExactly("agent_req_old", "agent_req_latest");
    }

    @Test
    void requestMonitorInfersModelCallPhaseForModelEventsWithoutExplicitPhase() {
        InMemoryPlatformTraceService service = new InMemoryPlatformTraceService();
        service.saveAgentTraceEvent(new AgentTraceEventVO(
                "agent_evt_model_call",
                "sess_model_call",
                "agent_req_model_call",
                "model_response",
                null,
                null,
                "rs_agent",
                "openai",
                "gpt-5",
                75L,
                Map.of(),
                Instant.parse("2026-06-29T10:00:01Z")
        ));

        AgentRunMonitorVO monitor = service.agentRequestMonitor("agent_req_model_call");

        assertThat(monitor.events().getFirst().phase()).isEqualTo("model_call");
        assertThat(monitor.phases()).extracting("phase").containsExactly("model_call");
    }

    @Test
    void requestMonitorInfersToolCallPhaseForGenericToolEventsWithoutExplicitPhase() {
        InMemoryPlatformTraceService service = new InMemoryPlatformTraceService();
        service.saveAgentTraceEvent(new AgentTraceEventVO(
                "agent_evt_tool_call",
                "sess_tool_call",
                "agent_req_tool_call",
                "tool_result",
                "call_catalog",
                "catalog_card",
                "rs_agent",
                "openai",
                "gpt-5",
                45L,
                Map.of(),
                Instant.parse("2026-06-29T10:00:01Z")
        ));

        AgentRunMonitorVO monitor = service.agentRequestMonitor("agent_req_tool_call");

        assertThat(monitor.events().getFirst().phase()).isEqualTo("tool_call");
        assertThat(monitor.phases()).extracting("phase").containsExactly("tool_call");
    }

    @Test
    void requestMonitorPrioritizesRagPhaseForRagRecommendToolsWithoutExplicitPhase() {
        InMemoryPlatformTraceService service = new InMemoryPlatformTraceService();
        service.saveAgentTraceEvent(new AgentTraceEventVO(
                "agent_evt_rag",
                "sess_rag",
                "agent_req_rag",
                "tool_result",
                "call_rag",
                "recommend_rag_support",
                "rs_agent",
                "openai",
                "gpt-5",
                55L,
                Map.of(),
                Instant.parse("2026-06-29T10:00:01Z")
        ));

        AgentRunMonitorVO monitor = service.agentRequestMonitor("agent_req_rag");

        assertThat(monitor.events().getFirst().phase()).isEqualTo("rag");
        assertThat(monitor.phases()).extracting("phase").containsExactly("rag");
    }

    @Test
    void requestMonitorInfersRecommendPhaseForRecommendToolsWithoutExplicitPhase() {
        InMemoryPlatformTraceService service = new InMemoryPlatformTraceService();
        service.saveAgentTraceEvent(new AgentTraceEventVO(
                "agent_evt_recommend",
                "sess_recommend",
                "agent_req_recommend",
                "tool_result",
                "call_recommend",
                "recommend_candidates",
                "rs_agent",
                "openai",
                "gpt-5",
                50L,
                Map.of(),
                Instant.parse("2026-06-29T10:00:01Z")
        ));

        AgentRunMonitorVO monitor = service.agentRequestMonitor("agent_req_recommend");

        assertThat(monitor.events().getFirst().phase()).isEqualTo("recommend");
        assertThat(monitor.phases()).extracting("phase").containsExactly("recommend");
    }

    @Test
    void requestMonitorPrioritizesToolNameOverModelEventType() {
        InMemoryPlatformTraceService service = new InMemoryPlatformTraceService();
        service.saveAgentTraceEvent(new AgentTraceEventVO(
                "agent_evt_tool_model",
                "sess_tool_model",
                "agent_req_tool_model",
                "model_tool_result",
                "call_catalog_model",
                "catalog_card",
                "rs_agent",
                "openai",
                "gpt-5",
                35L,
                Map.of(),
                Instant.parse("2026-06-29T10:00:01Z")
        ));

        AgentRunMonitorVO monitor = service.agentRequestMonitor("agent_req_tool_model");

        assertThat(monitor.events().getFirst().phase()).isEqualTo("tool_call");
        assertThat(monitor.phases()).extracting("phase").containsExactly("tool_call");
    }

    @Test
    void requestMonitorPrioritizesModelEventTypeOverDoneWithoutToolName() {
        InMemoryPlatformTraceService service = new InMemoryPlatformTraceService();
        service.saveAgentTraceEvent(new AgentTraceEventVO(
                "agent_evt_model_done",
                "sess_model_done",
                "agent_req_model_done",
                "model_done",
                null,
                null,
                "rs_agent",
                "openai",
                "gpt-5",
                35L,
                Map.of(),
                Instant.parse("2026-06-29T10:00:01Z")
        ));

        AgentRunMonitorVO monitor = service.agentRequestMonitor("agent_req_model_done");

        assertThat(monitor.events().getFirst().phase()).isEqualTo("model_call");
        assertThat(monitor.phases()).extracting("phase").containsExactly("model_call");
    }
}
