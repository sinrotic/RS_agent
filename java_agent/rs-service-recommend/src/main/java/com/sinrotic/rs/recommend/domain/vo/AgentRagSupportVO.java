package com.sinrotic.rs.recommend.domain.vo;

import com.fasterxml.jackson.annotation.JsonProperty;

import java.util.List;

public record AgentRagSupportVO(
        @JsonProperty("request_id")
        String requestId,
        @JsonProperty("query_rewrite")
        String queryRewrite,
        @JsonProperty("candidate_scoped")
        boolean candidateScoped,
        List<String> providers,
        @JsonProperty("item_support")
        List<RagItemSupportVO> itemSupport,
        @JsonProperty("comparison_points")
        List<String> comparisonPoints,
        @JsonProperty("agent_context")
        RagAgentContextVO agentContext,
        RagGovernanceVO governance
) {
    public AgentRagSupportVO {
        providers = providers == null ? List.of() : List.copyOf(providers);
        itemSupport = itemSupport == null ? List.of() : List.copyOf(itemSupport);
        comparisonPoints = comparisonPoints == null ? List.of() : List.copyOf(comparisonPoints);
    }
}
