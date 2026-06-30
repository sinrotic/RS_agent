package com.sinrotic.rs.agent.service.impl;

import com.sinrotic.rs.agent.service.AgentModelStreamClient;
import com.sinrotic.rs.agent.service.AgentLoopHookDispatcher;
import com.sinrotic.rs.agent.service.AgentInterrupter;
import com.sinrotic.rs.agent.service.AgentRuntimeConfigurationService;
import com.sinrotic.rs.agent.service.AgentToolUseExecutor;

import java.util.Map;

public class RagAgentLoop extends AgentLoop {

    public RagAgentLoop(
            AgentRuntimeConfigurationService runtimeConfigurationService,
            AgentToolUseExecutor toolUseExecutor,
            AgentModelStreamClient modelStreamClient
    ) {
        this(runtimeConfigurationService, toolUseExecutor, modelStreamClient, new NoopAgentLoopHookDispatcher());
    }

    public RagAgentLoop(
            AgentRuntimeConfigurationService runtimeConfigurationService,
            AgentToolUseExecutor toolUseExecutor,
            AgentModelStreamClient modelStreamClient,
            AgentLoopHookDispatcher hookDispatcher
    ) {
        this(runtimeConfigurationService, toolUseExecutor, modelStreamClient, hookDispatcher, new InMemoryAgentInterrupter());
    }

    public RagAgentLoop(
            AgentRuntimeConfigurationService runtimeConfigurationService,
            AgentToolUseExecutor toolUseExecutor,
            AgentModelStreamClient modelStreamClient,
            AgentLoopHookDispatcher hookDispatcher,
            AgentInterrupter interrupter
    ) {
        super(
                new AgentProfile(
                        "rag_agent",
                        "Internal recommendation RAG agent for query support and candidate-scoped evidence compression.",
                        Map.of(
                                "rag_evidence_search", "rs-service-recommend",
                                "load_skill", "rs-service-agent",
                                "emit_final_answer", "rs-service-agent"
                        )
                ),
                runtimeConfigurationService,
                toolUseExecutor,
                modelStreamClient,
                hookDispatcher,
                interrupter
        );
    }
}
