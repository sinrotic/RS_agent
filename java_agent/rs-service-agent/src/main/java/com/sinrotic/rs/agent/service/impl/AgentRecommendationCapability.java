package com.sinrotic.rs.agent.service.impl;

import com.sinrotic.rs.agent.domain.AgentCapabilityDescriptor;
import com.sinrotic.rs.agent.domain.AgentCapabilityRequest;
import com.sinrotic.rs.agent.domain.AgentCapabilityResult;
import com.sinrotic.rs.agent.domain.dto.AgentChatRequestDTO;
import com.sinrotic.rs.agent.domain.vo.AgentRecommendedItemVO;
import com.sinrotic.rs.agent.service.AgentCapability;
import com.sinrotic.rs.agent.service.AgentCapabilityDefinitions;
import com.sinrotic.rs.agent.service.AgentRecommendationService;

import java.util.List;
import java.util.Map;

public class AgentRecommendationCapability implements AgentCapability {

    private final AgentRecommendationService recommendationService;

    public AgentRecommendationCapability(AgentRecommendationService recommendationService) {
        this.recommendationService = recommendationService;
    }

    @Override
    public AgentCapabilityDescriptor descriptor() {
        return AgentCapabilityDefinitions.byId("recommend");
    }

    @Override
    public AgentCapabilityResult execute(AgentCapabilityRequest request) {
        Map<String, Object> arguments = request.arguments();
        List<AgentRecommendedItemVO> items = recommendationService.recommend(new AgentChatRequestDTO(
                textArgument(arguments, "session_id", request.requestId()),
                textArgument(arguments, "profile_user_id", ""),
                textArgument(arguments, "query", ""),
                integerArgument(arguments.get("limit")),
                mapArgument(arguments.get("context"))
        ));
        return AgentCapabilityResult.success(descriptor().id(), Map.of("items", items));
    }

    private String textArgument(Map<String, Object> arguments, String key, String fallback) {
        Object value = arguments.get(key);
        return value instanceof String text && !text.isBlank() ? text : fallback;
    }

    private Integer integerArgument(Object value) {
        if (value instanceof Number number) {
            return number.intValue();
        }
        if (value instanceof String text && !text.isBlank()) {
            return Integer.valueOf(text);
        }
        return null;
    }

    @SuppressWarnings("unchecked")
    private Map<String, Object> mapArgument(Object value) {
        return value instanceof Map<?, ?> map ? (Map<String, Object>) map : Map.of();
    }
}
