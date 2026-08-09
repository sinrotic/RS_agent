package com.sinrotic.rs.agent.service.impl;

import com.sinrotic.rs.agent.domain.AgentCapabilityDescriptor;
import com.sinrotic.rs.agent.domain.AgentCapabilityAuditEvent;
import com.sinrotic.rs.agent.domain.AgentCapabilityRequest;
import com.sinrotic.rs.agent.domain.AgentCapabilityResult;
import com.sinrotic.rs.agent.domain.AgentRuntimeProfile;
import com.sinrotic.rs.agent.service.AgentCapability;
import com.sinrotic.rs.agent.service.AgentCapabilityAuditSink;
import com.sinrotic.rs.agent.service.AgentCapabilityRegistry;

import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ConcurrentMap;
import java.time.Instant;

public class InMemoryAgentCapabilityRegistry implements AgentCapabilityRegistry {

    private final ConcurrentMap<String, AgentCapability> capabilities = new ConcurrentHashMap<>();

    private final AgentCapabilityAuditSink auditSink;

    public InMemoryAgentCapabilityRegistry() {
        this(event -> {
        });
    }

    public InMemoryAgentCapabilityRegistry(AgentCapabilityAuditSink auditSink) {
        this.auditSink = auditSink == null ? event -> {
        } : auditSink;
    }

    @Override
    public void register(AgentCapability capability) {
        if (capability == null || capability.descriptor() == null) {
            throw new IllegalArgumentException("capability and descriptor must not be null");
        }
        String id = capability.descriptor().id();
        if (capabilities.putIfAbsent(id, capability) != null) {
            throw new IllegalArgumentException("duplicate capability: " + id);
        }
    }

    @Override
    public List<AgentCapabilityDescriptor> descriptors() {
        List<AgentCapabilityDescriptor> descriptors = new ArrayList<>();
        capabilities.values().stream()
                .map(AgentCapability::descriptor)
                .sorted(Comparator.comparing(AgentCapabilityDescriptor::id))
                .forEach(descriptors::add);
        return List.copyOf(descriptors);
    }

    @Override
    public AgentCapabilityResult execute(AgentRuntimeProfile profile, AgentCapabilityRequest request) {
        if (profile == null) {
            return record(request, AgentCapabilityResult.failure(request.capabilityId(), "PROFILE_REQUIRED", "agent runtime profile is required"));
        }
        if (!profile.id().equals(request.profileId())) {
            return record(request, AgentCapabilityResult.failure(request.capabilityId(), "CAPABILITY_PROFILE_MISMATCH",
                    "capability request profile does not match runtime profile"));
        }
        AgentCapability capability = capabilities.get(request.capabilityId());
        if (capability == null) {
            return record(request, AgentCapabilityResult.failure(request.capabilityId(), "CAPABILITY_NOT_REGISTERED",
                    "capability is not registered: " + request.capabilityId()));
        }
        AgentCapabilityDescriptor descriptor = capability.descriptor();
        if (!profile.allowedCapabilities().contains(descriptor.id())) {
            return record(request, AgentCapabilityResult.failure(descriptor.id(), "CAPABILITY_NOT_ALLOWED",
                    "capability is not allowed by profile: " + profile.id()));
        }
        if (!descriptor.replaySafe()) {
            return record(request, AgentCapabilityResult.failure(descriptor.id(), "CAPABILITY_NOT_REPLAY_SAFE",
                    "capability is not replay-safe: " + descriptor.id()));
        }
        try {
            return record(request, capability.execute(request));
        } catch (RuntimeException error) {
            return record(request, AgentCapabilityResult.failure(descriptor.id(), "CAPABILITY_EXECUTION_FAILED", error.getMessage()));
        }
    }

    private AgentCapabilityResult record(AgentCapabilityRequest request, AgentCapabilityResult result) {
        auditSink.record(new AgentCapabilityAuditEvent(
                request.requestId(),
                request.profileId(),
                request.capabilityId(),
                result.status(),
                result.errorCode(),
                result.errorMessage(),
                Instant.now()
        ));
        return result;
    }
}
