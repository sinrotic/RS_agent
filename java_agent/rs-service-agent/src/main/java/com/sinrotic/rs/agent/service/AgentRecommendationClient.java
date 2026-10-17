package com.sinrotic.rs.agent.service;

import com.sinrotic.rs.agent.domain.dto.AgentChatRequestDTO;
import com.sinrotic.rs.agent.domain.vo.AgentRecommendedItemVO;

import java.util.List;

/** Transport boundary for the recommendation service used by the Agent capability. */
public interface AgentRecommendationClient {

    List<AgentRecommendedItemVO> recommend(AgentChatRequestDTO request);
    default AgentRecommendationDelivery recommendDelivery(AgentChatRequestDTO request) {
        return new AgentRecommendationDelivery(recommend(request), List.of());
    }
}
