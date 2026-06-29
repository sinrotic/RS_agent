package com.sinrotic.rs.model.domain.vo;

import com.fasterxml.jackson.annotation.JsonInclude;

import java.util.List;
import java.util.Map;

@JsonInclude(JsonInclude.Include.NON_NULL)
public record EmbeddingVectorVO(
        String id,
        List<Double> vector,
        Map<String, Object> metadata
) {
}
