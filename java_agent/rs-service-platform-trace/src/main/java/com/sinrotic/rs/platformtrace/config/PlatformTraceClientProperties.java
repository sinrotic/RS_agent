package com.sinrotic.rs.platformtrace.config;

import org.springframework.boot.context.properties.ConfigurationProperties;

@ConfigurationProperties(prefix = "rs.platform-trace.clients")
public class PlatformTraceClientProperties {

    private String userBaseUrl = "http://rs-service-user:18101";
    private String recommendBaseUrl = "http://rs-service-recommend:18103";
    private String agentBaseUrl = "http://rs-service-agent:18104";
    private boolean enabled = false;

    public String getUserBaseUrl() {
        return userBaseUrl;
    }

    public void setUserBaseUrl(String userBaseUrl) {
        this.userBaseUrl = userBaseUrl;
    }

    public String getRecommendBaseUrl() {
        return recommendBaseUrl;
    }

    public void setRecommendBaseUrl(String recommendBaseUrl) {
        this.recommendBaseUrl = recommendBaseUrl;
    }

    public String getAgentBaseUrl() {
        return agentBaseUrl;
    }

    public void setAgentBaseUrl(String agentBaseUrl) {
        this.agentBaseUrl = agentBaseUrl;
    }

    public boolean isEnabled() {
        return enabled;
    }

    public void setEnabled(boolean enabled) {
        this.enabled = enabled;
    }
}
