package com.sinrotic.rs.agent.service.impl;

import org.springframework.stereotype.Service;

@Service
public class RsAgentHookDispatcher extends ProfileAwareAgentLoopHookDispatcher {

    public RsAgentHookDispatcher() {
        super("rs_agent", context -> AgentLoopHookResult.proceed());
    }
}
