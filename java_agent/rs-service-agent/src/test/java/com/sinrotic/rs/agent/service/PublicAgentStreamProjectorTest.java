package com.sinrotic.rs.agent.service;

import com.sinrotic.rs.agent.domain.vo.AgentStreamEventVO;
import org.junit.jupiter.api.Test;

import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;

class PublicAgentStreamProjectorTest {

    private final PublicAgentStreamProjector projector = new PublicAgentStreamProjector();

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
