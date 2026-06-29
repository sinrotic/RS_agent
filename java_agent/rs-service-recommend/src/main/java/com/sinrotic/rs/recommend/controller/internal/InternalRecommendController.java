package com.sinrotic.rs.recommend.controller.internal;

import com.sinrotic.rs.recommend.domain.dto.HomeRecommendRequestDTO;
import com.sinrotic.rs.recommend.domain.dto.InternalRecommendByProfileUserRequestDTO;
import com.sinrotic.rs.recommend.domain.dto.InternalRecommendBySessionRequestDTO;
import com.sinrotic.rs.recommend.domain.vo.HomeRecommendConfigVO;
import com.sinrotic.rs.recommend.domain.vo.HomeRecommendVO;
import com.sinrotic.rs.recommend.domain.vo.InternalRecommendTraceSummaryVO;
import com.sinrotic.rs.recommend.domain.vo.InternalRecommendVO;
import com.sinrotic.rs.recommend.service.HomeRecommendService;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * Provides recommendation results for service-to-service callers.
 */
@RestController
@RequestMapping("/internal/recommend")
public class InternalRecommendController {

    private final HomeRecommendService homeRecommendService;

    public InternalRecommendController(HomeRecommendService homeRecommendService) {
        this.homeRecommendService = homeRecommendService;
    }

    @PostMapping("/by-session")
    public InternalRecommendVO recommendBySession(@RequestBody InternalRecommendBySessionRequestDTO request) {
        InternalRecommendBySessionRequestDTO normalized = request.withDefaults();
        HomeRecommendVO homeResponse = homeRecommendService.recommendHome(new HomeRecommendRequestDTO(
                normalized.sessionId(),
                normalized.scene(),
                normalized.limit(),
                "",
                normalized.includeTrace()
        ));
        return new InternalRecommendVO(
                homeResponse.requestId(),
                homeResponse.sessionId(),
                homeResponse.profileUserId(),
                homeResponse.items(),
                buildTraceSummary(homeResponse.config(), normalized.includeTrace())
        );
    }

    @PostMapping("/by-profile-user")
    public InternalRecommendVO recommendByProfileUser(@RequestBody InternalRecommendByProfileUserRequestDTO request) {
        InternalRecommendByProfileUserRequestDTO normalized = request.withDefaults();
        HomeRecommendVO homeResponse = homeRecommendService.recommendHome(new HomeRecommendRequestDTO(
                normalized.profileUserId(),
                normalized.scene(),
                normalized.limit(),
                "",
                normalized.includeTrace()
        ));
        return new InternalRecommendVO(
                homeResponse.requestId(),
                homeResponse.sessionId(),
                homeResponse.profileUserId(),
                homeResponse.items(),
                buildTraceSummary(homeResponse.config(), normalized.includeTrace())
        );
    }

    private InternalRecommendTraceSummaryVO buildTraceSummary(HomeRecommendConfigVO config, boolean includeTrace) {
        if (!includeTrace || config == null) {
            return null;
        }
        return new InternalRecommendTraceSummaryVO(
                config.recallPoolSize(),
                config.coarseRankSize(),
                config.fineRankSize(),
                config.finalReturnSize()
        );
    }
}
