package com.sinrotic.rs.agent.service;

import com.sinrotic.rs.agent.domain.vo.AgentStreamEventVO;

import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Optional;

/** Keeps internal tool and model events out of the public SSE stream. */
public final class PublicAgentStreamProjector {

    public Optional<AgentStreamEventVO> project(AgentStreamEventVO event) {
        if (event == null) {
            return Optional.empty();
        }
        return switch (event.event()) {
            case "token" -> Optional.of(new AgentStreamEventVO("token", event.requestId(), Map.of(
                    "delta", text(event.data().get("delta"), "")
            )));
            case "answer_block" -> Optional.of(new AgentStreamEventVO("answer_block", event.requestId(), answerBlock(event.data())));
            case "interrupted" -> Optional.of(new AgentStreamEventVO("interrupted", event.requestId(), Map.of(
                    "reason", text(event.data().get("reason"), "interrupted")
            )));
            case "done" -> Optional.of(new AgentStreamEventVO("done", event.requestId(), done(event.data())));
            default -> Optional.empty();
        };
    }

    private Map<String, Object> answerBlock(Map<String, Object> data) {
        if ("a2ui".equals(data.get("type"))) {
            return Map.of("type", "a2ui", "messages", new A2uiMessageProjector().project(data.get("messages")));
        }
        Map<String, Object> result = new LinkedHashMap<>();
        for (String key : new String[]{"type", "content", "card_set_id", "item_ids", "layout", "messages"}) {
            Object value = data.get(key);
            if (value != null) {
                result.put(key, value);
            }
        }
        return Map.copyOf(result);
    }

    private Map<String, Object> done(Map<String, Object> data) {
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("done", true);
        if (data.get("response") instanceof Map<?, ?> response) {
            Map<String, Object> publicResponse = new LinkedHashMap<>();
            for (String key : new String[]{"request_id", "session_id", "profile_user_id", "card_set_id",
                    "turn_index", "assistant_message", "recommended_items", "answer_blocks"}) {
                Object value = response.get(key);
                if (value != null) publicResponse.put(key, value);
            }
            if (response.get("degradation_reasons") instanceof java.util.List<?> reasons) {
                publicResponse.put("degradation_reasons", AgentRecommendationDelivery.publicReasons(reasons));
            }
            result.put("response", Map.copyOf(publicResponse));
        }
        Object finishReason = data.get("finish_reason");
        if (finishReason instanceof String text && !text.isBlank()) {
            result.put("finish_reason", text);
        }
        return Map.copyOf(result);
    }

    private String text(Object value, String fallback) {
        return value instanceof String text && !text.isBlank() ? text : fallback;
    }
}
