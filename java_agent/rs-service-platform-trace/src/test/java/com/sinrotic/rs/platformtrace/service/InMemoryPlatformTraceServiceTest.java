package com.sinrotic.rs.platformtrace.service;

import com.sinrotic.rs.platformtrace.domain.vo.AgentSessionTraceVO;
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
}
