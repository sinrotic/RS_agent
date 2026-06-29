package com.sinrotic.rs.model.service.impl;

import com.sinrotic.rs.model.domain.vo.ModelDefinitionVO;
import org.junit.jupiter.api.Test;

import java.util.Map;
import java.util.function.Function;
import java.util.stream.Collectors;

import static org.assertj.core.api.Assertions.assertThat;

class InMemoryModelRegistryServiceTest {

    private final InMemoryModelRegistryService registryService = new InMemoryModelRegistryService();

    @Test
    void registryIncludesRealtimeComputeModelsForRecommendSearchAndAgent() {
        Map<String, ModelDefinitionVO> models = registryService.listModels().models().stream()
                .collect(Collectors.toMap(ModelDefinitionVO::modelKey, Function.identity()));

        assertThat(models).containsKeys(
                "bge_m3_embedding",
                "two_tower_user_encoder",
                "deepfm_ranker",
                "cold_coarse_ranker",
                "qwen_agent_chat",
                "qwen_rerank_signal"
        );
        assertThat(models.get("bge_m3_embedding").type()).isEqualTo("embedding");
        assertThat(models.get("two_tower_user_encoder").type()).isEqualTo("embedding");
        assertThat(models.get("deepfm_ranker").type()).isEqualTo("ranking");
        assertThat(models.get("cold_coarse_ranker").type()).isEqualTo("ranking");
        assertThat(models.get("qwen_agent_chat").runtime()).isEqualTo("vllm");
        assertThat(models.get("qwen_rerank_signal").type()).isEqualTo("rank_signal");
    }

    @Test
    void platformRegistryDoesNotExposeInternalRuntimeUris() {
        ModelDefinitionVO model = registryService.getPlatformModel("qwen_agent_chat");

        assertThat(model.artifactUri()).isNull();
        assertThat(model.endpoint()).isNull();
        assertThat(model.enabled()).isTrue();
    }
}
