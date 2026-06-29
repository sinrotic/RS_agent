package com.sinrotic.rs.recommend.controller.agent;

import com.sinrotic.rs.recommend.domain.dto.AgentRecommendCandidatesRequestDTO;
import com.sinrotic.rs.recommend.domain.dto.AgentRecommendToolRequestDTO;
import com.sinrotic.rs.recommend.domain.vo.AgentRecommendCandidatesVO;
import com.sinrotic.rs.recommend.service.AgentRecommendService;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * Provides recommendation candidates for JavaAgent callers.
 */
@RestController
@RequestMapping("/agent/recommend")
public class AgentRecommendController {

    private final AgentRecommendService agentRecommendService;

    public AgentRecommendController(AgentRecommendService agentRecommendService) {
        this.agentRecommendService = agentRecommendService;
    }

    @PostMapping("/candidates")
    public AgentRecommendCandidatesVO candidates(@RequestBody AgentRecommendCandidatesRequestDTO request) {
        return agentRecommendService.candidates(request.withDefaults());
    }

    @PostMapping("/semantic-recall")
    public AgentRecommendCandidatesVO semanticRecall(@RequestBody AgentRecommendToolRequestDTO request) {
        return agentRecommendService.semanticRecall(request.withSemanticDefaults());
    }

    @PostMapping("/profile-pipeline")
    public AgentRecommendCandidatesVO profilePipeline(@RequestBody AgentRecommendToolRequestDTO request) {
        return agentRecommendService.profilePipeline(request.withProfileDefaults());
    }

    @PostMapping("/cold-fallback")
    public AgentRecommendCandidatesVO coldFallback(@RequestBody AgentRecommendToolRequestDTO request) {
        return agentRecommendService.coldFallback(request.withColdFallbackDefaults());
    }

    @PostMapping("/rerank")
    public AgentRecommendCandidatesVO rerankCandidates(@RequestBody AgentRecommendToolRequestDTO request) {
        return agentRecommendService.rerankCandidates(request.withRerankDefaults());
    }
}
