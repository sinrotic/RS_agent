package com.sinrotic.rs.recommend.service;

import com.sinrotic.rs.recommend.domain.dto.FinalRerankRequestDTO;
import com.sinrotic.rs.recommend.domain.dto.RecallRequestDTO;
import com.sinrotic.rs.recommend.domain.dto.RankStageRequestDTO;
import com.sinrotic.rs.recommend.domain.vo.PipelineRecallVO;

/**
 * Runs recommendation pipeline stages for internal diagnosis.
 */
public interface RecommendPipelineService {

    PipelineRecallVO recall(RecallRequestDTO request);

    PipelineRecallVO coarseRank(RankStageRequestDTO request);

    PipelineRecallVO fineRank(RankStageRequestDTO request);

    PipelineRecallVO finalRerank(FinalRerankRequestDTO request);
}
