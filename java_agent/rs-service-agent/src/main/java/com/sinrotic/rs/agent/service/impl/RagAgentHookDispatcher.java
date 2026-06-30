package com.sinrotic.rs.agent.service.impl;

import org.springframework.stereotype.Service;

@Service
public class RagAgentHookDispatcher extends ProfileAwareAgentLoopHookDispatcher {

    public RagAgentHookDispatcher() {
        super("rag_agent", context -> AgentLoopHookResult.proceed());
    }
}
