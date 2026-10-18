package com.sinrotic.rs.agent.config;

import org.springframework.boot.context.properties.ConfigurationProperties;

@ConfigurationProperties(prefix = "rs.agent.tool-governance")
public class AgentToolGovernanceProperties {
    private boolean enabled = true;
    private int maxAttempts = 2, maxAttemptsPerTurn = 32, noProgressLimit = 3, circuitFailureThreshold = 3;
    private long callTimeoutMs = 30000, turnTimeoutMs = 120000, retryDelayMs = 50, circuitOpenMs = 10000;
    public boolean isEnabled() { return enabled; }
    public void setEnabled(boolean value) { enabled = value; }
    public int getMaxAttempts() { return maxAttempts; }
    public void setMaxAttempts(int value) { maxAttempts = bounded(value, 1, 3); }
    public int getMaxAttemptsPerTurn() { return maxAttemptsPerTurn; }
    public void setMaxAttemptsPerTurn(int value) { maxAttemptsPerTurn = bounded(value, 1, 256); }
    public int getNoProgressLimit() { return noProgressLimit; }
    public void setNoProgressLimit(int value) { noProgressLimit = bounded(value, 2, 20); }
    public int getCircuitFailureThreshold() { return circuitFailureThreshold; }
    public void setCircuitFailureThreshold(int value) { circuitFailureThreshold = bounded(value, 1, 100); }
    public long getCallTimeoutMs() { return callTimeoutMs; }
    public void setCallTimeoutMs(long value) { callTimeoutMs = timeout(value); }
    public long getTurnTimeoutMs() { return turnTimeoutMs; }
    public void setTurnTimeoutMs(long value) { turnTimeoutMs = timeout(value); }
    public long getRetryDelayMs() { return retryDelayMs; }
    public void setRetryDelayMs(long value) { if (value < 0 || value > 10000) throw new IllegalArgumentException("Invalid retry delay"); retryDelayMs = value; }
    public long getCircuitOpenMs() { return circuitOpenMs; }
    public void setCircuitOpenMs(long value) { circuitOpenMs = timeout(value); }
    private static long timeout(long value) { if (value < 1 || value > 3600000) throw new IllegalArgumentException("Tool governance timeout must be 1..3600000ms"); return value; }
    private static int bounded(int value, int min, int max) { if (value < min || value > max) throw new IllegalArgumentException("Tool governance count outside bounds"); return value; }
}
