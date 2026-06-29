package com.sinrotic.rs.model.service.impl;

import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class MockModelHealthServiceTest {

    private final MockModelHealthService healthService = new MockModelHealthService();

    @Test
    void healthSummaryReflectsExpandedModelRuntimeGroups() {
        var health = healthService.getHealth();

        assertThat(health.manifest()).containsEntry("model_count", 10);
        assertThat(health.manifest()).containsEntry("enabled_model_count", 10);
        assertThat(health.runtimes())
                .extracting(runtime -> runtime.get("name"))
                .contains("embedding-service", "ranker-service", "vllm-agent");
    }

    @Test
    void modelHealthRoutesQwenModelsToVllmRuntime() {
        var health = healthService.getModelHealth("qwen_rerank_signal");

        assertThat(health.runtime()).isEqualTo("vllm");
        assertThat(health.endpoint()).isEqualTo("http://vllm-agent:8000/v1/chat/completions");
    }
}
