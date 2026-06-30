package com.sinrotic.rs.agent.service.impl;

import com.sinrotic.rs.agent.service.AgentLoopHookDispatcher;
import com.sinrotic.rs.agent.service.AgentProfileHookDispatcher;

public class ProfileAwareAgentLoopHookDispatcher implements AgentProfileHookDispatcher {

    private final String agentName;

    private final AgentLoopHookDispatcher delegate;

    public ProfileAwareAgentLoopHookDispatcher(String agentName, AgentLoopHookDispatcher delegate) {
        this.agentName = agentName;
        this.delegate = delegate;
    }

    @Override
    public boolean supports(String agentName) {
        return this.agentName.equals(agentName);
    }

    @Override
    public AgentLoopHookResult dispatch(AgentLoopHookContext context) {
        return delegate.dispatch(context);
    }
}
