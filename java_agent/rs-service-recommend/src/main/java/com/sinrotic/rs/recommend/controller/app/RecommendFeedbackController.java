package com.sinrotic.rs.recommend.controller.app;

import com.sinrotic.rs.recommend.domain.dto.RecommendEventFeedbackRequestDTO;
import com.sinrotic.rs.recommend.domain.dto.RecommendExposureFeedbackRequestDTO;
import com.sinrotic.rs.recommend.domain.dto.RecommendFeedbackReversalRequestDTO;
import com.sinrotic.rs.recommend.domain.delivery.RecommendationIdentity;
import com.sinrotic.rs.recommend.domain.vo.RecommendFeedbackAckVO;
import com.sinrotic.rs.recommend.service.RecommendFeedbackService;
import com.sinrotic.rs.recommend.service.RecommendationSessionValidator;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RestController;

/**
 * Accepts recommendation feedback from app clients.
 */
@RestController
@RequestMapping("/api/recommend/feedback")
public class RecommendFeedbackController {

    private final RecommendFeedbackService recommendFeedbackService;
    private final RecommendationSessionValidator sessions;

    public RecommendFeedbackController(RecommendFeedbackService recommendFeedbackService, RecommendationSessionValidator sessions) {
        this.recommendFeedbackService = recommendFeedbackService;
        this.sessions = sessions;
    }

    @PostMapping("/exposure")
    public RecommendFeedbackAckVO exposure(
            @RequestHeader("X-Account-Id") String accountId,
            @RequestHeader("X-Profile-User-Id") String profileUserId,
            @RequestBody RecommendExposureFeedbackRequestDTO request
    ) {
        RecommendExposureFeedbackRequestDTO normalized = request.withDefaults();
        sessions.requireActive(accountId, profileUserId, normalized.sessionId());
        return recommendFeedbackService.recordExposure(
                new RecommendationIdentity(accountId, profileUserId, normalized.sessionId()), normalized);
    }

    @PostMapping("/event")
    public RecommendFeedbackAckVO event(
            @RequestHeader("X-Account-Id") String accountId,
            @RequestHeader("X-Profile-User-Id") String profileUserId,
            @RequestBody RecommendEventFeedbackRequestDTO request
    ) {
        RecommendEventFeedbackRequestDTO normalized = request.withDefaults();
        sessions.requireActive(accountId, profileUserId, normalized.sessionId());
        return recommendFeedbackService.recordEvent(
                new RecommendationIdentity(accountId, profileUserId, normalized.sessionId()), normalized);
    }

    @PostMapping("/reversal")
    public RecommendFeedbackAckVO reversal(
            @RequestHeader("X-Account-Id") String accountId,
            @RequestHeader("X-Profile-User-Id") String profileUserId,
            @RequestBody RecommendFeedbackReversalRequestDTO request
    ) {
        return recommendFeedbackService.reverse(
                new RecommendationIdentity(accountId, profileUserId, "feedback-reversal"), request);
    }
}
