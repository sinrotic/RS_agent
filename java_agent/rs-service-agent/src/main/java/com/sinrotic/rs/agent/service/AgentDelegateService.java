package com.sinrotic.rs.agent.service;

import java.util.Map;

@FunctionalInterface
public interface AgentDelegateService {

    Map<String, Object> callAgent(String requestId, String agentName, Map<String, Object> arguments);
}
