package com.sinrotic.rs.agent.service;

import com.sinrotic.rs.agent.domain.vo.AgentStreamEventVO;
import org.junit.jupiter.api.Test;

import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;

class PublicAgentStreamProjectorTest {

    private final PublicAgentStreamProjector projector = new PublicAgentStreamProjector();

    @Test
    void preservesPublicDegradationWithoutInternalDiagnostics() {
        var event = projector.project(new AgentStreamEventVO("done", "req", Map.of("response", Map.of(
                "request_id", "req", "degradation_reasons", java.util.List.of("model_rank_unavailable", "raw_path"),
                "tool_calls", java.util.List.of("secret"))))).orElseThrow();
        var response = (Map<?, ?>) event.data().get("response");
        assertThat(response.containsKey("degradation_reasons")).isTrue();
        assertThat(response.containsKey("tool_calls")).isFalse();
        assertThat(((Map<?, ?>) event.data().get("response")).get("degradation_reasons"))
                .isEqualTo(java.util.List.of("model_rank_unavailable"));
    }

    @Test
    void dropsInternalToolAndModelEvents() {
        assertThat(projector.project(new AgentStreamEventVO("tool_result", "req", Map.of(
                "metadata", Map.of("ranking_evidence", "secret")
        )))).isEmpty();
        assertThat(projector.project(new AgentStreamEventVO("model_usage", "req", Map.of(
                "model_name", "internal"
        )))).isEmpty();
    }

    @Test
    void keepsOnlyPublicAnswerBlockFields() {
        AgentStreamEventVO projected = projector.project(new AgentStreamEventVO("answer_block", "req", Map.of(
                "type", "text",
                "content", "公开答案",
                "diagnostics", Map.of("raw_path", "/secret")
        ))).orElseThrow();

        assertThat(projected.data()).containsExactlyInAnyOrderEntriesOf(Map.of(
                "type", "text",
                "content", "公开答案"
        ));
    }
}
