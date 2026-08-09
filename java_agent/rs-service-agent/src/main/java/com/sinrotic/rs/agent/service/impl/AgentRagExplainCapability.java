package com.sinrotic.rs.agent.service.impl;

import com.sinrotic.rs.agent.domain.AgentCapabilityDescriptor;
import com.sinrotic.rs.agent.domain.AgentCapabilityRequest;
import com.sinrotic.rs.agent.domain.AgentCapabilityResult;
import com.sinrotic.rs.agent.service.AgentCapability;
import com.sinrotic.rs.agent.service.AgentCapabilityDefinitions;
import com.sinrotic.rs.agent.service.AgentDelegateService;

import java.util.Map;

public class AgentRagExplainCapability implements AgentCapability {

    private final AgentDelegateService delegateService;

    public AgentRagExplainCapability(AgentDelegateService delegateService) {
        this.delegateService = delegateService;
    }

    @Override
    public AgentCapabilityDescriptor descriptor() {
        return AgentCapabilityDefinitions.byId("rag-explain");
    }

    @Override
    public AgentCapabilityResult execute(AgentCapabilityRequest request) {
        Map<String, Object> result = delegateService.callAgent(request.requestId(), "rag_agent", request.arguments());
        return AgentCapabilityResult.success(descriptor().id(), result);
    }
}
