package com.sinrotic.rs.agent.service.impl;

import org.springframework.stereotype.Service;

@Service
public class RagAgentHookDispatcher extends ProfileAwareAgentLoopHookDispatcher {

    @Override
    public boolean supportsDirectRecommendation() { return getClass() == RagAgentHookDispatcher.class; }

    public RagAgentHookDispatcher() {
        super("rag_agent", context -> AgentLoopHookResult.proceed());
    }
}
