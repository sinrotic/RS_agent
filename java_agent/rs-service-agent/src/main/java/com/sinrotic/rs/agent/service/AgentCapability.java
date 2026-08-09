package com.sinrotic.rs.agent.service;

import com.sinrotic.rs.agent.domain.AgentCapabilityDescriptor;
import com.sinrotic.rs.agent.domain.AgentCapabilityRequest;
import com.sinrotic.rs.agent.domain.AgentCapabilityResult;

public interface AgentCapability {

    AgentCapabilityDescriptor descriptor();

    AgentCapabilityResult execute(AgentCapabilityRequest request);
}
