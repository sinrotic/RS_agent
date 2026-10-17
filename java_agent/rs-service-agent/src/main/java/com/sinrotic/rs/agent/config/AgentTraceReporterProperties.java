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
    private final Otlp otlp = new Otlp();
    public Otlp getOtlp() { return otlp; }

    public static class Otlp {
        private boolean enabled, langfuse;
        private String endpoint = "", authorization = "", identityKey = "", modelName = "";
        private String serviceName = "rs-service-agent";
        public boolean isEnabled() { return enabled; }
        public void setEnabled(boolean value) { enabled = value; }
        public boolean isLangfuse() { return langfuse; }
        public void setLangfuse(boolean value) { langfuse = value; }
        public String getEndpoint() { return endpoint; }
        public void setEndpoint(String value) { endpoint = value; }
        public String getAuthorization() { return authorization; }
        public void setAuthorization(String value) { authorization = value; }
        public String getIdentityKey() { return identityKey; }
        public void setIdentityKey(String value) { identityKey = value; }
        public String getModelName() { return modelName; }
        public void setModelName(String value) { modelName = value; }
        public String getServiceName() { return serviceName; }
        public void setServiceName(String value) { serviceName = value; }
    }

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
