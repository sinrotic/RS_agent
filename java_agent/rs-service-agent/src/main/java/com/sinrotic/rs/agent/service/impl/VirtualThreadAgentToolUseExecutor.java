package com.sinrotic.rs.agent.service.impl;

import com.sinrotic.rs.agent.service.AgentToolUseExecutor;
import com.sinrotic.rs.agent.service.AgentDelegateService;
import com.sinrotic.rs.agent.service.AgentRuntimeConfigurationService;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

import java.util.Map;
import java.util.List;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.function.Function;

@Service
public class VirtualThreadAgentToolUseExecutor implements AgentToolUseExecutor, AutoCloseable {

    private final ExecutorService executorService;

    private final Function<AgentModelStreamEvent, Map<String, Object>> toolHandler;

    public VirtualThreadAgentToolUseExecutor() {
        this(event -> Map.of(
                "status", "SUCCESS",
                "tool_name", event.toolName(),
                "arguments", event.arguments(),
                "thread_virtual", Thread.currentThread().isVirtual()
        ));
    }

    public VirtualThreadAgentToolUseExecutor(AgentRuntimeConfigurationService runtimeConfigurationService) {
        this(runtimeConfigurationService, (requestId, agentName, arguments) -> Map.of(
                "status", "SUCCESS",
                "agent_name", agentName,
                "arguments", arguments
        ));
    }

    @Autowired
    public VirtualThreadAgentToolUseExecutor(
            AgentRuntimeConfigurationService runtimeConfigurationService,
            AgentDelegateService agentDelegateService
    ) {
        this(event -> {
            if ("load_skill".equals(event.toolName())) {
                String skillName = String.valueOf(event.arguments().getOrDefault("skill_name", ""));
                var skill = runtimeConfigurationService.skill(skillName);
                return Map.of(
                        "status", "SUCCESS",
                        "tool_type", "skill",
                        "tool_name", event.toolName(),
                        "skill_name", skill.name(),
                        "loaded", true,
                        "description", skill.description(),
                        "content", skill.content(),
                        "thread_virtual", Thread.currentThread().isVirtual()
                );
            }
            if ("render_product_cards".equals(event.toolName())) {
                List<?> itemIds = event.arguments().get("item_ids") instanceof List<?> values ? values : List.of();
                String layout = String.valueOf(event.arguments().getOrDefault("layout", "inline"));
                List<Map<String, Object>> cards = itemIds.stream()
                        .map(itemId -> Map.of(
                                "item_id", itemId,
                                "title", String.valueOf(itemId),
                                "reason", "Prepared for recommendation display."
                        ))
                        .toList();
                return Map.of(
                        "status", "SUCCESS",
                        "tool_type", "presentation",
                        "tool_name", event.toolName(),
                        "card_set_id", "cards_" + Integer.toHexString(itemIds.hashCode()),
                        "layout", layout,
                        "cards", cards,
                        "thread_virtual", Thread.currentThread().isVirtual()
                );
            }
            if ("call_agent".equals(event.toolName())) {
                String agentName = String.valueOf(event.arguments().getOrDefault("agent_name", ""));
                Map<String, Object> result = agentDelegateService.callAgent("", agentName, event.arguments());
                return Map.of(
                        "status", "SUCCESS",
                        "tool_type", "agent",
                        "tool_name", event.toolName(),
                        "agent_name", agentName,
                        "result", result,
                        "thread_virtual", Thread.currentThread().isVirtual()
                );
            }
            return Map.of(
                    "status", "SUCCESS",
                    "tool_name", event.toolName(),
                    "arguments", event.arguments(),
                    "thread_virtual", Thread.currentThread().isVirtual()
            );
        });
    }

    public VirtualThreadAgentToolUseExecutor(Function<AgentModelStreamEvent, Map<String, Object>> toolHandler) {
        this.executorService = Executors.newVirtualThreadPerTaskExecutor();
        this.toolHandler = toolHandler;
    }

    @Override
    public CompletableFuture<Map<String, Object>> execute(AgentModelStreamEvent event) {
        return CompletableFuture.supplyAsync(() -> toolHandler.apply(event), executorService);
    }

    @Override
    public void close() {
        executorService.close();
    }
}
