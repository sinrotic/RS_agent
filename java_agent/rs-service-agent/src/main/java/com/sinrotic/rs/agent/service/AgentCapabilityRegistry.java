package com.sinrotic.rs.agent.service;

import com.sinrotic.rs.agent.domain.AgentCapabilityDescriptor;
import com.sinrotic.rs.agent.domain.AgentCapabilityRequest;
import com.sinrotic.rs.agent.domain.AgentCapabilityResult;
import com.sinrotic.rs.agent.domain.AgentRuntimeProfile;

import java.util.List;

public interface AgentCapabilityRegistry {

    void register(AgentCapability capability);

    List<AgentCapabilityDescriptor> descriptors();

    AgentCapabilityResult execute(AgentRuntimeProfile profile, AgentCapabilityRequest request);
}
