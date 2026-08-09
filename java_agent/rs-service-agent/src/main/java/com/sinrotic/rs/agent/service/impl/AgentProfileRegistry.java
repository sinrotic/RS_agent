package com.sinrotic.rs.agent.service.impl;

import com.sinrotic.rs.agent.config.AgentTemplateProperties;
import com.sinrotic.rs.agent.domain.AgentRuntimeProfile;

import java.util.Comparator;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * Immutable registry for the server-owned Agent Runtime Profiles.
 */
public final class AgentProfileRegistry {

    private final String defaultProfileId;

    private final Map<String, AgentRuntimeProfile> profiles;

    public AgentProfileRegistry(AgentTemplateProperties properties) {
        defaultProfileId = properties.getDefaultProfile();
        Map<String, AgentRuntimeProfile> configuredProfiles = new LinkedHashMap<>();
        AgentRuntimeProfile builtInShoppingAssistant = toRuntimeProfile(
                AgentTemplateProperties.builtInShoppingAssistant()
        );
        configuredProfiles.put(builtInShoppingAssistant.id(), builtInShoppingAssistant);
        Set<String> explicitProfileIds = new HashSet<>();
        for (AgentTemplateProperties.Profile profile : properties.getProfiles()) {
            AgentRuntimeProfile runtimeProfile = toRuntimeProfile(profile);
            if (!explicitProfileIds.add(runtimeProfile.id())) {
                throw new IllegalArgumentException("duplicate agent profile: " + runtimeProfile.id());
            }
            configuredProfiles.put(runtimeProfile.id(), runtimeProfile);
        }
        profiles = Map.copyOf(configuredProfiles);
        if (!profiles.containsKey(defaultProfileId)) {
            throw new IllegalArgumentException("unknown default agent profile: " + defaultProfileId);
        }
    }

    public AgentRuntimeProfile defaultProfile() {
        return profile(defaultProfileId);
    }

    public AgentRuntimeProfile profile(String id) {
        AgentRuntimeProfile profile = profiles.get(id);
        if (profile == null) {
            throw new IllegalArgumentException("unknown agent profile: " + id);
        }
        return profile;
    }

    public List<AgentRuntimeProfile> profiles() {
        return profiles.values().stream()
                .sorted(Comparator.comparing(AgentRuntimeProfile::id))
                .toList();
    }

    private AgentRuntimeProfile toRuntimeProfile(AgentTemplateProperties.Profile profile) {
        return new AgentRuntimeProfile(
                profile.getId(),
                profile.getModelRef(),
                profile.getSystemPromptRef(),
                profile.getAllowedCapabilities(),
                profile.getAllowedOutputBlocks(),
                profile.getMaxLoops(),
                profile.getFailurePolicy()
        );
    }
}
