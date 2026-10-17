package com.sinrotic.rs.agent.config;

import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.stereotype.Component;

@Component
@ConfigurationProperties(prefix = "rs.agent.execution")
public class AgentExecutionProperties {

    private int maxActiveLoops = 32;

    private long activeLoopAcquireTimeoutMs = 300;

    private int maxModelStreams = 8;

    private long modelStreamAcquireTimeoutMs = 200;

    private int maxToolCalls = 64;

    private long toolAcquireTimeoutMs = 300;

    private int maxRecommendationCalls = 8;

    private long recommendationAcquireTimeoutMs = 15000;

    private int maxSessionQueueSize = 2;

    private long sessionQueueTimeoutMs = 500;

    public int getMaxActiveLoops() {
        return maxActiveLoops;
    }

    public void setMaxActiveLoops(int maxActiveLoops) {
        this.maxActiveLoops = maxActiveLoops;
    }

    public long getActiveLoopAcquireTimeoutMs() {
        return activeLoopAcquireTimeoutMs;
    }

    public void setActiveLoopAcquireTimeoutMs(long activeLoopAcquireTimeoutMs) {
        this.activeLoopAcquireTimeoutMs = activeLoopAcquireTimeoutMs;
    }

    public int getMaxModelStreams() {
        return maxModelStreams;
    }

    public void setMaxModelStreams(int maxModelStreams) {
        this.maxModelStreams = maxModelStreams;
    }

    public long getModelStreamAcquireTimeoutMs() {
        return modelStreamAcquireTimeoutMs;
    }

    public void setModelStreamAcquireTimeoutMs(long modelStreamAcquireTimeoutMs) {
        this.modelStreamAcquireTimeoutMs = modelStreamAcquireTimeoutMs;
    }

    public int getMaxToolCalls() {
        return maxToolCalls;
    }

    public void setMaxToolCalls(int maxToolCalls) {
        this.maxToolCalls = maxToolCalls;
    }

    public long getToolAcquireTimeoutMs() {
        return toolAcquireTimeoutMs;
    }

    public void setToolAcquireTimeoutMs(long toolAcquireTimeoutMs) {
        this.toolAcquireTimeoutMs = toolAcquireTimeoutMs;
    }

    public int getMaxSessionQueueSize() {
        return maxSessionQueueSize;
    }

    public int getMaxRecommendationCalls() {
        return maxRecommendationCalls;
    }

    public void setMaxRecommendationCalls(int maxRecommendationCalls) {
        this.maxRecommendationCalls = maxRecommendationCalls;
    }

    public long getRecommendationAcquireTimeoutMs() {
        return recommendationAcquireTimeoutMs;
    }

    public void setRecommendationAcquireTimeoutMs(long recommendationAcquireTimeoutMs) {
        this.recommendationAcquireTimeoutMs = recommendationAcquireTimeoutMs;
    }

    public void setMaxSessionQueueSize(int maxSessionQueueSize) {
        this.maxSessionQueueSize = maxSessionQueueSize;
    }

    public long getSessionQueueTimeoutMs() {
        return sessionQueueTimeoutMs;
    }

    public void setSessionQueueTimeoutMs(long sessionQueueTimeoutMs) {
        this.sessionQueueTimeoutMs = sessionQueueTimeoutMs;
    }
}
