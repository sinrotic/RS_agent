package com.sinrotic.rs.agent.config;

import org.springframework.boot.context.properties.ConfigurationProperties;

@ConfigurationProperties(prefix = "rs.agent.trace")
public class AgentTraceReporterProperties {

    private boolean enabled;

    private String platformTraceBaseUrl = "http://rs-service-platform-trace:18108";

    public boolean isEnabled() {
        return enabled;
    }

    public void setEnabled(boolean enabled) {
        this.enabled = enabled;
    }

    public String getPlatformTraceBaseUrl() {
        return platformTraceBaseUrl;
    }

    public void setPlatformTraceBaseUrl(String platformTraceBaseUrl) {
        this.platformTraceBaseUrl = platformTraceBaseUrl;
    }
}
