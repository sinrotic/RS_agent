package com.sinrotic.rs.model.domain.vo;

import com.fasterxml.jackson.annotation.JsonProperty;

import java.util.List;

public record RankSignalVO(
        @JsonProperty("item_id") String itemId,
        double delta,
        double confidence,
        String reason,
        List<String> tags
) {
}
