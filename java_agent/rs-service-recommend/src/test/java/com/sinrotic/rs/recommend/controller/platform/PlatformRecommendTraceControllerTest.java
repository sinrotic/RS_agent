package com.sinrotic.rs.recommend.controller.platform;

import com.sinrotic.rs.recommend.domain.vo.RecommendTraceItemVO;
import com.sinrotic.rs.recommend.domain.vo.RecommendTraceVO;
import com.sinrotic.rs.recommend.service.RecommendTraceService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import java.util.List;
import java.util.Map;

import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

class PlatformRecommendTraceControllerTest {

    private MockMvc mockMvc;

    private RecommendTraceService recommendTraceService;

    @BeforeEach
    void setUp() {
        recommendTraceService = mock(RecommendTraceService.class);
        mockMvc = MockMvcBuilders
                .standaloneSetup(new PlatformRecommendTraceController(recommendTraceService))
                .build();
    }

    @Test
    void getTraceReturnsRecommendationStageCountsAndItems() throws Exception {
        RecommendTraceVO trace = new RecommendTraceVO(
                "rec_req_001",
                "sess_001",
                "A1XYZ",
                "home",
                Map.of(
                        "recall_pool_size", 500,
                        "coarse_rank_size", 100,
                        "fine_rank_size", 50,
                        "final_return_size", 20
                ),
                Map.of(
                        "recall", 500,
                        "coarse_rank", 100,
                        "fine_rank", 50,
                        "final", 20
                ),
                Map.of(
                        "itemcf_strong", 1,
                        "semantic", 1
                ),
                List.of(new RecommendTraceItemVO(
                        "B001",
                        1,
                        0.932,
                        List.of("itemcf_strong", "semantic"),
                        8,
                        2,
                        "结合你近期关注的通勤和收纳偏好推荐"
                ))
        );
        when(recommendTraceService.getTrace("rec_req_001")).thenReturn(trace);

        mockMvc.perform(get("/api/platform/recommend/rec_req_001/trace"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.request_id").value("rec_req_001"))
                .andExpect(jsonPath("$.stage_counts.recall").value(500))
                .andExpect(jsonPath("$.stage_counts.coarse_rank").value(100))
                .andExpect(jsonPath("$.stage_counts.fine_rank").value(50))
                .andExpect(jsonPath("$.stage_counts.final").value(20))
                .andExpect(jsonPath("$.items[0].item_id").value("B001"))
                .andExpect(jsonPath("$.items[0].final_rank").value(1));
    }
}
