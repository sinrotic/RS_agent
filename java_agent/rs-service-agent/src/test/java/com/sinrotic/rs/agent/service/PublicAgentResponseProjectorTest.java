package com.sinrotic.rs.agent.service;

import com.sinrotic.rs.agent.domain.AgentProfileFailurePolicy;
import com.sinrotic.rs.agent.domain.AgentPublicOutputBlock;
import com.sinrotic.rs.agent.domain.AgentRuntimeProfile;
import org.junit.jupiter.api.Test;

import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class PublicAgentResponseProjectorTest {

    private final PublicAgentResponseProjector projector = new PublicAgentResponseProjector();

    @Test
    void projectsAllSupportedBlocksAndDropsInternalFields() {
        List<Map<String, Object>> projected = projector.projectBlocks(List.of(
                Map.of("type", "text", "content", "推荐理由", "trace", Map.of("raw_path", "/secret")),
                Map.of("type", "product_cards", "card_set_id", "cards_1", "item_ids", List.of("B001"), "ranking_evidence", List.of("secret")),
                Map.of("type", "comparison_table", "content", "对比结果", "diagnostics", Map.of("model", "internal")),
                Map.of("type", "followup_question", "content", "需要更大容量吗？", "raw_path", "db://secret")
        ), profile(AgentPublicOutputBlock.values()));

        assertThat(projected).containsExactly(
                Map.of("type", "text", "content", "推荐理由"),
                Map.of("type", "product_cards", "card_set_id", "cards_1", "item_ids", List.of("B001")),
                Map.of("type", "comparison_table", "content", "对比结果"),
                Map.of("type", "followup_question", "content", "需要更大容量吗？")
        );
    }

    @Test
    void rejectsUnknownAndDisallowedOutputTypes() {
        assertThatThrownBy(() -> projector.projectBlock(Map.of("type", "diagnostics", "content", "secret"), profile(AgentPublicOutputBlock.values())))
                .hasMessageContaining("unknown answer block type");
        assertThatThrownBy(() -> projector.projectBlock(Map.of("type", "product_cards", "card_set_id", "cards_1"), profile(AgentPublicOutputBlock.TEXT)))
                .hasMessageContaining("not allowed by profile");
    }

    @Test
    void rejectsMalformedNestedPublicFields() {
        assertThatThrownBy(() -> projector.projectBlock(Map.of("type", "product_cards", "item_ids", List.of(42)), profile(AgentPublicOutputBlock.PRODUCT_CARDS)))
                .hasMessageContaining("item_id must be a non-blank string");
        assertThatThrownBy(() -> projector.projectBlock(Map.of("type", "text", "content", "x".repeat(4001)), profile(AgentPublicOutputBlock.TEXT)))
                .hasMessageContaining("maximum length");
    }

    private AgentRuntimeProfile profile(AgentPublicOutputBlock... outputBlocks) {
        return new AgentRuntimeProfile(
                "test",
                "default",
                "default",
                List.of("recommend"),
                List.of(outputBlocks),
                3,
                AgentProfileFailurePolicy.FAIL_TURN
        );
    }
}
