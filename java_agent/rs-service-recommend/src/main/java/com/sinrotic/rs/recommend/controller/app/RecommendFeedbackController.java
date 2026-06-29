package com.sinrotic.rs.recommend.controller.app;

import com.sinrotic.rs.recommend.domain.dto.RecommendEventFeedbackRequestDTO;
import com.sinrotic.rs.recommend.domain.dto.RecommendExposureFeedbackRequestDTO;
import com.sinrotic.rs.recommend.domain.vo.RecommendFeedbackAckVO;
import com.sinrotic.rs.recommend.service.RecommendFeedbackService;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * Accepts recommendation feedback from app clients.
 */
@RestController
@RequestMapping("/api/recommend/feedback")
public class RecommendFeedbackController {

    private final RecommendFeedbackService recommendFeedbackService;

    public RecommendFeedbackController(RecommendFeedbackService recommendFeedbackService) {
        this.recommendFeedbackService = recommendFeedbackService;
    }

    @PostMapping("/exposure")
    public RecommendFeedbackAckVO exposure(@RequestBody RecommendExposureFeedbackRequestDTO request) {
        return recommendFeedbackService.recordExposure(request.withDefaults());
    }

    @PostMapping("/event")
    public RecommendFeedbackAckVO event(@RequestBody RecommendEventFeedbackRequestDTO request) {
        return recommendFeedbackService.recordEvent(request.withDefaults());
    }
}
