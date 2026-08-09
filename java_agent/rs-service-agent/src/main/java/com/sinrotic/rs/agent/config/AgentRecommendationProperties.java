package com.sinrotic.rs.agent.config;

import org.springframework.boot.context.properties.ConfigurationProperties;

@ConfigurationProperties(prefix = "rs.agent.recommendation")
public class AgentRecommendationProperties {

    private String type = "memory";
    private String baseUrl = "http://rs-service-recommend:18103";
    private String candidatesPath = "/agent/recommend/candidates";
    private String semanticRecallPath = "/agent/recommend/semantic-recall";

    public String getType() {
        return type;
    }

    public void setType(String type) {
        this.type = type;
    }

    public String getBaseUrl() {
        return baseUrl;
    }

    public void setBaseUrl(String baseUrl) {
        this.baseUrl = baseUrl;
    }

    public String getCandidatesPath() {
        return candidatesPath;
    }

    public void setCandidatesPath(String candidatesPath) {
        this.candidatesPath = candidatesPath;
    }

    public String getSemanticRecallPath() {
        return semanticRecallPath;
    }

    public void setSemanticRecallPath(String semanticRecallPath) {
        this.semanticRecallPath = semanticRecallPath;
    }
}
