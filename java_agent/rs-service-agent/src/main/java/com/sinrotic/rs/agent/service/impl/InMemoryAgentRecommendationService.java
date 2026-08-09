package com.sinrotic.rs.agent.service.impl;

import com.sinrotic.rs.agent.domain.dto.AgentChatRequestDTO;
import com.sinrotic.rs.agent.domain.vo.AgentRecommendedItemVO;
import com.sinrotic.rs.agent.service.AgentRecommendationService;
import java.util.List;

public class InMemoryAgentRecommendationService implements AgentRecommendationService {

    private static final List<AgentRecommendedItemVO> MOCK_ITEMS = List.of(
            new AgentRecommendedItemVO("B001", "Commuter Backpack", "Backpacks", 0.91, "匹配通勤、轻量和中价位偏好"),
            new AgentRecommendedItemVO("B002", "Travel Organizer", "Storage", 0.84, "补充收纳场景，适合搭配通勤包"),
            new AgentRecommendedItemVO("B003", "Waterproof Daypack", "Backpacks", 0.79, "强调防水和日常使用")
    );

    @Override
    public List<AgentRecommendedItemVO> recommend(AgentChatRequestDTO request) {
        int limit = Math.min(request.resolvedLimit(), MOCK_ITEMS.size());
        return MOCK_ITEMS.subList(0, limit);
    }
}
