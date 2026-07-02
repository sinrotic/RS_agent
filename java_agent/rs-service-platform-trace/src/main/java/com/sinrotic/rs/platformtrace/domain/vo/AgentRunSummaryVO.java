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
        Boolean hasFinalAnswer
) {
    public AgentRunSummaryVO {
        totalLatencyMs = totalLatencyMs == null ? 0L : totalLatencyMs;
        promptTokens = promptTokens == null ? 0 : promptTokens;
        completionTokens = completionTokens == null ? 0 : completionTokens;
        totalTokens = totalTokens == null ? 0 : totalTokens;
        modelProvider = modelProvider == null ? "" : modelProvider;
        modelName = modelName == null ? "" : modelName;
        toolCallCount = toolCallCount == null ? 0 : toolCallCount;
        errorCount = errorCount == null ? 0 : errorCount;
        recommendItemCount = recommendItemCount == null ? 0 : recommendItemCount;
        hasFinalAnswer = hasFinalAnswer != null && hasFinalAnswer;
    }

    public static AgentRunSummaryVO empty() {
        return new AgentRunSummaryVO(0L, 0, 0, 0, "", "", 0, 0, 0, false);
    }
}
