package com.sinrotic.rs.recommend.service.impl;

import com.sinrotic.rs.recommend.domain.dto.FinalRerankRequestDTO;
import com.sinrotic.rs.recommend.domain.dto.RecallRequestDTO;
import com.sinrotic.rs.recommend.domain.dto.RankStageRequestDTO;
import com.sinrotic.rs.recommend.domain.vo.PipelineCandidateVO;
import com.sinrotic.rs.recommend.domain.vo.PipelineRecallVO;
import com.sinrotic.rs.recommend.service.RecommendPipelineService;
import com.sinrotic.rs.recommend.service.TwoTowerRecallProvider;
import com.sinrotic.rs.recommend.service.MultiSourceRecallProvider;
import com.sinrotic.rs.recommend.service.UserHistoryClient;
import com.sinrotic.rs.recommend.service.TrainedRankingClient;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;

/**
 * First-step pipeline service for internal recall diagnostics.
 */
@Service
public class DefaultRecommendPipelineService implements RecommendPipelineService {

    private final TwoTowerRecallProvider twoTowerRecallProvider;
    private MultiSourceRecallProvider multiRecall;
    private UserHistoryClient history;
    private TrainedRankingClient ranking;

    @Autowired(required = false)
    public void setTrainedRankingClient(TrainedRankingClient ranking) { this.ranking = ranking; }

    @Autowired(required = false)
    public void setMultiRecall(MultiSourceRecallProvider provider, UserHistoryClient history) {
        this.multiRecall = provider;
        this.history = history;
    }

    public DefaultRecommendPipelineService() {
        this((TwoTowerRecallProvider) null);
    }

    public DefaultRecommendPipelineService(TwoTowerRecallProvider twoTowerRecallProvider) {
        this.twoTowerRecallProvider = twoTowerRecallProvider;
    }

    @Autowired
    public DefaultRecommendPipelineService(ObjectProvider<TwoTowerRecallProvider> twoTowerRecallProvider) {
        this(twoTowerRecallProvider.getIfAvailable());
    }

    @Override
    public PipelineRecallVO recall(RecallRequestDTO request) {
        Map<String, Integer> sourceDistribution = buildSourceDistribution(request.sources(), request.limit());
        List<PipelineCandidateVO> candidates = new ArrayList<>();
        if (request.sources().contains("two_tower") && twoTowerRecallProvider != null) {
            candidates.addAll(twoTowerRecallProvider.recall(request.profileUserId(), "rec_req_recall", request.limit()));
            sourceDistribution.put("two_tower", candidates.size());
        }
        if (multiRecall != null) {
            var requested = request.sources().stream().filter(MultiSourceRecallProvider.SOURCES::contains).toList();
            if (!requested.isEmpty()) {
                var recalled = multiRecall.recall(request.profileUserId(), history.recentItemIds(request.profileUserId(), 20), requested,
                        Math.max(1,Math.min(120,request.limit())));
                recalled.forEach((source, rows) -> { candidates.addAll(rows); sourceDistribution.put(source, rows.size()); });
            }
        }
        // 总预算按来源交错截断，数量来自最后实际返回的候选。
        var bySource = new LinkedHashMap<String, List<PipelineCandidateVO>>();
        for (var candidate : candidates) bySource.computeIfAbsent(candidate.source(), key -> new ArrayList<>()).add(candidate);
        var selected = new ArrayList<PipelineCandidateVO>();
        int budget = Math.max(1, request.limit());
        for (int index = 0; index < budget && selected.size() < budget; index++) {
            for (var pool : bySource.values()) if (index < pool.size() && selected.size() < budget) selected.add(pool.get(index));
        }
        sourceDistribution.replaceAll((key, value) -> 0);
        selected.forEach(candidate -> sourceDistribution.merge(candidate.source(), 1, Integer::sum));
        return new PipelineRecallVO(
                "rec_req_recall_" + UUID.randomUUID(),
                "recall",
                selected.size(),
                sourceDistribution,
                selected
        );
    }

    @Override
    public PipelineRecallVO coarseRank(RankStageRequestDTO request) {
        return rankStage(request.requestId(), request.profileUserId(), request.candidateItemIds(), "coarse", request.limit());
    }

    @Override
    public PipelineRecallVO fineRank(RankStageRequestDTO request) {
        return rankStage(request.requestId(), request.profileUserId(), request.candidateItemIds(), "fine", request.limit());
    }

    @Override
    public PipelineRecallVO finalRerank(FinalRerankRequestDTO request) {
        return rankStage(request.requestId(), request.profileUserId(), request.candidateItemIds().stream()
                .filter(id -> !request.excludeItemIds().contains(id)).toList(), "final", request.limit());
    }

    private PipelineRecallVO rankStage(String requestId, String user, List<String> ids, String stage, int limit) {
        if (ranking == null) throw new org.springframework.web.server.ResponseStatusException(
                org.springframework.http.HttpStatus.SERVICE_UNAVAILABLE, "trained ranking unavailable");
        var result = ranking.rank(user, ids.stream().distinct().limit(500).toList(), List.of(),
                stage.equals("coarse") ? "coarse" : "fine", Math.max(1,Math.min(500,limit)), Math.max(1,Math.min(500,limit)));
        var candidates = result.items().stream().map(item -> new PipelineCandidateVO(item.itemId(), "", null,
                item.coldScore(), item.deepfmLogit(), item.score())).toList();
        return new PipelineRecallVO(requestId, stage.equals("final") ? "final_rerank" : stage + "_rank",
                candidates.size(), Map.of(), candidates);
    }

    private Map<String, Integer> buildSourceDistribution(List<String> sources, int limit) {
        Map<String, Integer> distribution = new LinkedHashMap<>();
        if (sources == null || sources.isEmpty()) {
            return distribution;
        }
        sources.forEach(source -> distribution.put(source, 0));
        return distribution;
    }
}
