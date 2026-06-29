package com.sinrotic.rs.model.domain.vo;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.annotation.JsonProperty;

import java.util.Map;

@JsonInclude(JsonInclude.Include.NON_NULL)
public record RankedItemVO(
        @JsonProperty("item_id") String itemId,
        double score,
        int rank,
        Map<String, Object> metadata
) {
}
