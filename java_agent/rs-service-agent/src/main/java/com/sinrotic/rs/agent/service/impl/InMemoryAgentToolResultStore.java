package com.sinrotic.rs.agent.service.impl;

import com.sinrotic.rs.agent.domain.session.AgentToolResultLines;
import com.sinrotic.rs.agent.service.AgentToolResultStore;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.stereotype.Service;

import java.util.List;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ConcurrentMap;

@Service
@ConditionalOnProperty(prefix = "rs.agent.result-store", name = "type", havingValue = "memory", matchIfMissing = true)
public class InMemoryAgentToolResultStore implements AgentToolResultStore {

    private static final int DEFAULT_BLOCK_LINE_COUNT = 50;
    private static final int DEFAULT_LIMIT = 20;
    private static final int MAX_LIMIT = 200;

    private final ConcurrentMap<String, StoredResult> resultsByRef = new ConcurrentHashMap<>();

    @Override
    public void saveLines(String resultRef, List<String> lines) {
        saveLines(resultRef, lines, DEFAULT_BLOCK_LINE_COUNT);
    }

    public void saveLines(String resultRef, List<String> lines, int blockLineCount) {
        if (resultRef == null || resultRef.isBlank()) {
            throw new IllegalArgumentException("result_ref is required");
        }
        List<String> safeLines = List.copyOf(lines == null ? List.of() : lines);
        int safeBlockLineCount = Math.max(1, blockLineCount);
        resultsByRef.put(resultRef, new StoredResult(safeLines.size(), safeBlockLineCount, blocks(safeLines, safeBlockLineCount)));
    }

    @Override
    public AgentToolResultLines readLines(String resultRef, int offset, int limit) {
        if (resultRef == null || resultRef.isBlank()) {
            throw new IllegalArgumentException("result_ref is required");
        }
        StoredResult result = resultsByRef.get(resultRef);
        if (result == null) {
            throw new IllegalArgumentException("unknown result_ref: " + resultRef);
        }
        int normalizedOffset = Math.max(0, offset);
        int normalizedLimit = limit <= 0 ? DEFAULT_LIMIT : Math.min(limit, MAX_LIMIT);
        int from = Math.min(normalizedOffset, result.totalLines());
        int to = Math.min(from + normalizedLimit, result.totalLines());
        return new AgentToolResultLines(
                resultRef,
                normalizedOffset,
                normalizedLimit,
                result.totalLines(),
                to < result.totalLines(),
                readLines(result, from, to)
        );
    }

    private List<List<String>> blocks(List<String> lines, int blockLineCount) {
        java.util.ArrayList<List<String>> blocks = new java.util.ArrayList<>();
        for (int from = 0; from < lines.size(); from += blockLineCount) {
            int to = Math.min(from + blockLineCount, lines.size());
            blocks.add(lines.subList(from, to));
        }
        return List.copyOf(blocks);
    }

    private List<String> readLines(StoredResult result, int from, int to) {
        if (from >= to) {
            return List.of();
        }
        int firstBlock = from / result.blockLineCount();
        int lastBlock = (to - 1) / result.blockLineCount();
        java.util.ArrayList<String> expanded = new java.util.ArrayList<>();
        for (int blockIndex = firstBlock; blockIndex <= lastBlock; blockIndex++) {
            expanded.addAll(result.blocks().get(blockIndex));
        }
        int expandedOffset = from - firstBlock * result.blockLineCount();
        return List.copyOf(expanded.subList(expandedOffset, expandedOffset + (to - from)));
    }

    private record StoredResult(
            int totalLines,
            int blockLineCount,
            List<List<String>> blocks
    ) {
    }
}
