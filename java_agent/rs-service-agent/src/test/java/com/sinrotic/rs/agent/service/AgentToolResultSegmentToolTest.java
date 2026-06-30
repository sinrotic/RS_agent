package com.sinrotic.rs.agent.service;

import com.sinrotic.rs.agent.service.impl.AgentModelStreamEvent;
import com.sinrotic.rs.agent.service.impl.InMemoryAgentRuntimeConfigurationService;
import com.sinrotic.rs.agent.service.impl.InMemoryAgentToolResultStore;
import com.sinrotic.rs.agent.service.impl.VirtualThreadAgentToolUseExecutor;
import com.sinrotic.rs.agent.service.impl.VirtualThreadAgentToolUseExecutor.TriFunction;
import org.junit.jupiter.api.Test;

import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;

class AgentToolResultSegmentToolTest {

    @Test
    void readToolResultLinesReturnsOnlyRequestedLinesWithPagingMetadata() {
        InMemoryAgentToolResultStore resultStore = new InMemoryAgentToolResultStore();
        resultStore.saveLines(
                "agent:result:sess_001:toolu_001",
                List.of("line-0", "line-1", "line-2", "line-3", "line-4"),
                2
        );
        VirtualThreadAgentToolUseExecutor executor = new VirtualThreadAgentToolUseExecutor(
                new InMemoryAgentRuntimeConfigurationService(),
                (TriFunction<String, String, Map<String, Object>, Map<String, Object>>) (requestId, agentName, arguments) -> Map.of("status", "SUCCESS"),
                resultStore
        );

        Map<String, Object> result = executor.execute(AgentModelStreamEvent.toolUse(
                "read_tool_result_lines",
                Map.of(
                        "result_ref", "agent:result:sess_001:toolu_001",
                        "offset", 1,
                        "limit", 2
                )
        )).join();

        assertThat(result).containsEntry("status", "SUCCESS");
        assertThat(result).containsEntry("tool_type", "tool_result_lines");
        assertThat(result).containsEntry("result_ref", "agent:result:sess_001:toolu_001");
        assertThat(result).containsEntry("offset", 1);
        assertThat(result).containsEntry("limit", 2);
        assertThat(result).containsEntry("total_lines", 5);
        assertThat(result).containsEntry("has_more", true);
        assertThat(result).containsEntry("thread_virtual", true);
        assertThat((List<String>) result.get("lines")).containsExactly("line-1", "line-2");
    }

    @Test
    void readToolResultLinesUsesOriginalResultLinesAcrossStorageBlocks() {
        InMemoryAgentToolResultStore resultStore = new InMemoryAgentToolResultStore();
        resultStore.saveLines(
                "agent:result:sess_001:toolu_002",
                List.of("result-line-0", "result-line-1", "result-line-2", "result-line-3", "result-line-4"),
                2
        );
        VirtualThreadAgentToolUseExecutor executor = new VirtualThreadAgentToolUseExecutor(
                new InMemoryAgentRuntimeConfigurationService(),
                (TriFunction<String, String, Map<String, Object>, Map<String, Object>>) (requestId, agentName, arguments) -> Map.of("status", "SUCCESS"),
                resultStore
        );

        Map<String, Object> result = executor.execute(AgentModelStreamEvent.toolUse(
                "read_tool_result_lines",
                Map.of(
                        "result_ref", "agent:result:sess_001:toolu_002",
                        "offset", 1,
                        "limit", 3
                )
        )).join();

        assertThat(result).containsEntry("total_lines", 5);
        assertThat(result).containsEntry("has_more", true);
        assertThat((List<String>) result.get("lines"))
                .containsExactly("result-line-1", "result-line-2", "result-line-3");
    }
}
