package com.sinrotic.rs.agent.service.impl;

import com.sinrotic.rs.agent.service.AgentModelStreamClient;
import com.sinrotic.rs.agent.service.AgentRuntimeConfigurationService;
import com.sinrotic.rs.agent.service.AgentToolUseExecutor;

import java.util.Map;
import static java.util.Map.entry;

public class RsAgentLoop extends AgentLoop {

    public RsAgentLoop(
            AgentRuntimeConfigurationService runtimeConfigurationService,
            AgentToolUseExecutor toolUseExecutor,
            AgentModelStreamClient modelStreamClient
    ) {
        super(
                new AgentProfile(
                        "rs_agent",
                        "Main recommendation agent for shopping dialogue, candidate selection, evidence use, and explanation.",
                        Map.ofEntries(
                                entry("recommend_candidates", "rs-service-recommend"),
                                entry("recommend_semantic_recall", "rs-service-recommend"),
                                entry("recommend_profile_pipeline", "rs-service-recommend"),
                                entry("recommend_cold_fallback", "rs-service-recommend"),
                                entry("recommend_rerank_candidates", "rs-service-recommend"),
                                entry("rag_support", "rs-service-search-rag"),
                                entry("catalog_card", "rs-service-catalog"),
                                entry("render_product_cards", "rs-service-agent"),
                                entry("model_chat", "rs-service-model"),
                                entry("load_skill", "rs-service-agent"),
                                entry("call_agent", "rs-service-agent"),
                                entry("emit_final_answer", "rs-service-agent")
                        )
                ),
                runtimeConfigurationService,
                toolUseExecutor,
                modelStreamClient
        );
    }
}
