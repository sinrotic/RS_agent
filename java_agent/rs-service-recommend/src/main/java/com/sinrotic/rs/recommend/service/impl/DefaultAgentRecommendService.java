package com.sinrotic.rs.recommend.service.impl;

import com.sinrotic.rs.recommend.domain.dto.AgentRecommendCandidatesRequestDTO;
import com.sinrotic.rs.recommend.domain.dto.AgentRecommendToolRequestDTO;
import com.sinrotic.rs.recommend.domain.dto.HomeRecommendRequestDTO;
import com.sinrotic.rs.recommend.domain.delivery.RecommendationIdentity;
import com.sinrotic.rs.recommend.domain.vo.AgentRecommendCandidateItemVO;
import com.sinrotic.rs.recommend.domain.vo.AgentRecommendCandidatesVO;
import com.sinrotic.rs.recommend.domain.vo.HomeRecommendVO;
import com.sinrotic.rs.recommend.domain.vo.RecommendItemVO;
import com.sinrotic.rs.recommend.service.AgentRecommendService;
import com.sinrotic.rs.recommend.service.HomeRecommendService;
import com.sinrotic.rs.recommend.service.SemanticItemRecallProvider;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

import java.util.List;
import java.util.Map;

/**
 * Bridges agent candidate requests to the homepage recommendation pipeline.
 */
@Service
public class DefaultAgentRecommendService implements AgentRecommendService {

    private final HomeRecommendService homeRecommendService;
    private final SemanticItemRecallProvider semanticItemRecallProvider;
    private TrainedAgentCandidateRanker trainedRanker;

    @Autowired
    public void setTrainedAgentRanker(TrainedAgentCandidateRanker ranker) { this.trainedRanker = ranker; }

    public DefaultAgentRecommendService(HomeRecommendService homeRecommendService) {
        this(homeRecommendService, null);
    }

    @Autowired
    public DefaultAgentRecommendService(
            HomeRecommendService homeRecommendService,
            SemanticItemRecallProvider semanticItemRecallProvider
    ) {
        this.homeRecommendService = homeRecommendService;
        this.semanticItemRecallProvider = semanticItemRecallProvider;
    }

    @Override
    public AgentRecommendCandidatesVO candidates(AgentRecommendCandidatesRequestDTO request) {
        AgentRecommendationBudget.from(request.constraints());
        HomeRecommendVO homeResponse = homeRecommendService.recommendHome(new RecommendationIdentity(
                request.accountId(), request.profileUserId(), request.taskId()
        ), new HomeRecommendRequestDTO(
                request.taskId(),
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
                filterCandidatesForAgent(toAgentCandidates(homeResponse.items()), request.constraints())
        );
    }

    @Override
    public AgentRecommendCandidatesVO semanticRecall(AgentRecommendToolRequestDTO request) {
        if (semanticItemRecallProvider == null || request.query() == null || request.query().isBlank()) {
            return runHomeBackedTool(request, request.returnCount());
        }
        String requestId = "rec_req_semantic_" + java.util.UUID.randomUUID();
        AgentRecommendationBudget.from(request.constraints());
        List<com.sinrotic.rs.recommend.domain.recall.ItemEmbeddingText> recalled;
        try { recalled = semanticItemRecallProvider.recall(requestId,request.query(),request.recallLimit()); }
        catch (RuntimeException error) { return runHomeBackedTool(request,request.returnCount()); }
        if (recalled.isEmpty()) return runHomeBackedTool(request,request.returnCount());
        if (trainedRanker==null) throw new IllegalStateException("Agent 候选处理器未配置");
        // 仅召回失败允许回退；偏好读取或交付失败必须保留原错误。
        return trainedRanker.rank(request,recalled,"semantic");
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
        if (trainedRanker == null || !trainedRanker.trainedRankingEnabled()) throw new org.springframework.web.server.ResponseStatusException(
                org.springframework.http.HttpStatus.SERVICE_UNAVAILABLE,"训练排序未启用");
        return trainedRanker.rerank(request);
    }

    private AgentRecommendCandidatesVO runHomeBackedTool(
            AgentRecommendToolRequestDTO request,
            int returnCount
    ) {
        AgentRecommendationBudget.from(request.constraints());
        String sessionId = firstNonBlank(request.sessionId(), request.taskId());
        HomeRecommendVO homeResponse = homeRecommendService.recommendHome(new RecommendationIdentity(
                request.accountId(), request.profileUserId(), sessionId
        ), new HomeRecommendRequestDTO(
                sessionId,
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
                filterCandidatesForAgent(toAgentCandidates(homeResponse.items()), request.constraints())
        );
    }

    public List<AgentRecommendCandidateItemVO> filterCandidatesForAgent(
            List<AgentRecommendCandidateItemVO> candidates,
            Map<String, Object> constraints
    ) {
        var budget = AgentRecommendationBudget.from(constraints);
        return candidates.stream()
                .filter(candidate -> budget.matches(candidate.price()))
                .toList();
    }

    private List<AgentRecommendCandidateItemVO> toAgentCandidates(List<RecommendItemVO> items) {
        return items.stream()
                .map(item -> new AgentRecommendCandidateItemVO(
                        item.itemId(),
                        titleOf(item),
                        categoryOf(item),
                        item.display()==null ? null : item.display().price(),
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
