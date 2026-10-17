package com.sinrotic.rs.platformtrace.domain.vo;

import com.fasterxml.jackson.annotation.JsonProperty;

public record AgentRunSummaryVO(
        @JsonProperty("total_latency_ms")
        Long totalLatencyMs,
        @JsonProperty("prompt_tokens")
        Integer promptTokens,
        @JsonProperty("completion_tokens")
        Integer completionTokens,
        @JsonProperty("total_tokens")
        Integer totalTokens,
        @JsonProperty("model_provider")
        String modelProvider,
        @JsonProperty("model_name")
        String modelName,
        @JsonProperty("tool_call_count")
        Integer toolCallCount,
        @JsonProperty("error_count")
        Integer errorCount,
        @JsonProperty("recommend_item_count")
        Integer recommendItemCount,
        @JsonProperty("has_final_answer")
        Boolean hasFinalAnswer,
        @JsonProperty("usage_coverage")
        java.util.Map<String, Object> usageCoverage
) {
    public AgentRunSummaryVO {
        totalLatencyMs = totalLatencyMs == null ? 0L : totalLatencyMs;
        modelProvider = modelProvider == null ? "" : modelProvider;
        modelName = modelName == null ? "" : modelName;
        toolCallCount = toolCallCount == null ? 0 : toolCallCount;
        errorCount = errorCount == null ? 0 : errorCount;
        recommendItemCount = recommendItemCount == null ? 0 : recommendItemCount;
        hasFinalAnswer = hasFinalAnswer != null && hasFinalAnswer;
        usageCoverage = usageCoverage == null ? java.util.Map.of() : java.util.Map.copyOf(usageCoverage);
    }

    public static AgentRunSummaryVO empty() {
        return new AgentRunSummaryVO(0L, null, null, null, "", "", 0, 0, 0, false, java.util.Map.of("mode", "not_observed"));
    }
}
