package com.sinrotic.rs.recommend.service.impl;

import com.sinrotic.rs.recommend.domain.recall.ItemEmbeddingText;
import com.sinrotic.rs.recommend.domain.recall.VectorRecallItem;
import com.sinrotic.rs.recommend.service.CatalogEmbeddingTextClient;
import com.sinrotic.rs.recommend.service.SemanticItemRecallProvider;
import com.sinrotic.rs.recommend.service.TextEmbeddingClient;
import com.sinrotic.rs.recommend.service.VectorRecallClient;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

@Service
public class DefaultSemanticItemRecallProvider implements SemanticItemRecallProvider {

    private final TextEmbeddingClient textEmbeddingClient;
    private final VectorRecallClient vectorRecallClient;
    private final CatalogEmbeddingTextClient catalogEmbeddingTextClient;
    private final String modelKey;
    private final String collectionName;
    private RecommendationStageObservation observation = new RecommendationStageObservation(false);
    private RestProductQueryTowerClient queryTower;
    private static final org.slf4j.Logger LOG = org.slf4j.LoggerFactory.getLogger(DefaultSemanticItemRecallProvider.class);

    @org.springframework.beans.factory.annotation.Autowired
    public void setQueryTower(RestProductQueryTowerClient queryTower) { this.queryTower = queryTower; }

    @org.springframework.beans.factory.annotation.Autowired
    public void setObservation(RecommendationStageObservation observation) { this.observation = observation; }

    public DefaultSemanticItemRecallProvider(
            TextEmbeddingClient textEmbeddingClient,
            VectorRecallClient vectorRecallClient,
            CatalogEmbeddingTextClient catalogEmbeddingTextClient,
            @Value("${rs.recommend.embedding.model-key:bge-m3}") String modelKey,
            @Value("${rs.recommend.semantic-index.collection:rs_agent_semantic_items_bge_m3_v1}") String collectionName
    ) {
        this.textEmbeddingClient = textEmbeddingClient;
        this.vectorRecallClient = vectorRecallClient;
        this.catalogEmbeddingTextClient = catalogEmbeddingTextClient;
        this.modelKey = modelKey;
        this.collectionName = collectionName;
    }

    @Override
    public List<ItemEmbeddingText> recall(String requestId, String query, int limit) {
        if (query == null || query.isBlank() || limit <= 0) {
            return List.of();
        }
        List<List<Float>> embeddings = observation.measure("query_embedding", () -> textEmbeddingClient.embedTexts(
                modelKey, requestId + "_query_embed", List.of(query)));
        if (embeddings.isEmpty() || embeddings.getFirst().isEmpty()) {
            return List.of();
        }
        List<VectorRecallItem> hits = observation.measure("vector_search", () -> recallVectors(embeddings.getFirst(), limit));
        if (hits.isEmpty()) {
            return List.of();
        }
        List<String> itemIds = hits.stream()
                .map(VectorRecallItem::itemId)
                .filter(itemId -> itemId != null && !itemId.isBlank())
                .distinct()
                .toList();
        Map<String, ItemEmbeddingText> itemById = new LinkedHashMap<>();
        for (int start = 0; start < itemIds.size(); start += 100) {
            var batch = itemIds.subList(start, Math.min(start + 100, itemIds.size()));
            observation.measure("catalog_facts", () -> catalogEmbeddingTextClient.fetchItemEmbeddingTexts(batch))
                    .forEach(item -> itemById.putIfAbsent(item.itemId(), item));
        }
        return itemIds.stream().map(itemById::get).filter(java.util.Objects::nonNull).toList();
    }

    private List<VectorRecallItem> recallVectors(List<Float> bge, int limit) {
        var selected = new LinkedHashMap<String, VectorRecallItem>();
        if (queryTower != null && queryTower.enabled()) {
            try {
                var projected = queryTower.project(bge);
                int primaryLimit = Math.max(1, (int) Math.floor(limit * .65));
                vectorRecallClient.searchSimilarItems(queryTower.collection(), projected, primaryLimit)
                        .forEach(hit -> selected.putIfAbsent(hit.itemId(), hit));
            } catch (RuntimeException failure) { LOG.warn("Product query tower unavailable; using BGE recall ({})", failure.getClass().getSimpleName()); }
        }
        try {
            for (var hit : vectorRecallClient.searchSimilarItems(collectionName, bge, limit)) {
                if (selected.size() >= limit) break;
                selected.putIfAbsent(hit.itemId(), hit);
            }
        } catch (RuntimeException failure) {
            if (selected.isEmpty()) throw failure;
            LOG.warn("BGE supplement unavailable; returning product query recall ({})", failure.getClass().getSimpleName());
        }
        return List.copyOf(selected.values());
    }
}
