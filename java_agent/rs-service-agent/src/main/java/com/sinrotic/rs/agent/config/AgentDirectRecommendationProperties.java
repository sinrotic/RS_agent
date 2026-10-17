package com.sinrotic.rs.agent.config;

import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.stereotype.Component;

/** Opt-in until real dependencies and answer quality have passed acceptance. */
@Component
@ConfigurationProperties(prefix = "rs.agent.direct-recommendation")
public class AgentDirectRecommendationProperties {
    private boolean enabled;
    private boolean llmSynthesisEnabled;
    private String catalogCurrency = "";

    public boolean isEnabled() { return enabled; }
    public void setEnabled(boolean enabled) { this.enabled = enabled; }
    public boolean isLlmSynthesisEnabled() { return llmSynthesisEnabled; }
    public void setLlmSynthesisEnabled(boolean enabled) { this.llmSynthesisEnabled = enabled; }
    public String getCatalogCurrency() { return catalogCurrency; }
    public void setCatalogCurrency(String catalogCurrency) {
        this.catalogCurrency = catalogCurrency == null ? "" : catalogCurrency;
    }
}
