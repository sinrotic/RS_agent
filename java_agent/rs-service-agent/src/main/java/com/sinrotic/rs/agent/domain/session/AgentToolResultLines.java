package com.sinrotic.rs.agent.domain.session;

import java.util.List;

/**
 * One offset/limit line range of a large tool result.
 */
public record AgentToolResultLines(
        String resultRef,
        int offset,
        int limit,
        int totalLines,
        boolean hasMore,
        List<String> lines
) {

    public AgentToolResultLines {
        lines = lines == null ? List.of() : List.copyOf(lines);
    }
}
