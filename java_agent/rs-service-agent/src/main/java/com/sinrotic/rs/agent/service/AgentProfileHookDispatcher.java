package com.sinrotic.rs.agent.service;

import com.sinrotic.rs.agent.service.impl.AgentLoopHookContext;
import com.sinrotic.rs.agent.service.impl.AgentLoopHookResult;

public interface AgentProfileHookDispatcher {

    boolean supports(String agentName);

    AgentLoopHookResult dispatch(AgentLoopHookContext context);
}
