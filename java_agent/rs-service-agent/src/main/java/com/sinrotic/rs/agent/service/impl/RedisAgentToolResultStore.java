package com.sinrotic.rs.agent.service.impl;

import com.sinrotic.rs.agent.config.AgentToolResultStoreProperties;
import com.sinrotic.rs.agent.domain.session.AgentToolResultLines;
import com.sinrotic.rs.agent.service.AgentToolResultStore;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Service;

import java.time.Duration;
import java.time.Instant;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

@Service
@ConditionalOnProperty(prefix = "rs.agent.result-store", name = "type", havingValue = "redis")
public class RedisAgentToolResultStore implements AgentToolResultStore {

    private static final int DEFAULT_LIMIT = 20;
    private static final int MAX_LIMIT = 200;

    private final StringRedisTemplate redisTemplate;

    private final AgentToolResultStoreProperties properties;

    public RedisAgentToolResultStore(StringRedisTemplate redisTemplate, AgentToolResultStoreProperties properties) {
        this.redisTemplate = redisTemplate;
        this.properties = properties;
    }

    @Override
    public void saveLines(String resultRef, List<String> lines) {
        if (resultRef == null || resultRef.isBlank()) {
            throw new IllegalArgumentException("result_ref is required");
        }
        List<String> safeLines = List.copyOf(lines == null ? List.of() : lines);
        int blockLineCount = Math.max(1, properties.getBlockLineCount());

        String linesKey = linesKey(resultRef);
        String metaKey = metaKey(resultRef);
        redisTemplate.delete(linesKey);
        redisTemplate.delete(metaKey);

        List<String> blocks = blocks(safeLines, blockLineCount);
        if (!blocks.isEmpty()) {
            redisTemplate.opsForList().rightPushAll(linesKey, blocks);
        }

        Map<String, String> meta = new HashMap<>();
        meta.put("total_lines", String.valueOf(safeLines.size()));
        meta.put("block_line_count", String.valueOf(blockLineCount));
        meta.put("created_at", Instant.now().toString());
        Duration ttl = properties.getTtl();
        if (ttl != null && !ttl.isZero() && !ttl.isNegative()) {
            meta.put("ttl_seconds", String.valueOf(ttl.toSeconds()));
        }
        redisTemplate.opsForHash().putAll(metaKey, meta);

        if (ttl != null && !ttl.isZero() && !ttl.isNegative()) {
            redisTemplate.expire(linesKey, ttl);
            redisTemplate.expire(metaKey, ttl);
        }
    }

    @Override
    public AgentToolResultLines readLines(String resultRef, int offset, int limit) {
        if (resultRef == null || resultRef.isBlank()) {
            throw new IllegalArgumentException("result_ref is required");
        }
        Map<Object, Object> rawMeta = redisTemplate.opsForHash().entries(metaKey(resultRef));
        if (rawMeta.isEmpty()) {
            throw new IllegalArgumentException("unknown result_ref: " + resultRef);
        }

        int totalLines = intMeta(rawMeta, "total_lines", 0);
        int blockLineCount = Math.max(1, intMeta(rawMeta, "block_line_count", properties.getBlockLineCount()));
        int normalizedOffset = Math.max(0, offset);
        int normalizedLimit = limit <= 0 ? DEFAULT_LIMIT : Math.min(limit, MAX_LIMIT);
        int from = Math.min(normalizedOffset, totalLines);
        int to = Math.min(from + normalizedLimit, totalLines);
        if (from >= to) {
            return new AgentToolResultLines(resultRef, normalizedOffset, normalizedLimit, totalLines, false, List.of());
        }

        int firstBlock = from / blockLineCount;
        int lastBlock = (to - 1) / blockLineCount;
        List<String> storedBlocks = redisTemplate.opsForList().range(linesKey(resultRef), firstBlock, lastBlock);
        if (storedBlocks == null) {
            storedBlocks = List.of();
        }

        List<String> expanded = new ArrayList<>();
        for (int blockOffset = 0; blockOffset < storedBlocks.size(); blockOffset++) {
            int blockIndex = firstBlock + blockOffset;
            int expectedLineCount = Math.min(blockLineCount, Math.max(0, totalLines - blockIndex * blockLineCount));
            expanded.addAll(unpackBlock(storedBlocks.get(blockOffset), expectedLineCount));
        }
        int expandedOffset = from - firstBlock * blockLineCount;
        int requestedSize = to - from;
        int safeTo = Math.min(expandedOffset + requestedSize, expanded.size());
        List<String> lines = expandedOffset >= safeTo ? List.of() : List.copyOf(expanded.subList(expandedOffset, safeTo));

        return new AgentToolResultLines(resultRef, normalizedOffset, normalizedLimit, totalLines, to < totalLines, lines);
    }

    private List<String> blocks(List<String> lines, int blockLineCount) {
        List<String> blocks = new ArrayList<>();
        for (int from = 0; from < lines.size(); from += blockLineCount) {
            int to = Math.min(from + blockLineCount, lines.size());
            blocks.add(String.join("\n", lines.subList(from, to)));
        }
        return List.copyOf(blocks);
    }

    private List<String> unpackBlock(String storedBlock, int expectedLineCount) {
        if (expectedLineCount <= 0) {
            return List.of();
        }
        if (storedBlock == null || storedBlock.isEmpty()) {
            return expectedLineCount == 1 ? List.of("") : List.of(storedBlock == null ? "" : storedBlock);
        }
        return List.of(storedBlock.split("\n", -1));
    }

    private int intMeta(Map<Object, Object> meta, String key, int fallback) {
        Object value = meta.get(key);
        if (value == null) {
            return fallback;
        }
        return Integer.parseInt(String.valueOf(value));
    }

    private String linesKey(String resultRef) {
        return resultRef + ":lines";
    }

    private String metaKey(String resultRef) {
        return resultRef + ":meta";
    }
}
