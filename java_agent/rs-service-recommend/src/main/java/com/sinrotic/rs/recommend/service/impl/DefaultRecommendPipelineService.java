package com.sinrotic.rs.recommend.service.impl;

import com.sinrotic.rs.recommend.domain.dto.FinalRerankRequestDTO;
import com.sinrotic.rs.recommend.domain.dto.RecallRequestDTO;
import com.sinrotic.rs.recommend.domain.dto.RankStageRequestDTO;
import com.sinrotic.rs.recommend.domain.vo.PipelineCandidateVO;
import com.sinrotic.rs.recommend.domain.vo.PipelineRecallVO;
import com.sinrotic.rs.recommend.service.RecommendPipelineService;
import org.springframework.stereotype.Service;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;

/**
 * First-step pipeline service for internal recall diagnostics.
 */
@Service
public class DefaultRecommendPipelineService implements RecommendPipelineService {

    @Override
    public PipelineRecallVO recall(RecallRequestDTO request) {
        Map<String, Integer> sourceDistribution = buildSourceDistribution(request.sources(), request.limit());
        PipelineCandidateVO candidate = new PipelineCandidateVO(
                "B001",
                request.sources().getFirst(),
                0.81,
                null,
                null,
                null
        );
        return new PipelineRecallVO(
                "rec_req_recall_" + UUID.randomUUID(),
                "recall",
                request.limit(),
                sourceDistribution,
                List.of(candidate)
        );
    }

    @Override
    public PipelineRecallVO coarseRank(RankStageRequestDTO request) {
        List<PipelineCandidateVO> candidates = request.candidateItemIds().stream()
                .limit(request.limit())
                .map(itemId -> new PipelineCandidateVO(
                        itemId,
                        "",
                        null,
                        0.73,
                        null,
                        null
                ))
                .toList();
        return new PipelineRecallVO(
                request.requestId(),
                "coarse_rank",
                request.limit(),
                Map.of(),
                candidates
        );
    }

    @Override
    public PipelineRecallVO fineRank(RankStageRequestDTO request) {
        List<PipelineCandidateVO> candidates = request.candidateItemIds().stream()
                .limit(request.limit())
                .map(itemId -> new PipelineCandidateVO(
                        itemId,
                        "",
                        null,
                        null,
                        0.91,
                        null
                ))
                .toList();
        return new PipelineRecallVO(
                request.requestId(),
                "fine_rank",
                request.limit(),
                Map.of(),
                candidates
        );
    }

    @Override
    public PipelineRecallVO finalRerank(FinalRerankRequestDTO request) {
        List<PipelineCandidateVO> candidates = request.candidateItemIds().stream()
                .filter(itemId -> !request.excludeItemIds().contains(itemId))
                .limit(request.limit())
                .map(itemId -> new PipelineCandidateVO(
                        itemId,
                        "",
                        null,
                        null,
                        null,
                        0.95
                ))
                .toList();
        return new PipelineRecallVO(
                request.requestId(),
                "final_rerank",
                request.limit(),
                Map.of(),
                candidates
        );
    }

    private Map<String, Integer> buildSourceDistribution(List<String> sources, int limit) {
        Map<String, Integer> distribution = new LinkedHashMap<>();
        if (sources == null || sources.isEmpty()) {
            return distribution;
        }
        int baseCount = limit / sources.size();
        int remainder = limit % sources.size();
        for (int index = 0; index < sources.size(); index++) {
            distribution.put(sources.get(index), baseCount + (index < remainder ? 1 : 0));
        }
        return distribution;
    }
}
