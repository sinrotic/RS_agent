package com.sinrotic.rs.recommend.controller.internal;

import com.sinrotic.rs.recommend.domain.dto.FinalRerankRequestDTO;
import com.sinrotic.rs.recommend.domain.dto.RecallRequestDTO;
import com.sinrotic.rs.recommend.domain.dto.RankStageRequestDTO;
import com.sinrotic.rs.recommend.domain.vo.PipelineRecallVO;
import com.sinrotic.rs.recommend.service.RecommendPipelineService;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * Exposes internal recommendation pipeline stages for diagnosis.
 */
@RestController
@RequestMapping("/internal/recommend/pipeline")
public class InternalRecommendPipelineController {

    private final RecommendPipelineService recommendPipelineService;

    public InternalRecommendPipelineController(RecommendPipelineService recommendPipelineService) {
        this.recommendPipelineService = recommendPipelineService;
    }

    @PostMapping("/recall")
    public PipelineRecallVO recall(@RequestBody RecallRequestDTO request) {
        return recommendPipelineService.recall(request.withDefaults());
    }

    @PostMapping("/coarse-rank")
    public PipelineRecallVO coarseRank(@RequestBody RankStageRequestDTO request) {
        return recommendPipelineService.coarseRank(request.withDefaults());
    }

    @PostMapping("/fine-rank")
    public PipelineRecallVO fineRank(@RequestBody RankStageRequestDTO request) {
        return recommendPipelineService.fineRank(request.withDefaults());
    }

    @PostMapping("/final-rerank")
    public PipelineRecallVO finalRerank(@RequestBody FinalRerankRequestDTO request) {
        return recommendPipelineService.finalRerank(request.withDefaults());
    }
}
