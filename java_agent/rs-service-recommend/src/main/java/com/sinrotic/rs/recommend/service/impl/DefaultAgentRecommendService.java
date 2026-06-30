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
                toAgentCandidates(homeResponse.items())
        );
    }

    @Override
    public AgentRecommendCandidatesVO semanticRecall(AgentRecommendToolRequestDTO request) {
        return runHomeBackedTool(request, request.returnCount());
    }

    @Override
    public AgentRecommendCandidatesVO profilePipeline(AgentRecommendToolRequestDTO request) {
        return runHomeBackedTool(request, request.returnCount());
    }

    @Override
    public AgentRecommendCandidatesVO coldFallback(AgentRecommendToolRequestDTO request) {
        return runHomeBackedTool(request, request.returnCount());
    }

    @Override
    public AgentRecommendCandidatesVO rerankCandidates(AgentRecommendToolRequestDTO request) {
        return runHomeBackedTool(request, request.returnCount());
    }

    private AgentRecommendCandidatesVO runHomeBackedTool(
            AgentRecommendToolRequestDTO request,
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
                toAgentCandidates(homeResponse.items())
        );
    }

    private List<AgentRecommendCandidateItemVO> toAgentCandidates(List<RecommendItemVO> items) {
        return items.stream()
                .map(item -> new AgentRecommendCandidateItemVO(
                        item.itemId(),
                        titleOf(item),
                        categoryOf(item),
                        null,
                        "",
                        valueOrEmpty(item.reason()),
                        valueOrEmpty(item.reason())
                ))
                .toList();
    }

    private String titleOf(RecommendItemVO item) {
        if (item.display() == null || item.display().title() == null || item.display().title().isBlank()) {
            return item.itemId();
        }
        return item.display().title();
    }

    private String categoryOf(RecommendItemVO item) {
        if (item.display() == null) {
            return "";
        }
        return valueOrEmpty(item.display().category());
    }

    private String valueOrEmpty(String value) {
        if (value == null) {
            return "";
        }
        return value;
    }

    private String firstNonBlank(String primary, String fallback) {
        if (primary != null && !primary.isBlank()) {
            return primary;
        }
        return fallback;
    }
}
