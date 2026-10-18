package com.sinrotic.rs.agent.service.impl;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.sinrotic.rs.agent.service.AgentToolResultStore;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;

class AgentToolResultExternalizer {

    private static final int MAX_INLINE_RESULT_LINES = 80;
    private static final int MAX_INLINE_RESULT_CHARS = 2_000;
    private static final int MAX_TOOL_RESULTS_MESSAGE_CHARS = 3_000;
    private static final int MAX_STORED_LINE_CHARS = 160;
    private static final int PREVIEW_LINE_COUNT = 20;

    private static final ObjectMapper OBJECT_MAPPER = new ObjectMapper();

    private final AgentToolResultStore toolResultStore;

    AgentToolResultExternalizer(AgentToolResultStore toolResultStore) {
        this.toolResultStore = toolResultStore == null ? new InMemoryAgentToolResultStore() : toolResultStore;
    }

    Map<String, Object> externalizeLargeNestedResult(AgentModelStreamEvent event, Map<String, Object> result) {
        if (result == null || !result.containsKey("result") || "read_tool_result_lines".equals(event.toolName())) {
            return result;
        }
        String serializedResult = serializedResult(result.get("result"));
        List<String> lines = serializedLines(serializedResult);
        if (lines.size() <= MAX_INLINE_RESULT_LINES && serializedResult.length() <= MAX_INLINE_RESULT_CHARS) {
            return result;
        }

        String resultRef = resultRef(event.toolName(), event.toolCallId());
        toolResultStore.saveLines(resultRef, lines);

        Map<String, Object> compact = new LinkedHashMap<>(result);
        compact.remove("result");
        compact.putAll(referencePayload(resultRef, lines, "json"));
        // 回查引用随调用变化；保留完整正文摘要，供无进展检查区别引用变化与隐藏内容刷新。
        try { compact.put("result_sha256", AgentModelRequestFingerprint.sha256(result.get("result"))); }
        catch (RuntimeException nonJson) { /* 缺摘要时仍保留引用差异，不猜测正文相同，也不破坏原有回查。 */ }
        return Map.copyOf(compact);
    }

    Object externalizeAggregateToolResults(Object value) {
        if (!(value instanceof List<?> toolResults)) {
            return value;
        }

        List<Candidate> candidates = candidates(toolResults);
        int totalSize = candidates.stream().mapToInt(Candidate::size).sum();
        if (totalSize <= MAX_TOOL_RESULTS_MESSAGE_CHARS) {
            return value;
        }

        List<Candidate> selected = selectCandidates(candidates, totalSize);
        if (selected.isEmpty()) {
            return value;
        }

        Map<Integer, Map<String, Object>> replacementsByIndex = new LinkedHashMap<>();
        for (Candidate candidate : selected) {
            String resultRef = resultRef("tool_results:" + candidate.toolName(), candidate.toolCallId());
            List<String> lines = serializedLines(candidate.serializedMetadata());
            toolResultStore.saveLines(resultRef, lines);

            Map<String, Object> replaced = new LinkedHashMap<>(candidate.toolResult());
            replaced.put("metadata", referencePayload(resultRef, lines, "json"));
            replacementsByIndex.put(candidate.index(), Map.copyOf(replaced));
        }

        ArrayList<Object> compacted = new ArrayList<>(toolResults.size());
        for (int index = 0; index < toolResults.size(); index++) {
            Map<String, Object> replacement = replacementsByIndex.get(index);
            compacted.add(replacement == null ? toolResults.get(index) : replacement);
        }
        return List.copyOf(compacted);
    }

    private List<Candidate> candidates(List<?> toolResults) {
        ArrayList<Candidate> candidates = new ArrayList<>();
        for (int index = 0; index < toolResults.size(); index++) {
            Object item = toolResults.get(index);
            if (!(item instanceof Map<?, ?> rawToolResult)) {
                continue;
            }
            Map<String, Object> toolResult = stringKeyMap(rawToolResult);
            Object metadata = toolResult.get("metadata");
            if (isAlreadyExternalized(metadata)) {
                continue;
            }
            String serialized = serializedResult(metadata);
            candidates.add(new Candidate(
                    index,
                    toolResult,
                    String.valueOf(toolResult.getOrDefault("tool_call_id", "")),
                    String.valueOf(toolResult.getOrDefault("tool_name", "tool")),
                    serialized,
                    serialized.length()
            ));
        }
        return List.copyOf(candidates);
    }

    private List<Candidate> selectCandidates(List<Candidate> candidates, int totalSize) {
        ArrayList<Candidate> selected = new ArrayList<>();
        int remaining = totalSize;
        for (Candidate candidate : candidates.stream()
                .sorted(Comparator.comparingInt(Candidate::size).reversed())
                .toList()) {
            if (remaining <= MAX_TOOL_RESULTS_MESSAGE_CHARS) {
                break;
            }
            selected.add(candidate);
            remaining -= candidate.size();
        }
        return List.copyOf(selected);
    }

    private boolean isAlreadyExternalized(Object metadata) {
        return metadata instanceof Map<?, ?> map && Boolean.TRUE.equals(map.get("result_externalized"));
    }

    private Map<String, Object> stringKeyMap(Map<?, ?> raw) {
        LinkedHashMap<String, Object> result = new LinkedHashMap<>();
        for (Map.Entry<?, ?> entry : raw.entrySet()) {
            if (entry.getKey() instanceof String key) {
                result.put(key, entry.getValue());
            }
        }
        return result;
    }

    private Map<String, Object> referencePayload(String resultRef, List<String> lines, String format) {
        return Map.of(
                "result_externalized", true,
                "result_ref", resultRef,
                "result_format", format,
                "preview_lines", List.copyOf(lines.subList(0, Math.min(PREVIEW_LINE_COUNT, lines.size()))),
                "total_lines", lines.size(),
                "has_more", lines.size() > PREVIEW_LINE_COUNT,
                "read_tool", "read_tool_result_lines"
        );
    }

    private String serializedResult(Object value) {
        try {
            return OBJECT_MAPPER.writerWithDefaultPrettyPrinter().writeValueAsString(value);
        } catch (JsonProcessingException ex) {
            return String.valueOf(value);
        }
    }

    private List<String> serializedLines(String serializedResult) {
        return Arrays.stream(serializedResult.split("\\R", -1))
                .flatMap(line -> splitLongLine(line).stream())
                .toList();
    }

    private List<String> splitLongLine(String line) {
        if (line.length() <= MAX_STORED_LINE_CHARS) {
            return List.of(line);
        }
        ArrayList<String> parts = new ArrayList<>();
        for (int from = 0; from < line.length(); from += MAX_STORED_LINE_CHARS) {
            parts.add(line.substring(from, Math.min(from + MAX_STORED_LINE_CHARS, line.length())));
        }
        return List.copyOf(parts);
    }

    private String resultRef(String toolName, String toolCallId) {
        String safeToolCallId = toolCallId == null || toolCallId.isBlank()
                ? "toolu_" + UUID.randomUUID().toString().substring(0, 8)
                : toolCallId;
        String safeToolName = toolName == null || toolName.isBlank() ? "tool" : toolName;
        return "agent:result:" + safeToolName + ":" + safeToolCallId;
    }

    private record Candidate(
            int index,
            Map<String, Object> toolResult,
            String toolCallId,
            String toolName,
            String serializedMetadata,
            int size
    ) {
    }
}
