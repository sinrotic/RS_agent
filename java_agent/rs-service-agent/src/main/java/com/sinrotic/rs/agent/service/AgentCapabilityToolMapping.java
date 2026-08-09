package com.sinrotic.rs.agent.service;

import java.util.Map;
import java.util.Optional;

/**
 * Maps model-facing tool names to the stable capability ids exposed by an Agent Runtime Profile.
 */
public final class AgentCapabilityToolMapping {

    private static final Map<String, String> CAPABILITY_BY_TOOL = Map.ofEntries(
            Map.entry("recommend_candidates", "recommend"),
            Map.entry("recommend_semantic_recall", "recommend"),
            Map.entry("recommend_profile_pipeline", "recommend"),
            Map.entry("recommend_cold_fallback", "recommend"),
            Map.entry("recommend_rerank_candidates", "recommend"),
            Map.entry("rag_support", "rag-explain"),
            Map.entry("rag_evidence_search", "rag-explain"),
            Map.entry("session_memory", "session-memory")
    );

    private AgentCapabilityToolMapping() {
    }

    public static Optional<String> capabilityForTool(String toolName) {
        return Optional.ofNullable(CAPABILITY_BY_TOOL.get(toolName));
    }
}
