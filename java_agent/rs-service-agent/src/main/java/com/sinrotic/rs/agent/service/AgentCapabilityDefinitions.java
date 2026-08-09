package com.sinrotic.rs.agent.service;

import com.sinrotic.rs.agent.domain.AgentCapabilityDescriptor;

import java.util.List;
import java.util.LinkedHashMap;
import java.util.Map;

public final class AgentCapabilityDefinitions {

    private static final Map<String, AgentCapabilityDescriptor> BUILT_INS = definitions();

    private AgentCapabilityDefinitions() {
    }

    public static List<AgentCapabilityDescriptor> builtIns() {
        return List.copyOf(BUILT_INS.values());
    }

    public static AgentCapabilityDescriptor byId(String id) {
        AgentCapabilityDescriptor descriptor = BUILT_INS.get(id);
        if (descriptor == null) {
            throw new IllegalArgumentException("unknown built-in capability: " + id);
        }
        return descriptor;
    }

    private static Map<String, AgentCapabilityDescriptor> definitions() {
        List<AgentCapabilityDescriptor> descriptors = List.of(
                descriptor("recommend", "Retrieve answer-ready recommendation candidates.", Map.of(
                        "type", "object",
                        "properties", Map.of(
                                "query", Map.of("type", "string"),
                                "session_id", Map.of("type", "string"),
                                "profile_user_id", Map.of("type", "string"),
                                "limit", Map.of("type", "integer"),
                                "context", Map.of("type", "object")
                        )
                )),
                descriptor("rag-explain", "Retrieve candidate-scoped evidence for an explanation.", Map.of(
                        "type", "object",
                        "properties", Map.of("query", Map.of("type", "string"),
                                "candidate_item_ids", Map.of("type", "array"))
                )),
                descriptor("session-memory", "Read replay-safe session memory for the current turn.", Map.of(
                        "type", "object",
                        "properties", Map.of("session_id", Map.of("type", "string"))
                ))
        );
        Map<String, AgentCapabilityDescriptor> definitions = new LinkedHashMap<>();
        descriptors.forEach(descriptor -> definitions.put(descriptor.id(), descriptor));
        return Map.copyOf(definitions);
    }

    private static AgentCapabilityDescriptor descriptor(String id, String description, Map<String, Object> schema) {
        return new AgentCapabilityDescriptor(id, description, schema, true, false);
    }
}
