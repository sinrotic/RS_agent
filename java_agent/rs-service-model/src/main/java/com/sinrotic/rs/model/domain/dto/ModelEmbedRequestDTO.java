package com.sinrotic.rs.model.domain.dto;

import com.fasterxml.jackson.annotation.JsonProperty;

import java.util.Map;

public record ModelEmbedRequestDTO(
        @JsonProperty("model_key") String modelKey,
        @JsonProperty("request_id") String requestId,
        Map<String, Object> inputs,
        Map<String, Object> options
) {

    public ModelEmbedRequestDTO {
        inputs = inputs == null ? Map.of() : Map.copyOf(inputs);
        options = options == null ? Map.of() : Map.copyOf(options);
    }
}
