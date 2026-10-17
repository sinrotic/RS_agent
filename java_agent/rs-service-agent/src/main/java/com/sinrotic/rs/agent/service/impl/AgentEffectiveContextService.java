package com.sinrotic.rs.agent.service.impl;

import com.sinrotic.rs.agent.domain.session.AgentRecoveredTranscript;
import com.sinrotic.rs.agent.service.AgentTranscriptRecoveryService;
import java.util.*;

/** Rebuilds bounded conversational context from durable checkpoints and transcript, independently of Redis. */
public final class AgentEffectiveContextService {
    private static final int MAX_CHARACTERS = 6000;
    private final AgentTranscriptRecoveryService recovery;
    public AgentEffectiveContextService(AgentTranscriptRecoveryService recovery) { this.recovery = recovery; }

    public Map<String, Object> recover(String sessionId) {
        return recover(sessionId, null);
    }

    public Map<String, Object> recover(String sessionId,
            List<com.sinrotic.rs.agent.domain.session.AgentTranscriptEntry> transcript) {
        AgentRecoveredTranscript recovered = transcript == null ? recovery.recover(sessionId)
                : recovery.recover(sessionId, transcript);
        var messages = new ArrayList<Map<String, Object>>();
        recovered.summaryMessages().forEach(message -> add(messages, message.get("role"), message.get("content")));
        int summaryCount = messages.size();
        recovered.preservedEntries().forEach(message -> {
            if (message.containsKey("assistant_message")) add(messages, "assistant", message.get("assistant_message"));
            else add(messages, message.get("role"), message.get("content"));
        });
        for (var entry : recovered.tailEntries()) {
            if ("USER_MESSAGE".equals(entry.entryType())) add(messages, "user", entry.payload().get("content"));
            if ("ASSISTANT_FINAL".equals(entry.entryType())) add(messages, "assistant", entry.payload().get("assistant_message"));
            if ("ASSISTANT_MESSAGE".equals(entry.entryType())) add(messages, "assistant", entry.payload().get("content"));
        }
        // 摘要独立保留；对话按用户消息与其回答组成完整语义组，不截断单条消息。
        var groups = new ArrayList<List<Integer>>();
        for (int index = 0; index < messages.size(); index++) {
            if (index < summaryCount || "user".equals(messages.get(index).get("role")) || groups.isEmpty()
                    || groups.getLast().getFirst() < summaryCount) groups.add(new ArrayList<>());
            groups.getLast().add(index);
        }
        var selected = new TreeMap<Integer, Map<String, Object>>();
        int remaining = MAX_CHARACTERS;
        var priority = new LinkedHashSet<List<Integer>>();
        groups.stream().filter(group -> group.getFirst() < summaryCount).forEach(priority::add);
        groups.stream().filter(group -> group.stream().anyMatch(index -> "user".equals(messages.get(index).get("role"))))
                .findFirst().ifPresent(priority::add);
        for (int index = groups.size() - 1; index >= 0; index--) priority.add(groups.get(index));
        for (var group : priority) {
            int characters = group.stream().mapToInt(index -> String.valueOf(messages.get(index).get("content")).length()).sum();
            if (characters > remaining) continue;
            group.forEach(index -> selected.put(index, messages.get(index)));
            remaining -= characters;
        }
        boolean truncated = selected.size() != messages.size();
        return Map.of("messages", List.copyOf(selected.values()), "checkpoint_id", recovered.checkpointId(),
                "truncated", truncated, "omitted_message_count", messages.size() - selected.size(), "character_budget", MAX_CHARACTERS);
    }

    private void add(List<Map<String, Object>> messages, Object role, Object content) {
        if (role instanceof String name && Set.of("system", "user", "assistant").contains(name)
                && content instanceof String text && !text.isBlank()) messages.add(Map.of("role", name, "content", text));
    }
}
