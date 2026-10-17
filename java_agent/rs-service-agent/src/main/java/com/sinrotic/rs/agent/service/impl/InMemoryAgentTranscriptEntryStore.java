package com.sinrotic.rs.agent.service.impl;

import com.sinrotic.rs.agent.domain.session.AgentTranscriptEntry;
import com.sinrotic.rs.agent.service.AgentTranscriptEntryStore;

import java.util.List;
import java.util.NavigableMap;
import java.util.Optional;
import java.util.TreeMap;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ConcurrentMap;

public class InMemoryAgentTranscriptEntryStore implements AgentTranscriptEntryStore {

    private final ConcurrentMap<String, NavigableMap<Long, AgentTranscriptEntry>> entries = new ConcurrentHashMap<>();

    @Override
    public void append(AgentTranscriptEntry entry) {
        entries.compute(entry.sessionId(), (sessionId, current) -> {
            NavigableMap<Long, AgentTranscriptEntry> next = current == null ? new TreeMap<>() : new TreeMap<>(current);
            next.put(entry.seq(), entry);
            return next;
        });
    }

    @Override
    public Optional<AgentTranscriptEntry> latest(String sessionId) {
        NavigableMap<Long, AgentTranscriptEntry> sessionEntries = entries.get(sessionId);
        if (sessionEntries == null || sessionEntries.isEmpty()) {
            return Optional.empty();
        }
        return Optional.of(sessionEntries.lastEntry().getValue());
    }

    @Override
    public List<AgentTranscriptEntry> tailAfter(String sessionId, long exclusiveSeq) {
        NavigableMap<Long, AgentTranscriptEntry> sessionEntries = entries.get(sessionId);
        if (sessionEntries == null) {
            return List.of();
        }
        return List.copyOf(sessionEntries.tailMap(exclusiveSeq, false).values());
    }
}
