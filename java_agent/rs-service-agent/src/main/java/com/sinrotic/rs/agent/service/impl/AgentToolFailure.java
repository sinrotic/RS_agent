package com.sinrotic.rs.agent.service.impl;

import com.sinrotic.rs.agent.service.AgentBusyException;
import com.sinrotic.rs.agent.service.AgentToolDependencyException;
import java.net.http.HttpTimeoutException;
import java.io.IOException;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.*;

/** 明确分类，未知异常不推测为可重试基础设施故障。 */
enum AgentToolFailure {
    SUCCESS(false), INVALID_ARGUMENTS(false), INVALID_RESPONSE(false), AUTHORIZATION(false), CAPACITY(false),
    TRANSIENT_DEPENDENCY(true), TIMEOUT(true), CANCELLED(false), UNKNOWN(false);
    final boolean infrastructure;
    AgentToolFailure(boolean infrastructure) { this.infrastructure = infrastructure; }
    String code() { return "TOOL_" + name(); }

    static AgentToolFailure from(Throwable error) {
        Throwable current = error;
        for (int depth = 0; current != null && depth < 16; depth++, current = current.getCause()) {
            if (current instanceof CancellationException || current instanceof InterruptedException) return CANCELLED;
            if (current instanceof HttpTimeoutException || current instanceof java.net.SocketTimeoutException || current instanceof TimeoutException) return TIMEOUT;
            if (current instanceof AgentToolDependencyException http) {
                int status = http.status();
                if (status == 401 || status == 403) return AUTHORIZATION;
                if (status == 400 || status == 422) return INVALID_ARGUMENTS;
                return status == 408 || status == 429 || status >= 500 ? TRANSIENT_DEPENDENCY : UNKNOWN;
            }
            if (current instanceof AgentBusyException || current instanceof RejectedExecutionException) {
                // 许可等待被中断也会包装成 AgentBusyException；不能误报成容量拒绝。
                var cause = current.getCause();
                for (int nested = 0; cause != null && nested < 16; nested++, cause = cause.getCause())
                    if (cause instanceof InterruptedException || cause instanceof CancellationException) return CANCELLED;
                return CAPACITY;
            }
            if (current instanceof SecurityException) return AUTHORIZATION;
            if (current instanceof IllegalArgumentException) return INVALID_ARGUMENTS;
            if (current instanceof com.fasterxml.jackson.core.JsonProcessingException) return INVALID_RESPONSE;
            if (current instanceof IOException) return TRANSIENT_DEPENDENCY;
        }
        return UNKNOWN;
    }

    static AgentToolFailure from(Map<String, Object> result) {
        String status = String.valueOf(result.getOrDefault("status", "SUCCESS"));
        if (Set.of("SUCCESS", "OK", "EMPTY", "NO_RESULTS").contains(status.toUpperCase(java.util.Locale.ROOT))) return SUCCESS;
        String code = String.valueOf(result.getOrDefault("error_code", ""));
        for (var category : values()) if (category.code().equals(code)) return category;
        if (Set.of("INVALID_ARGUMENTS", "INVALID_PARAMETERS").contains(code)) return INVALID_ARGUMENTS;
        if (Set.of("SKILL_DISABLED", "TOOL_UNAVAILABLE", "TOOL_NOT_REGISTERED", "PROFILE_REQUIRED", "CAPABILITY_PROFILE_MISMATCH",
                "CAPABILITY_NOT_REGISTERED", "CAPABILITY_NOT_ALLOWED", "CAPABILITY_NOT_REPLAY_SAFE").contains(code)) return AUTHORIZATION;
        return UNKNOWN;
    }
}
