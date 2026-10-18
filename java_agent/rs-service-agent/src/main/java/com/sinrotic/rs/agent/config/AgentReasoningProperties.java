package com.sinrotic.rs.agent.config;

import java.math.BigDecimal;
import org.springframework.boot.context.properties.ConfigurationProperties;

/** 启动配置，不接受模型或用户 context 覆盖。费用单位为 USD，费率单位为 USD/百万 token。 */
@ConfigurationProperties(prefix = "rs.agent.reasoning")
public class AgentReasoningProperties {
    private boolean budgetEnabled = true, driftEnabled = true, semanticReviewEnabled = true, pricingConfigured;
    private long maxTokens = 131072;
    private int maxModelCalls = 32, maxOutputTokens = 4096, inputPaddingTokens = 512;
    private int reviewEvery = 3, maxDriftViolations = 2, reviewMaxTokens = 256;
    private long reviewTimeoutMs = 5000;
    private BigDecimal maxUsd = BigDecimal.ZERO, inputUsdPerMillion, outputUsdPerMillion;
    private String pricedModel = "";
    public boolean isBudgetEnabled() { return budgetEnabled; }
    public void setBudgetEnabled(boolean v) { budgetEnabled = v; }
    public boolean isDriftEnabled() { return driftEnabled; }
    public void setDriftEnabled(boolean v) { driftEnabled = v; }
    public boolean isSemanticReviewEnabled() { return semanticReviewEnabled; }
    public void setSemanticReviewEnabled(boolean v) { semanticReviewEnabled = v; }
    public long getMaxTokens() { return maxTokens; }
    public void setMaxTokens(long v) { if (v < 1 || v > 10000000) throw new IllegalArgumentException("Invalid token budget"); maxTokens = v; }
    public int getMaxModelCalls() { return maxModelCalls; }
    public void setMaxModelCalls(int v) { maxModelCalls = count(v, 1, 256); }
    public int getMaxOutputTokens() { return maxOutputTokens; }
    public void setMaxOutputTokens(int v) { maxOutputTokens = count(v, 1, 131072); }
    public int getInputPaddingTokens() { return inputPaddingTokens; }
    public void setInputPaddingTokens(int v) { inputPaddingTokens = count(v, 0, 65536); }
    public int getReviewEvery() { return reviewEvery; }
    public void setReviewEvery(int v) { reviewEvery = count(v, 1, 32); }
    public int getMaxDriftViolations() { return maxDriftViolations; }
    public void setMaxDriftViolations(int v) { maxDriftViolations = count(v, 1, 8); }
    public int getReviewMaxTokens() { return reviewMaxTokens; }
    public void setReviewMaxTokens(int v) { reviewMaxTokens = count(v, 32, 1024); }
    public long getReviewTimeoutMs() { return reviewTimeoutMs; }
    public void setReviewTimeoutMs(long v) { if (v < 1 || v > 60000) throw new IllegalArgumentException("Invalid review timeout"); reviewTimeoutMs = v; }
    public BigDecimal getMaxUsd() { return maxUsd; }
    public void setMaxUsd(BigDecimal v) { maxUsd = money(v); }
    public BigDecimal getInputUsdPerMillion() { return inputUsdPerMillion; }
    public void setInputUsdPerMillion(BigDecimal v) { inputUsdPerMillion = money(v); }
    public BigDecimal getOutputUsdPerMillion() { return outputUsdPerMillion; }
    public void setOutputUsdPerMillion(BigDecimal v) { outputUsdPerMillion = money(v); }
    public String getPricedModel() { return pricedModel; }
    public void setPricedModel(String v) { pricedModel = v == null ? "" : v; }
    public boolean isPricingConfigured() { return pricingConfigured; }
    public void setPricingConfigured(boolean value) { pricingConfigured = value; }
    private static BigDecimal money(BigDecimal v) { if (v == null || v.signum() < 0 || v.precision() > 24 || Math.abs(v.scale()) > 12) throw new IllegalArgumentException("Invalid configured cost"); return v; }
    private static int count(int v, int min, int max) { if (v < min || v > max) throw new IllegalArgumentException("Invalid reasoning count"); return v; }
}
