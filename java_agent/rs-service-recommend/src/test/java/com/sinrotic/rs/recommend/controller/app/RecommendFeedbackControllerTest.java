package com.sinrotic.rs.recommend.controller.app;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.sinrotic.rs.recommend.domain.vo.RecommendFeedbackAckVO;
import com.sinrotic.rs.recommend.service.RecommendFeedbackService;
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

class RecommendFeedbackControllerTest {

    private MockMvc mockMvc;

    private final ObjectMapper objectMapper = new ObjectMapper();

    private RecommendFeedbackService recommendFeedbackService;

    @BeforeEach
    void setUp() {
        recommendFeedbackService = mock(RecommendFeedbackService.class);
        mockMvc = MockMvcBuilders
                .standaloneSetup(new RecommendFeedbackController(recommendFeedbackService))
                .build();
    }

    @Test
    void exposureFeedbackAcknowledgesExposedItems() throws Exception {
        RecommendFeedbackAckVO response = new RecommendFeedbackAckVO("fb_exp_001", true, "exposure", 2);
        when(recommendFeedbackService.recordExposure(argThat(request ->
                "rec_req_001".equals(request.requestId())
                        && "sess_001".equals(request.sessionId())
                        && request.itemIds().contains("B001")
                        && request.itemIds().contains("B002")
        ))).thenReturn(response);

        mockMvc.perform(post("/api/recommend/feedback/exposure")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(Map.of(
                                "request_id", "rec_req_001",
                                "session_id", "sess_001",
                                "item_ids", List.of("B001", "B002"),
                                "exposed_at", 1782636400000L
                        ))))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.feedback_id").value("fb_exp_001"))
                .andExpect(jsonPath("$.accepted").value(true))
                .andExpect(jsonPath("$.feedback_type").value("exposure"))
                .andExpect(jsonPath("$.accepted_count").value(2));

        verify(recommendFeedbackService).recordExposure(argThat(request ->
                "rec_req_001".equals(request.requestId())
                        && request.itemIds().size() == 2
        ));
    }

    @Test
    void eventFeedbackAcknowledgesSingleUserEvent() throws Exception {
        RecommendFeedbackAckVO response = new RecommendFeedbackAckVO("fb_evt_001", true, "click", 1);
        when(recommendFeedbackService.recordEvent(argThat(request ->
                "rec_req_001".equals(request.requestId())
                        && "B001".equals(request.itemId())
                        && "click".equals(request.eventType())
        ))).thenReturn(response);

        mockMvc.perform(post("/api/recommend/feedback/event")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(Map.of(
                                "request_id", "rec_req_001",
                                "session_id", "sess_001",
                                "item_id", "B001",
                                "event_type", "click",
                                "event_value", 1.0,
                                "occurred_at", 1782636410000L
                        ))))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.feedback_id").value("fb_evt_001"))
                .andExpect(jsonPath("$.accepted").value(true))
                .andExpect(jsonPath("$.feedback_type").value("click"))
                .andExpect(jsonPath("$.accepted_count").value(1));

        verify(recommendFeedbackService).recordEvent(argThat(request ->
                "rec_req_001".equals(request.requestId())
                        && "B001".equals(request.itemId())
                        && "click".equals(request.eventType())
        ));
    }
}
