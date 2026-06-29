package com.sinrotic.rs.recommend.service.impl;

import com.sinrotic.rs.recommend.domain.dto.HomeRecommendRequestDTO;
import com.sinrotic.rs.recommend.domain.vo.HomeRecommendConfigVO;
import com.sinrotic.rs.recommend.domain.vo.HomeRecommendVO;
import com.sinrotic.rs.recommend.domain.vo.RecommendDisplayVO;
import com.sinrotic.rs.recommend.domain.vo.RecommendItemVO;
import com.sinrotic.rs.recommend.domain.vo.RecommendTraceItemVO;
import com.sinrotic.rs.recommend.domain.vo.RecommendTraceVO;
import com.sinrotic.rs.recommend.service.HomeRecommendService;
import com.sinrotic.rs.recommend.service.RecommendTraceService;
import org.springframework.stereotype.Service;

import java.util.List;
import java.util.Map;
import java.util.UUID;

/**
 * First-step implementation for the homepage API.
 *
 * The model serving boundary stays behind this service: later iterations should replace
 * the sample item assembly with calls to rs-service-model and the recommendation pipeline.
 */
@Service
public class DefaultHomeRecommendService implements HomeRecommendService {

    private static final HomeRecommendConfigVO HOME_CONFIG = new HomeRecommendConfigVO(500, 100, 50, 20, 8);

    private final RecommendTraceService recommendTraceService;

    public DefaultHomeRecommendService(RecommendTraceService recommendTraceService) {
        this.recommendTraceService = recommendTraceService;
    }

    @Override
    public HomeRecommendVO recommendHome(HomeRecommendRequestDTO request) {
        String requestId = "rec_req_" + UUID.randomUUID();
        RecommendItemVO item = new RecommendItemVO(
                "B001",
                1,
                0.932,
                "结合你近期关注的通勤和收纳偏好推荐",
                List.of("itemcf_strong", "semantic"),
                new RecommendDisplayVO("Commuter Backpack", "Backpacks", "Urban Carry", "")
        );
        HomeRecommendVO response = new HomeRecommendVO(
                requestId,
                request.sessionId(),
                request.scene(),
                "",
                List.of(item),
                false,
                "",
                HOME_CONFIG
        );
        recommendTraceService.saveTrace(buildTrace(response));
        return response;
    }

    private RecommendTraceVO buildTrace(HomeRecommendVO response) {
        return new RecommendTraceVO(
                response.requestId(),
                response.sessionId(),
                response.profileUserId(),
                response.scene(),
                Map.of(
                        "recall_pool_size", HOME_CONFIG.recallPoolSize(),
                        "coarse_rank_size", HOME_CONFIG.coarseRankSize(),
                        "fine_rank_size", HOME_CONFIG.fineRankSize(),
                        "final_return_size", HOME_CONFIG.finalReturnSize()
                ),
                Map.of(
                        "recall", HOME_CONFIG.recallPoolSize(),
                        "coarse_rank", HOME_CONFIG.coarseRankSize(),
                        "fine_rank", HOME_CONFIG.fineRankSize(),
                        "final", HOME_CONFIG.finalReturnSize()
                ),
                Map.of(
                        "itemcf_strong", 1,
                        "semantic", 1
                ),
                response.items().stream()
                        .map(item -> new RecommendTraceItemVO(
                                item.itemId(),
                                item.rank(),
                                item.score(),
                                item.sourceTags(),
                                1,
                                1,
                                item.reason()
                        ))
                        .toList()
        );
    }
}
