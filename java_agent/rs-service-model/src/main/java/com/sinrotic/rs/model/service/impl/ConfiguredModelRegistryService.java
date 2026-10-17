package com.sinrotic.rs.model.service.impl;

import com.sinrotic.rs.model.domain.vo.*;
import com.sinrotic.rs.model.service.ModelRegistryService;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Profile;
import org.springframework.stereotype.Service;
import java.util.List;

@Service
@Profile("!mock-models")
public class ConfiguredModelRegistryService implements ModelRegistryService {
    private final List<ModelDefinitionVO> models;

    public ConfiguredModelRegistryService(
            @Value("${rs.model.runtime.embedding-base-url:}") String embeddingBaseUrl,
            @Value("${rs.model.runtime.rerank-base-url:}") String rerankBaseUrl) {
        models = List.of(definition("bge-m3", "embedding", embeddingBaseUrl, "/internal/model/embed"),
                definition("bge-reranker-v2-m3", "ranking", rerankBaseUrl, "/internal/model/rank"));
    }

    private ModelDefinitionVO definition(String key, String type, String baseUrl, String path) {
        boolean enabled = baseUrl != null && !baseUrl.isBlank();
        return new ModelDefinitionVO(key, type, "http", "runtime", null,
                enabled ? baseUrl + path : null, null, 128, "runtime", enabled);
    }

    @Override public ModelRegistryVO listModels() { return new ModelRegistryVO(models); }
    @Override public ModelRegistryVO listPlatformModels() {
        return new ModelRegistryVO(models.stream().map(ModelDefinitionVO::toPlatformView).toList());
    }
    @Override public ModelDefinitionVO getModel(String key) {
        return models.stream().filter(model -> model.modelKey().equals(key)).findFirst()
                .orElseThrow(() -> new IllegalArgumentException("Unknown model_key: " + key));
    }
    @Override public ModelDefinitionVO getPlatformModel(String key) { return getModel(key).toPlatformView(); }
}
