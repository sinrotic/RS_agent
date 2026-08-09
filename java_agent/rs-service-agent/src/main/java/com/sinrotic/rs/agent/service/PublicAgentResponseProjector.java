package com.sinrotic.rs.agent.service;

import com.sinrotic.rs.agent.domain.AgentPublicOutputBlock;
import com.sinrotic.rs.agent.domain.AgentRuntimeProfile;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/** Projects model-produced answer blocks onto the small, public wire contract. */
public final class PublicAgentResponseProjector {

    private static final int MAX_CONTENT_LENGTH = 4_000;
    private static final int MAX_CARD_SET_ID_LENGTH = 128;
    private static final int MAX_LAYOUT_LENGTH = 64;
    private static final int MAX_ITEM_COUNT = 20;

    public List<Map<String, Object>> projectBlocks(Object rawBlocks, AgentRuntimeProfile profile) {
        if (!(rawBlocks instanceof List<?> blocks) || blocks.isEmpty()) {
            throw new IllegalArgumentException("emit_final_answer requires non-empty blocks");
        }
        List<Map<String, Object>> projected = new ArrayList<>();
        for (Object rawBlock : blocks) {
            if (!(rawBlock instanceof Map<?, ?> block)) {
                throw new IllegalArgumentException("answer block must be an object");
            }
            projected.add(projectBlock(block, profile));
        }
        return List.copyOf(projected);
    }

    public Map<String, Object> projectBlock(Map<?, ?> rawBlock, AgentRuntimeProfile profile) {
        if (profile == null) {
            throw new IllegalArgumentException("agent runtime profile is required");
        }
        String type = requiredText(rawBlock.get("type"), "answer block type");
        String normalizedType = type.toLowerCase(java.util.Locale.ROOT);
        AgentPublicOutputBlock outputBlock = outputBlock(normalizedType);
        if (!profile.allowedOutputBlocks().contains(outputBlock)) {
            throw new IllegalArgumentException("answer block is not allowed by profile: " + type);
        }

        Map<String, Object> result = new LinkedHashMap<>();
        result.put("type", normalizedType);
        switch (outputBlock) {
            case TEXT, FOLLOWUP_QUESTION -> result.put("content", boundedText(rawBlock.get("content"), "content", MAX_CONTENT_LENGTH));
            case PRODUCT_CARDS -> projectProductCards(rawBlock, result);
            case COMPARISON_TABLE -> projectComparisonTable(rawBlock, result);
        }
        return Map.copyOf(result);
    }

    private void projectProductCards(Map<?, ?> rawBlock, Map<String, Object> result) {
        optionalText(rawBlock, result, "card_set_id", MAX_CARD_SET_ID_LENGTH);
        optionalItemIds(rawBlock, result);
        optionalText(rawBlock, result, "layout", MAX_LAYOUT_LENGTH);
        if (!result.containsKey("card_set_id") && !result.containsKey("item_ids")) {
            throw new IllegalArgumentException("product_cards requires card_set_id or item_ids");
        }
    }

    private void projectComparisonTable(Map<?, ?> rawBlock, Map<String, Object> result) {
        Object content = rawBlock.get("content");
        if (content instanceof String text && !text.isBlank()) {
            result.put("content", boundedText(text, "content", MAX_CONTENT_LENGTH));
            return;
        }
        optionalItemIds(rawBlock, result);
        optionalText(rawBlock, result, "layout", MAX_LAYOUT_LENGTH);
        if (!result.containsKey("item_ids")) {
            throw new IllegalArgumentException("comparison_table requires content or item_ids");
        }
    }

    private void optionalText(Map<?, ?> rawBlock, Map<String, Object> result, String key, int maxLength) {
        Object value = rawBlock.get(key);
        if (value == null) {
            return;
        }
        result.put(key, boundedText(value, key, maxLength));
    }

    private void optionalItemIds(Map<?, ?> rawBlock, Map<String, Object> result) {
        Object value = rawBlock.get("item_ids");
        if (value == null) {
            return;
        }
        if (!(value instanceof List<?> itemIds) || itemIds.size() > MAX_ITEM_COUNT) {
            throw new IllegalArgumentException("item_ids must be a list of at most " + MAX_ITEM_COUNT + " strings");
        }
        List<String> projected = new ArrayList<>();
        for (Object itemId : itemIds) {
            projected.add(requiredText(itemId, "item_id"));
        }
        result.put("item_ids", List.copyOf(projected));
    }

    private String boundedText(Object value, String field, int maxLength) {
        String text = requiredText(value, field);
        if (text.length() > maxLength) {
            throw new IllegalArgumentException(field + " exceeds maximum length " + maxLength);
        }
        return text;
    }

    private String requiredText(Object value, String field) {
        if (!(value instanceof String text) || text.isBlank()) {
            throw new IllegalArgumentException(field + " must be a non-blank string");
        }
        return text;
    }

    private AgentPublicOutputBlock outputBlock(String type) {
        try {
            return AgentPublicOutputBlock.valueOf(type.toUpperCase(java.util.Locale.ROOT));
        } catch (IllegalArgumentException error) {
            throw new IllegalArgumentException("unknown answer block type: " + type, error);
        }
    }
}
