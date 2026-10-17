package com.sinrotic.rs.agent.service;

import com.sinrotic.rs.agent.domain.vo.AgentRecommendedItemVO;
import java.util.List;
import java.util.Map;

public record AgentRecommendationDelivery(List<AgentRecommendedItemVO> items, List<String> degradationReasons,
                                          Map<String, AgentRecommendationFact> facts, boolean degraded) {
    public AgentRecommendationDelivery {
        items = List.copyOf(items);
        degraded = degraded || (degradationReasons != null && !degradationReasons.isEmpty());
        degradationReasons = publicReasons(degradationReasons);
        facts = facts == null ? Map.of() : Map.copyOf(facts);
    }

    public AgentRecommendationDelivery(List<AgentRecommendedItemVO> items, List<String> degradationReasons) {
        this(items, degradationReasons, Map.of());
    }

    public AgentRecommendationDelivery(List<AgentRecommendedItemVO> items, List<String> degradationReasons,
                                       Map<String, AgentRecommendationFact> facts) {
        this(items, degradationReasons, facts, false);
    }

    public static List<String> publicReasons(Object raw) {
        if (!(raw instanceof List<?> reasons)) return List.of();
        var allowed = java.util.Set.of("trained_ranking_unavailable", "model_rank_unavailable", "recommendation_unavailable");
        return reasons.stream().filter(String.class::isInstance).map(String.class::cast)
                .filter(allowed::contains).distinct().toList();
    }
}
