package com.sinrotic.rs.agent.service;

import com.sinrotic.rs.agent.service.impl.AgentModelStreamEvent;
import com.sinrotic.rs.agent.service.impl.InMemoryAgentRuntimeConfigurationService;
import com.sinrotic.rs.agent.service.impl.VirtualThreadAgentToolUseExecutor;
import org.junit.jupiter.api.Test;

import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;

class VirtualThreadAgentToolUseExecutorTest {

    @Test
    void loadSkillToolUseReturnsSkillContentOnVirtualThread() {
        VirtualThreadAgentToolUseExecutor executor = new VirtualThreadAgentToolUseExecutor(
                new InMemoryAgentRuntimeConfigurationService()
        );

        Map<String, Object> result = executor.execute(AgentModelStreamEvent.toolUse(
                "load_skill",
                Map.of("skill_name", "explicit-need-recommendation")
        )).join();

        assertThat(result).containsEntry("status", "SUCCESS");
        assertThat(result).containsEntry("tool_type", "skill");
        assertThat(result).containsEntry("skill_name", "explicit-need-recommendation");
        assertThat(result).containsEntry("loaded", true);
        assertThat((String) result.get("content")).contains("Workflow");
        assertThat(result).containsEntry("thread_virtual", true);
    }

    @Test
    void callAgentToolUseDelegatesToRagAgentOnVirtualThread() {
        VirtualThreadAgentToolUseExecutor executor = new VirtualThreadAgentToolUseExecutor(
                new InMemoryAgentRuntimeConfigurationService(),
                (requestId, agentName, arguments) -> Map.of(
                        "status", "SUCCESS",
                        "agent_name", agentName,
                        "task", arguments.get("task"),
                        "evidence", Map.of("item_ids", arguments.get("candidate_item_ids")),
                        "thread_virtual", Thread.currentThread().isVirtual()
                )
        );

        Map<String, Object> result = executor.execute(AgentModelStreamEvent.toolUse(
                "call_agent",
                Map.of(
                        "agent_name", "rag_agent",
                        "task", "Retrieve evidence for commuter backpacks",
                        "candidate_item_ids", java.util.List.of("B001", "B002")
                )
        )).join();

        assertThat(result).containsEntry("status", "SUCCESS");
        assertThat(result).containsEntry("tool_type", "agent");
        assertThat(result).containsEntry("tool_name", "call_agent");
        assertThat(result).containsEntry("agent_name", "rag_agent");
        assertThat(result).containsEntry("thread_virtual", true);
        assertThat((Map<String, Object>) result.get("result"))
                .containsEntry("task", "Retrieve evidence for commuter backpacks");
    }

    @Test
    void renderProductCardsReturnsCardSetForSelectedItemsOnVirtualThread() {
        VirtualThreadAgentToolUseExecutor executor = new VirtualThreadAgentToolUseExecutor(
                new InMemoryAgentRuntimeConfigurationService()
        );

        Map<String, Object> result = executor.execute(AgentModelStreamEvent.toolUse(
                "render_product_cards",
                Map.of(
                        "item_ids", java.util.List.of("B001", "B002"),
                        "layout", "inline"
                )
        )).join();

        assertThat(result).containsEntry("status", "SUCCESS");
        assertThat(result).containsEntry("tool_type", "presentation");
        assertThat(result).containsEntry("tool_name", "render_product_cards");
        assertThat(result).containsEntry("layout", "inline");
        assertThat((String) result.get("card_set_id")).startsWith("cards_");
        assertThat((java.util.List<?>) result.get("cards")).hasSize(2);
        assertThat(result).containsEntry("thread_virtual", true);
    }
}
