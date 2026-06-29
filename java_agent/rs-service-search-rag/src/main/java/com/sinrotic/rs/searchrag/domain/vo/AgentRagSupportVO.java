package com.sinrotic.rs.searchrag.domain.vo;

import com.fasterxml.jackson.annotation.JsonProperty;

import java.util.List;

/**
 * Agent-facing RAG grounding context.
 */
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
}
