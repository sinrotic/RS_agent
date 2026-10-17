package com.sinrotic.rs.recommend.domain.vo;

import com.fasterxml.jackson.annotation.JsonProperty;
import java.util.List;

/** 保留旧列表字段，同时明确批次是否完成及每次删除的可追踪回执。 */
public record RecommendPreferenceClearVO(
        @JsonProperty("preference_version") long preferenceVersion,
        List<RecommendPreferenceItemVO> items,
        @JsonProperty("operation_complete") boolean operationComplete,
        List<RecommendFeedbackAckVO> operations
) { }
