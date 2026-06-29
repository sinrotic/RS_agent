package com.sinrotic.rs.recommend.controller.internal;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.sinrotic.rs.recommend.domain.vo.HomeRecommendConfigVO;
import com.sinrotic.rs.recommend.domain.vo.HomeRecommendVO;
import com.sinrotic.rs.recommend.domain.vo.RecommendDisplayVO;
import com.sinrotic.rs.recommend.domain.vo.RecommendItemVO;
import com.sinrotic.rs.recommend.service.HomeRecommendService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import java.util.List;
import java.util.Map;

import static org.mockito.ArgumentMatchers.argThat;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

class InternalRecommendControllerTest {

    private MockMvc mockMvc;

    private final ObjectMapper objectMapper = new ObjectMapper();

    private HomeRecommendService homeRecommendService;

    @BeforeEach
    void setUp() {
        homeRecommendService = mock(HomeRecommendService.class);
        mockMvc = MockMvcBuilders
                .standaloneSetup(new InternalRecommendController(homeRecommendService))
                .build();
    }

    @Test
    void bySessionReturnsInternalRecommendationAndTraceSummary() throws Exception {
        HomeRecommendVO homeResponse = new HomeRecommendVO(
                "rec_req_002",
                "sess_001",
                "home",
                "A1XYZ",
                List.of(new RecommendItemVO(
                        "B001",
                        1,
                        0.932,
                        "来自相似历史商品和语义偏好的共同命中",
                        List.of("itemcf_strong", "semantic"),
                        new RecommendDisplayVO("Commuter Backpack", "Backpacks", "Urban Carry", "")
                )),
                false,
                "",
                new HomeRecommendConfigVO(500, 100, 50, 20, 8)
        );
        when(homeRecommendService.recommendHome(argThat(request ->
                "sess_001".equals(request.sessionId())
                        && "home".equals(request.scene())
                        && request.pageSize() == 10
                        && request.debug()
        ))).thenReturn(homeResponse);

        mockMvc.perform(post("/internal/recommend/by-session")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(Map.of(
                                "session_id", "sess_001",
                                "scene", "home",
                                "limit", 10,
                                "include_trace", true
                        ))))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.request_id").value("rec_req_002"))
                .andExpect(jsonPath("$.session_id").value("sess_001"))
                .andExpect(jsonPath("$.profile_user_id").value("A1XYZ"))
                .andExpect(jsonPath("$.items[0].item_id").value("B001"))
                .andExpect(jsonPath("$.trace_summary.recall_count").value(500))
                .andExpect(jsonPath("$.trace_summary.coarse_rank_count").value(100))
                .andExpect(jsonPath("$.trace_summary.fine_rank_count").value(50))
                .andExpect(jsonPath("$.trace_summary.final_count").value(20));

        verify(homeRecommendService).recommendHome(argThat(request ->
                "sess_001".equals(request.sessionId())
                        && "home".equals(request.scene())
                        && request.pageSize() == 10
                        && request.debug()
        ));
    }

    @Test
    void byProfileUserReturnsInternalRecommendationForKnownProfile() throws Exception {
        HomeRecommendVO homeResponse = new HomeRecommendVO(
                "rec_req_profile_001",
                "",
                "home",
                "A1XYZ",
                List.of(new RecommendItemVO(
                        "B003",
                        1,
                        0.887,
                        "profile candidate",
                        List.of("itemcf_strong"),
                        new RecommendDisplayVO("Desk Organizer", "Workspace", "Urban Carry", "")
                )),
                false,
                "",
                new HomeRecommendConfigVO(500, 100, 50, 20, 8)
        );
        when(homeRecommendService.recommendHome(argThat(request ->
                "A1XYZ".equals(request.sessionId())
                        && "home".equals(request.scene())
                        && request.pageSize() == 12
                        && request.debug()
        ))).thenReturn(homeResponse);

        mockMvc.perform(post("/internal/recommend/by-profile-user")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(Map.of(
                                "profile_user_id", "A1XYZ",
                                "scene", "home",
                                "limit", 12,
                                "include_trace", true
                        ))))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.request_id").value("rec_req_profile_001"))
                .andExpect(jsonPath("$.profile_user_id").value("A1XYZ"))
                .andExpect(jsonPath("$.items[0].item_id").value("B003"))
                .andExpect(jsonPath("$.trace_summary.final_count").value(20));

        verify(homeRecommendService).recommendHome(argThat(request ->
                "A1XYZ".equals(request.sessionId())
                        && request.pageSize() == 12
                        && request.debug()
        ));
    }
}
