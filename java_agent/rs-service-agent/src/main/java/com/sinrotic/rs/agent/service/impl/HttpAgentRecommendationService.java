package com.sinrotic.rs.agent.service.impl;

import com.sinrotic.rs.agent.domain.dto.AgentChatRequestDTO;
import com.sinrotic.rs.agent.domain.vo.AgentRecommendedItemVO;
import com.sinrotic.rs.agent.service.AgentRecommendationClient;
import com.sinrotic.rs.agent.service.AgentRecommendationService;

import java.util.List;

public class HttpAgentRecommendationService implements AgentRecommendationService {

    private final AgentRecommendationClient client;

    public HttpAgentRecommendationService(AgentRecommendationClient client) {
        this.client = client;
    }

    @Override
    public List<AgentRecommendedItemVO> recommend(AgentChatRequestDTO request) {
        return client.recommend(request);
    }
}
