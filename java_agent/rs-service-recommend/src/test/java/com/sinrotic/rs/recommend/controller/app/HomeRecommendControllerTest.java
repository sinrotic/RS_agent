package com.sinrotic.rs.recommend.controller.app;

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

class HomeRecommendControllerTest {

    private MockMvc mockMvc;

    private final ObjectMapper objectMapper = new ObjectMapper();

    private HomeRecommendService homeRecommendService;

    @BeforeEach
    void setUp() {
        homeRecommendService = mock(HomeRecommendService.class);
        mockMvc = MockMvcBuilders
                .standaloneSetup(new HomeRecommendController(homeRecommendService))
                .build();
    }

    @Test
    void homeRecommendationReturnsTwentyItemConfigAndDelegatesToService() throws Exception {
        HomeRecommendVO response = new HomeRecommendVO(
                "rec_req_001",
                "sess_001",
                "home",
                "A1XYZ",
                List.of(new RecommendItemVO(
                        "B001",
                        1,
                        0.932,
                        "结合你近期关注的通勤和收纳偏好推荐",
                        List.of("itemcf_strong", "semantic"),
                        new RecommendDisplayVO("Commuter Backpack", "Backpacks", "Urban Carry", "")
                )),
                true,
                "rec_req_001:20",
                new HomeRecommendConfigVO(500, 100, 50, 20, 8)
        );
        when(homeRecommendService.recommendHome(argThat(request ->
                "sess_001".equals(request.sessionId())
                        && "home".equals(request.scene())
                        && request.pageSize() == 20
        ))).thenReturn(response);

        mockMvc.perform(post("/api/recommend/home")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(Map.of(
                                "session_id", "sess_001",
                                "scene", "home",
                                "page_size", 20,
                                "cursor", "",
                                "debug", false
                        ))))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.request_id").value("rec_req_001"))
                .andExpect(jsonPath("$.session_id").value("sess_001"))
                .andExpect(jsonPath("$.items[0].item_id").value("B001"))
                .andExpect(jsonPath("$.config.recall_pool_size").value(500))
                .andExpect(jsonPath("$.config.coarse_rank_size").value(100))
                .andExpect(jsonPath("$.config.fine_rank_size").value(50))
                .andExpect(jsonPath("$.config.final_return_size").value(20))
                .andExpect(jsonPath("$.config.first_screen_display_size").value(8));

        verify(homeRecommendService).recommendHome(argThat(request ->
                "sess_001".equals(request.sessionId())
                        && "home".equals(request.scene())
                        && request.pageSize() == 20
                        && !request.debug()
        ));
    }

    @Test
    void homeRefreshReturnsNextPageAndUsesRefreshTokenAsCursor() throws Exception {
        HomeRecommendVO response = new HomeRecommendVO(
                "rec_req_refresh_001",
                "sess_001",
                "home",
                "A1XYZ",
                List.of(new RecommendItemVO(
                        "B002",
                        1,
                        0.901,
                        "refresh candidate",
                        List.of("semantic"),
                        new RecommendDisplayVO("Travel Pouch", "Accessories", "Urban Carry", "")
                )),
                true,
                "rec_req_refresh_001:20",
                new HomeRecommendConfigVO(500, 100, 50, 20, 8)
        );
        when(homeRecommendService.recommendHome(argThat(request ->
                "sess_001".equals(request.sessionId())
                        && "home".equals(request.scene())
                        && request.pageSize() == 20
                        && "rec_req_001:20".equals(request.cursor())
        ))).thenReturn(response);

        mockMvc.perform(post("/api/recommend/home/refresh")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(Map.of(
                                "session_id", "sess_001",
                                "scene", "home",
                                "page_size", 20,
                                "refresh_token", "rec_req_001:20"
                        ))))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.request_id").value("rec_req_refresh_001"))
                .andExpect(jsonPath("$.items[0].item_id").value("B002"))
                .andExpect(jsonPath("$.next_cursor").value("rec_req_refresh_001:20"));

        verify(homeRecommendService).recommendHome(argThat(request ->
                "sess_001".equals(request.sessionId())
                        && "rec_req_001:20".equals(request.cursor())
                        && request.pageSize() == 20
        ));
    }
}
