package com.sinrotic.rs.recommend.domain.vo;

import com.fasterxml.jackson.annotation.JsonProperty;

import java.util.List;

public record RecommendPreferencesVO(
        @JsonProperty("preference_version") long preferenceVersion,
        List<RecommendPreferenceItemVO> items
) {
}
