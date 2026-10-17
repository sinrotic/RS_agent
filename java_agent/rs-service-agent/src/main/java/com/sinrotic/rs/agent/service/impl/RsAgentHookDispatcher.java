package com.sinrotic.rs.agent.service.impl;

import org.springframework.stereotype.Service;

@Service
public class RsAgentHookDispatcher extends ProfileAwareAgentLoopHookDispatcher {

    @Override
    public boolean supportsDirectRecommendation() { return getClass() == RsAgentHookDispatcher.class; }

    public RsAgentHookDispatcher() {
        super("rs_agent", context -> AgentLoopHookResult.proceed());
    }
}
