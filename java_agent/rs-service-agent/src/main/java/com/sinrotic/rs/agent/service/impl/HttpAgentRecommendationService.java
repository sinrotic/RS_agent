package com.sinrotic.rs.agent.service.impl;

import com.sinrotic.rs.agent.domain.dto.AgentChatRequestDTO;
import com.sinrotic.rs.agent.domain.vo.AgentRecommendedItemVO;
import com.sinrotic.rs.agent.service.AgentRecommendationClient;
import com.sinrotic.rs.agent.service.AgentRecommendationService;

import java.util.List;

public class HttpAgentRecommendationService implements AgentRecommendationService {

    private static final org.slf4j.Logger log = org.slf4j.LoggerFactory.getLogger(HttpAgentRecommendationService.class);

    private final AgentRecommendationClient client;

    public HttpAgentRecommendationService(AgentRecommendationClient client) {
        this.client = client;
    }

    @Override
    public List<AgentRecommendedItemVO> recommend(AgentChatRequestDTO request) {
        return client.recommend(request);
    }
    @Override
    public com.sinrotic.rs.agent.service.AgentRecommendationDelivery recommendDelivery(AgentChatRequestDTO request) {
        try {
            return client.recommendDelivery(request);
        } catch (IllegalStateException unavailable) {
            log.warn("推荐交付不可用，本轮返回无商品降级结果");
            return new com.sinrotic.rs.agent.service.AgentRecommendationDelivery(List.of(), List.of("recommendation_unavailable"));
        }
    }
}
