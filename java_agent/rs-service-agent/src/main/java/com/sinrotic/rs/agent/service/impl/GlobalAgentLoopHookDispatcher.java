package com.sinrotic.rs.agent.service.impl;

import com.sinrotic.rs.agent.service.AgentLoopHookDispatcher;
import org.springframework.stereotype.Service;

@Service
public class GlobalAgentLoopHookDispatcher implements AgentLoopHookDispatcher {

    @Override
    public AgentLoopHookResult dispatch(AgentLoopHookContext context) {
        return AgentLoopHookResult.proceed();
    }
}
