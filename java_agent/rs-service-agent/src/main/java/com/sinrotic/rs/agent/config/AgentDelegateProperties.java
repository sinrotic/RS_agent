package com.sinrotic.rs.agent.config;

import org.springframework.boot.context.properties.ConfigurationProperties;

@ConfigurationProperties(prefix = "rs.agent.delegate")
public class AgentDelegateProperties {

    private final RagAgent ragAgent = new RagAgent();

    public RagAgent ragAgent() {
        return ragAgent;
    }

    public static class RagAgent {

        private String baseUrl = "http://127.0.0.1:8086";

        private String supportPath = "/agent/rag/support";

        public String getBaseUrl() {
            return baseUrl;
        }

        public void setBaseUrl(String baseUrl) {
            this.baseUrl = baseUrl;
        }

        public String getSupportPath() {
            return supportPath;
        }

        public void setSupportPath(String supportPath) {
            this.supportPath = supportPath;
        }
    }
}
