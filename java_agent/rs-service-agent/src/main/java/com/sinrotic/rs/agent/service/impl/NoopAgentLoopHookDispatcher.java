package com.sinrotic.rs.agent.service.impl;

import com.sinrotic.rs.agent.service.AgentLoopHookDispatcher;
import org.springframework.stereotype.Service;

@Service
public class NoopAgentLoopHookDispatcher implements AgentLoopHookDispatcher {

    @Override
    public boolean supportsDirectRecommendation() { return getClass() == NoopAgentLoopHookDispatcher.class; }

    @Override
    public AgentLoopHookResult dispatch(AgentLoopHookContext context) {
        return AgentLoopHookResult.proceed();
    }
}
