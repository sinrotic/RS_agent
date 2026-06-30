package com.sinrotic.rs.agent.config;

import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.stereotype.Component;

import java.time.Duration;

@Component
@ConfigurationProperties(prefix = "rs.agent.result-store")
public class AgentToolResultStoreProperties {

    private String type = "memory";

    private int blockLineCount = 50;

    private Duration ttl = Duration.ofHours(1);

    public String getType() {
        return type;
    }

    public void setType(String type) {
        this.type = type;
    }

    public int getBlockLineCount() {
        return blockLineCount;
    }

    public void setBlockLineCount(int blockLineCount) {
        this.blockLineCount = blockLineCount;
    }

    public Duration getTtl() {
        return ttl;
    }

    public void setTtl(Duration ttl) {
        this.ttl = ttl;
    }
}
