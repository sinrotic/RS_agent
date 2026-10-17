package com.sinrotic.rs.agent.service.impl;

import com.fasterxml.jackson.annotation.JsonProperty;
import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.sinrotic.rs.agent.config.AgentRecommendationProperties;
import com.sinrotic.rs.agent.domain.dto.AgentChatRequestDTO;
import com.sinrotic.rs.agent.domain.vo.AgentRecommendedItemVO;
import com.sinrotic.rs.agent.service.AgentModelProviderHttpClient;
import com.sinrotic.rs.agent.service.AgentRecommendationClient;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/** Calls the agent-facing candidate endpoint and keeps its response private to the adapter. */
public class HttpAgentRecommendationClient implements AgentRecommendationClient {

    private final AgentRecommendationProperties properties;
    private final AgentModelProviderHttpClient httpClient;
    private final ObjectMapper objectMapper;

    public HttpAgentRecommendationClient(
            AgentRecommendationProperties properties,
            AgentModelProviderHttpClient httpClient
    ) {
        this(properties, httpClient, new ObjectMapper());
    }

    HttpAgentRecommendationClient(
            AgentRecommendationProperties properties,
            AgentModelProviderHttpClient httpClient,
            ObjectMapper objectMapper
    ) {
        this.properties = properties;
        this.httpClient = httpClient;
        this.objectMapper = objectMapper;
    }

    @Override
    public List<AgentRecommendedItemVO> recommend(AgentChatRequestDTO request) {
        return recommendDelivery(request).items();
    }

    @Override
    public com.sinrotic.rs.agent.service.AgentRecommendationDelivery recommendDelivery(AgentChatRequestDTO request) {
        boolean hasQuery = hasText(request.userMessage());
        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("agent_id", "rs_agent");
        payload.put("task_id", request.sessionId());
        payload.put("profile_user_id", request.profileUserId());
        payload.put("account_id", String.valueOf(request.resolvedContext()
                .getOrDefault("authenticated_account_id", request.profileUserId())));
        if (hasQuery) {
            payload.put("session_id", request.sessionId());
            payload.put("query", request.userMessage());
            payload.put("candidate_item_ids", List.of());
            payload.put("return_count", request.resolvedLimit());
        } else {
            payload.put("limit", request.resolvedLimit());
        }
        payload.put("scene", scene(request));
        payload.put("constraints", request.resolvedContext().getOrDefault("constraints", Map.of()));

        try {
            String response = httpClient.postJson(
                    properties.getBaseUrl() + pathFor(hasQuery),
                    objectMapper.writeValueAsString(payload),
                    "application/json"
            );
            CandidatesResponse candidates = objectMapper.readValue(response, CandidatesResponse.class);
            List<AgentRecommendedItemVO> items = (candidates.candidates() == null ? List.<Candidate>of() : candidates.candidates()).stream()
                    .map(candidate -> toAgentItem(candidate, candidates.requestId()))
                    .toList();
            List<String> reasons = candidates.degradationReasons();
            Map<String, com.sinrotic.rs.agent.service.AgentRecommendationFact> facts = new LinkedHashMap<>();
            if (candidates.candidates() != null) {
                for (Candidate candidate : candidates.candidates()) {
                    if (candidate.itemId() != null) facts.put(candidate.itemId(),
                            new com.sinrotic.rs.agent.service.AgentRecommendationFact(candidate.price()));
                }
            }
            return new com.sinrotic.rs.agent.service.AgentRecommendationDelivery(items, reasons, facts);
        } catch (JsonProcessingException ex) {
            throw new IllegalStateException("failed to decode recommendation response", ex);
        } catch (RuntimeException ex) {
            throw new IllegalStateException("recommendation service unavailable", ex);
        }
    }

    private AgentRecommendedItemVO toAgentItem(Candidate candidate, String cardSetId) {
        String reason = firstNonBlank(candidate.reasonHint(), candidate.shortText());
        return new AgentRecommendedItemVO(
                candidate.itemId(),
                candidate.title(),
                candidate.categoryPath(),
                0.0,
                reason,
                cardSetId == null ? "" : cardSetId
        );
    }

    private String scene(AgentChatRequestDTO request) {
        Object scene = request.resolvedContext().get("scene");
        return scene instanceof String value && !value.isBlank() ? value : "agent_chat";
    }

    private String pathFor(boolean hasQuery) {
        return hasQuery ? properties.getSemanticRecallPath() : properties.getCandidatesPath();
    }

    private boolean hasText(String value) {
        return value != null && !value.isBlank();
    }

    private String firstNonBlank(String primary, String fallback) {
        if (primary != null && !primary.isBlank()) {
            return primary;
        }
        return fallback == null ? "" : fallback;
    }

    @JsonIgnoreProperties(ignoreUnknown = true)
    private record CandidatesResponse(
            @JsonProperty("request_id") String requestId,
            List<Candidate> candidates,
            @JsonProperty("degradation_reasons") List<String> degradationReasons
    ) {
    }

    @JsonIgnoreProperties(ignoreUnknown = true)
    private record Candidate(
            @JsonProperty("item_id") String itemId,
            String title,
            java.math.BigDecimal price,
            @JsonProperty("category_path") String categoryPath,
            @JsonProperty("reason_hint") String reasonHint,
            @JsonProperty("short_text") String shortText
    ) {
    }
}
