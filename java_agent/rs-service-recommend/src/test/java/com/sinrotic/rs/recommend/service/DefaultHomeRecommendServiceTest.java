package com.sinrotic.rs.recommend.service;

import com.sinrotic.rs.recommend.domain.dto.HomeRecommendRequestDTO;
import com.sinrotic.rs.recommend.domain.vo.HomeRecommendVO;
import com.sinrotic.rs.recommend.domain.vo.RecommendTraceVO;
import com.sinrotic.rs.recommend.service.impl.DefaultHomeRecommendService;
import com.sinrotic.rs.recommend.service.impl.InMemoryRecommendTraceService;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;

class DefaultHomeRecommendServiceTest {

    @Test
    void recommendHomeStoresTraceForGeneratedRequestId() {
        RecommendTraceService traceService = new InMemoryRecommendTraceService();
        DefaultHomeRecommendService homeRecommendService = new DefaultHomeRecommendService(traceService);

        HomeRecommendVO response = homeRecommendService.recommendHome(new HomeRecommendRequestDTO(
                "sess_001",
                "home",
                20,
                "",
                false
        ));

        RecommendTraceVO trace = traceService.getTrace(response.requestId());
        assertNotNull(trace);
        assertEquals(response.requestId(), trace.requestId());
        assertEquals("sess_001", trace.sessionId());
        assertEquals(500, trace.stageCounts().get("recall"));
        assertEquals(100, trace.stageCounts().get("coarse_rank"));
        assertEquals(50, trace.stageCounts().get("fine_rank"));
        assertEquals(20, trace.stageCounts().get("final"));
    }
}
