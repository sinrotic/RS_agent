package com.sinrotic.rs.recommend.service;

import com.sinrotic.rs.recommend.domain.dto.AgentRecommendCandidatesRequestDTO;
import com.sinrotic.rs.recommend.domain.dto.AgentRecommendToolRequestDTO;
import com.sinrotic.rs.recommend.domain.vo.AgentRecommendCandidatesVO;

/**
 * Provides recommendation candidates for JavaAgent tasks.
 */
public interface AgentRecommendService {

    AgentRecommendCandidatesVO candidates(AgentRecommendCandidatesRequestDTO request);

    AgentRecommendCandidatesVO semanticRecall(AgentRecommendToolRequestDTO request);

    AgentRecommendCandidatesVO profilePipeline(AgentRecommendToolRequestDTO request);

    AgentRecommendCandidatesVO coldFallback(AgentRecommendToolRequestDTO request);

    AgentRecommendCandidatesVO rerankCandidates(AgentRecommendToolRequestDTO request);
}
