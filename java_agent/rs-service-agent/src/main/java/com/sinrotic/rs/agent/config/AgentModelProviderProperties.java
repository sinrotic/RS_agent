package com.sinrotic.rs.agent.config;

import org.springframework.boot.context.properties.ConfigurationProperties;

@ConfigurationProperties(prefix = "rs.agent.model-provider")
public class AgentModelProviderProperties {

    private ProviderType type = ProviderType.PYTHON_API;

    private final PythonApi pythonApi = new PythonApi();

    private final SelfHosted selfHosted = new SelfHosted();

    public ProviderType getType() {
        return type;
    }

    public void setType(ProviderType type) {
        this.type = type;
    }

    public PythonApi pythonApi() {
        return pythonApi;
    }

    public SelfHosted selfHosted() {
        return selfHosted;
    }

    public enum ProviderType {
        PYTHON_API,
        SELF_HOSTED,
        SPRING_AI
    }

    public static class PythonApi {

        private String baseUrl = "http://127.0.0.1:8002";

        private String chatPath = "/chat";

        private String streamPath = "/chat/stream";

        public String getBaseUrl() {
            return baseUrl;
        }

        public void setBaseUrl(String baseUrl) {
            this.baseUrl = baseUrl;
        }

        public String getChatPath() {
            return chatPath;
        }

        public void setChatPath(String chatPath) {
            this.chatPath = chatPath;
        }

        public String getStreamPath() {
            return streamPath;
        }

        public void setStreamPath(String streamPath) {
            this.streamPath = streamPath;
        }
    }

    public static class SelfHosted {

        private String baseUrl = "http://127.0.0.1:9001";

        private String streamPath = "/internal/model/chat/stream";

        private String modelKey = "agent_4b";

        public String getBaseUrl() {
            return baseUrl;
        }

        public void setBaseUrl(String baseUrl) {
            this.baseUrl = baseUrl;
        }

        public String getStreamPath() {
            return streamPath;
        }

        public void setStreamPath(String streamPath) {
            this.streamPath = streamPath;
        }

        public String getModelKey() {
            return modelKey;
        }

        public void setModelKey(String modelKey) {
            this.modelKey = modelKey;
        }
    }
}
