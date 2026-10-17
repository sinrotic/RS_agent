package com.sinrotic.rs.recommend.controller.app;

import com.sinrotic.rs.recommend.domain.dto.HomeRecommendRequestDTO;
import com.sinrotic.rs.recommend.domain.dto.HomeRecommendRefreshRequestDTO;
import com.sinrotic.rs.recommend.domain.delivery.RecommendationIdentity;
import com.sinrotic.rs.recommend.domain.vo.HomeRecommendVO;
import com.sinrotic.rs.recommend.service.HomeRecommendService;
import com.sinrotic.rs.recommend.service.RecommendationSessionValidator;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RestController;

/**
 * Provides homepage recommendation results for the frontend.
 */
@RestController
@RequestMapping("/api/recommend")
public class HomeRecommendController {

    private final HomeRecommendService homeRecommendService;
    private final RecommendationSessionValidator sessions;

    public HomeRecommendController(HomeRecommendService homeRecommendService, RecommendationSessionValidator sessions) {
        this.homeRecommendService = homeRecommendService;
        this.sessions = sessions;
    }

    @PostMapping("/home")
    public HomeRecommendVO recommendHome(
            @RequestHeader("X-Account-Id") String accountId,
            @RequestHeader("X-Profile-User-Id") String profileUserId,
            @RequestBody HomeRecommendRequestDTO request
    ) {
        HomeRecommendRequestDTO normalized = request.withDefaults();
        sessions.requireActive(accountId, profileUserId, normalized.sessionId());
        return homeRecommendService.recommendHome(identity(accountId, profileUserId, normalized.sessionId()), normalized);
    }

    @PostMapping("/home/refresh")
    public HomeRecommendVO refreshHome(
            @RequestHeader("X-Account-Id") String accountId,
            @RequestHeader("X-Profile-User-Id") String profileUserId,
            @RequestBody HomeRecommendRefreshRequestDTO request
    ) {
        HomeRecommendRequestDTO normalized = request.toHomeRecommendRequest();
        sessions.requireActive(accountId, profileUserId, normalized.sessionId());
        return homeRecommendService.recommendHome(identity(accountId, profileUserId, normalized.sessionId()), normalized);
    }

    private RecommendationIdentity identity(String accountId, String profileUserId, String sessionId) {
        return new RecommendationIdentity(accountId, profileUserId, sessionId);
    }
}
