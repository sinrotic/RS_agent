package com.sinrotic.rs.agent.config;

import org.springframework.boot.context.properties.ConfigurationProperties;

@ConfigurationProperties(prefix = "rs.agent.trace")
public class AgentTraceReporterProperties {

    private boolean enabled;

    private String platformTraceBaseUrl = "http://rs-service-platform-trace:18108";
    private int queueCapacity = 512;
    private int requestTimeoutMs = 2000;
    private int shutdownTimeoutMs = 3000;
    private int maxEventBytes = 65536;

    public int getQueueCapacity() { return queueCapacity; }
    public void setQueueCapacity(int value) { queueCapacity = positive(value); }
    public int getRequestTimeoutMs() { return requestTimeoutMs; }
    public void setRequestTimeoutMs(int value) { requestTimeoutMs = positive(value); }
    public int getShutdownTimeoutMs() { return shutdownTimeoutMs; }
    public void setShutdownTimeoutMs(int value) { shutdownTimeoutMs = positive(value); }
    public int getMaxEventBytes() { return maxEventBytes; }
    public void setMaxEventBytes(int value) { maxEventBytes = positive(value); }

    private static int positive(int value) {
        if (value <= 0) throw new IllegalArgumentException("Trace 容量与超时必须为正数");
        return value;
    }

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
