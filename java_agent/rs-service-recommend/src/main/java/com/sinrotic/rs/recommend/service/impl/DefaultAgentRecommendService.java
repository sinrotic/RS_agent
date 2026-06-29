package com.sinrotic.rs.recommend.service.impl;

import com.sinrotic.rs.recommend.domain.dto.AgentRecommendCandidatesRequestDTO;
import com.sinrotic.rs.recommend.domain.dto.AgentRecommendToolRequestDTO;
import com.sinrotic.rs.recommend.domain.dto.HomeRecommendRequestDTO;
import com.sinrotic.rs.recommend.domain.vo.AgentRecommendCandidateItemVO;
import com.sinrotic.rs.recommend.domain.vo.AgentRecommendCandidatesVO;
import com.sinrotic.rs.recommend.domain.vo.HomeRecommendVO;
import com.sinrotic.rs.recommend.domain.vo.RecommendItemVO;
import com.sinrotic.rs.recommend.service.AgentRecommendService;
import com.sinrotic.rs.recommend.service.HomeRecommendService;
import org.springframework.stereotype.Service;

import java.util.List;

/**
 * Bridges agent candidate requests to the homepage recommendation pipeline.
 */
@Service
public class DefaultAgentRecommendService implements AgentRecommendService {

    private final HomeRecommendService homeRecommendService;

    public DefaultAgentRecommendService(HomeRecommendService homeRecommendService) {
        this.homeRecommendService = homeRecommendService;
    }

    @Override
    public AgentRecommendCandidatesVO candidates(AgentRecommendCandidatesRequestDTO request) {
        HomeRecommendVO homeResponse = homeRecommendService.recommendHome(new HomeRecommendRequestDTO(
                request.profileUserId(),
                request.scene(),
                request.limit(),
                "",
                true
        ).withDefaults());
        return new AgentRecommendCandidatesVO(
                homeResponse.requestId(),
                request.agentId(),
                request.taskId(),
                request.profileUserId(),
                toAgentCandidates(homeResponse.items(), List.of("profile"))
        );
    }

    @Override
    public AgentRecommendCandidatesVO semanticRecall(AgentRecommendToolRequestDTO request) {
        return runHomeBackedTool(request, "semantic", request.returnCount());
    }

    @Override
    public AgentRecommendCandidatesVO profilePipeline(AgentRecommendToolRequestDTO request) {
        return runHomeBackedTool(request, "profile", request.returnCount());
    }

    @Override
    public AgentRecommendCandidatesVO coldFallback(AgentRecommendToolRequestDTO request) {
        return runHomeBackedTool(request, "cold_fallback", request.returnCount());
    }

    @Override
    public AgentRecommendCandidatesVO rerankCandidates(AgentRecommendToolRequestDTO request) {
        return runHomeBackedTool(request, "rerank", request.returnCount());
    }

    private AgentRecommendCandidatesVO runHomeBackedTool(
            AgentRecommendToolRequestDTO request,
            String fallbackSourceTag,
            int returnCount
    ) {
        HomeRecommendVO homeResponse = homeRecommendService.recommendHome(new HomeRecommendRequestDTO(
                firstNonBlank(request.sessionId(), request.profileUserId()),
                request.scene(),
                returnCount,
                "",
                true
        ).withDefaults());
        return new AgentRecommendCandidatesVO(
                homeResponse.requestId(),
                request.agentId(),
                request.taskId(),
                request.profileUserId(),
                toAgentCandidates(homeResponse.items(), List.of(fallbackSourceTag))
        );
    }

    private List<AgentRecommendCandidateItemVO> toAgentCandidates(
            List<RecommendItemVO> items,
            List<String> fallbackSourceTags
    ) {
        return items.stream()
                .map(item -> new AgentRecommendCandidateItemVO(
                        item.itemId(),
                        item.rank(),
                        item.score(),
                        item.display() == null ? item.itemId() : item.display().title(),
                        item.display() == null ? "" : item.display().category(),
                        null,
                        null,
                        null,
                        item.sourceTags() == null || item.sourceTags().isEmpty()
                                ? fallbackSourceTags
                                : item.sourceTags(),
                        item.reason(),
                        confidenceLevel(null, null)
                ))
                .toList();
    }

    private String confidenceLevel(Double averageRating, Integer ratingNumber) {
        if (averageRating != null && ratingNumber != null && ratingNumber >= 100 && averageRating >= 4.3) {
            return "high";
        }
        if (ratingNumber != null && ratingNumber >= 20) {
            return "medium";
        }
        return "unknown";
    }

    private String firstNonBlank(String primary, String fallback) {
        if (primary != null && !primary.isBlank()) {
            return primary;
        }
        return fallback;
    }
}
