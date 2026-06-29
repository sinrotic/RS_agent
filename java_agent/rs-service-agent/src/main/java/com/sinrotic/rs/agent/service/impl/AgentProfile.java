package com.sinrotic.rs.agent.service.impl;

import java.util.Map;

public record AgentProfile(
        String name,
        String description,
        Map<String, String> toolServices
) {

    public String serviceForTool(String toolName) {
        return toolServices.getOrDefault(toolName, "rs-service-agent");
    }
}
