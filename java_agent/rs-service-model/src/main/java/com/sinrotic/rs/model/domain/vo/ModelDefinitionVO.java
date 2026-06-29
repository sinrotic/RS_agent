package com.sinrotic.rs.model.domain.vo;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.annotation.JsonProperty;

@JsonInclude(JsonInclude.Include.NON_NULL)
public record ModelDefinitionVO(
        @JsonProperty("model_key") String modelKey,
        String type,
        String runtime,
        String version,
        @JsonProperty("artifact_uri") String artifactUri,
        String endpoint,
        @JsonProperty("timeout_ms") Integer timeoutMs,
        @JsonProperty("batch_size") Integer batchSize,
        String device,
        Boolean enabled
) {

    public ModelDefinitionVO toPlatformView() {
        return new ModelDefinitionVO(
                modelKey,
                type,
                runtime,
                version,
                null,
                null,
                timeoutMs,
                batchSize,
                device,
                enabled
        );
    }
}
