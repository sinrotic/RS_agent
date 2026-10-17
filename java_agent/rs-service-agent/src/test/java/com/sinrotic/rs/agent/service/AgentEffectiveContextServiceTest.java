package com.sinrotic.rs.agent.service;

import com.sinrotic.rs.agent.domain.session.AgentRecoveredTranscript;
import com.sinrotic.rs.agent.domain.session.AgentTranscriptEntry;
import com.sinrotic.rs.agent.service.impl.AgentEffectiveContextService;
import org.junit.jupiter.api.Test;
import java.time.Instant;
import java.util.List;
import java.util.Map;
import static org.assertj.core.api.Assertions.assertThat;

class AgentEffectiveContextServiceTest {
    @Test
    void checkpointAndTailRecoverConversationWithoutToolOrAuthenticationPayloads() {
        var context = new AgentEffectiveContextService(id -> new AgentRecoveredTranscript(id, "checkpoint", 2,
                List.of(Map.of("role", "assistant", "content", "摘要：预算五百元")),
                List.of(Map.of("seq", 2, "assistant_message", "保留防雨约束")),
                List.of(entry(3, "USER_MESSAGE", Map.of("content", "还要轻便")),
                        entry(4, "TOOL_RESULT", Map.of("content", "private credential")),
                        entry(5, "ASSISTANT_FINAL", Map.of("assistant_message", "好的", "authenticated_account_id", "private account"))))).recover("session");
        assertThat(context.get("checkpoint_id")).isEqualTo("checkpoint");
        assertThat(context.get("truncated")).isEqualTo(false);
        assertThat(context.get("messages").toString()).contains("预算五百元", "保留防雨约束", "还要轻便", "好的").doesNotContain("private");
    }

    @Test
    @SuppressWarnings("unchecked")
    void oversizedContextDropsWholeSemanticGroupsAndReportsLoss() {
        var context = new AgentEffectiveContextService(id -> new AgentRecoveredTranscript(id, "", 0, List.of(), List.of(),
                List.of(entry(1, "USER_MESSAGE", Map.of("content", "最早完整需求")),
                        entry(2, "ASSISTANT_FINAL", Map.of("assistant_message", "早期回答")),
                        entry(3, "USER_MESSAGE", Map.of("content", "中间需求".repeat(1700))),
                        entry(4, "ASSISTANT_FINAL", Map.of("assistant_message", "中间回答不能孤立出现")),
                        entry(5, "USER_MESSAGE", Map.of("content", "最近要求")),
                        entry(6, "ASSISTANT_FINAL", Map.of("assistant_message", "最近回答"))))).recover("session");
        var messages = (List<Map<String, Object>>) context.get("messages");
        assertThat(messages.toString()).contains("最早完整需求", "早期回答", "最近要求", "最近回答").doesNotContain("中间");
        assertThat(messages.stream().mapToInt(message -> message.get("content").toString().length()).sum()).isLessThanOrEqualTo(6000);
        assertThat(context.get("truncated")).isEqualTo(true);
        assertThat(context.get("omitted_message_count")).isEqualTo(2);
    }

    private AgentTranscriptEntry entry(long seq, String type, Map<String, Object> payload) {
        return new AgentTranscriptEntry("session", seq, (seq + 1) / 2, 0, "request", type, "", payload, Instant.EPOCH);
    }
}
