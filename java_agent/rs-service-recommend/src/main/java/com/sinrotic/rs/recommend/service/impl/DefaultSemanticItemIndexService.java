package com.sinrotic.rs.recommend.service.impl;

import com.sinrotic.rs.recommend.domain.recall.ItemEmbeddingText;
import com.sinrotic.rs.recommend.domain.recall.ItemVectorDocument;
import com.sinrotic.rs.recommend.domain.vo.SemanticItemIndexResultVO;
import com.sinrotic.rs.recommend.service.CatalogEmbeddingTextClient;
import com.sinrotic.rs.recommend.service.ItemVectorIndexClient;
import com.sinrotic.rs.recommend.service.SemanticItemIndexService;
import com.sinrotic.rs.recommend.service.TextEmbeddingClient;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

import java.util.ArrayList;
import java.util.List;

@Service
public class DefaultSemanticItemIndexService implements SemanticItemIndexService {

    private final CatalogEmbeddingTextClient catalogEmbeddingTextClient;
    private final TextEmbeddingClient textEmbeddingClient;
    private final ItemVectorIndexClient itemVectorIndexClient;
    private final String modelKey;
    private final String collectionName;

    public DefaultSemanticItemIndexService(
            CatalogEmbeddingTextClient catalogEmbeddingTextClient,
            TextEmbeddingClient textEmbeddingClient,
            ItemVectorIndexClient itemVectorIndexClient,
            @Value("${rs.recommend.embedding.model-key:bge-m3}") String modelKey,
            @Value("${rs.recommend.semantic-index.collection:rs_agent_semantic_items_bge_m3_v1}") String collectionName
    ) {
        this.catalogEmbeddingTextClient = catalogEmbeddingTextClient;
        this.textEmbeddingClient = textEmbeddingClient;
        this.itemVectorIndexClient = itemVectorIndexClient;
        this.modelKey = modelKey;
        this.collectionName = collectionName;
    }

    @Override
    public SemanticItemIndexResultVO rebuild(String requestId, int pageSize, int maxPages) {
        int indexedCount = 0;
        int pageCount = 0;
        String afterItemId = null;
        for (int page = 0; page < maxPages; page++) {
            List<ItemEmbeddingText> items = catalogEmbeddingTextClient.fetchActiveItemEmbeddingTexts(afterItemId, pageSize);
            if (items.isEmpty()) {
                break;
            }
            pageCount++;
            List<List<Float>> vectors = textEmbeddingClient.embedTexts(
                    modelKey,
                    requestId + "_page_" + pageCount,
                    items.stream().map(ItemEmbeddingText::embeddingText).toList()
            );
            List<ItemVectorDocument> documents = toDocuments(items, vectors);
            indexedCount += itemVectorIndexClient.upsertItems(collectionName, documents);
            afterItemId = items.getLast().itemId();
        }
        return new SemanticItemIndexResultVO(requestId, collectionName, modelKey, indexedCount, pageCount, afterItemId);
    }

    private List<ItemVectorDocument> toDocuments(List<ItemEmbeddingText> items, List<List<Float>> vectors) {
        if (items.size() != vectors.size()) {
            throw new IllegalStateException("embedding vector count does not match item count");
        }
        List<ItemVectorDocument> documents = new ArrayList<>();
        for (int i = 0; i < items.size(); i++) {
            ItemEmbeddingText item = items.get(i);
            documents.add(new ItemVectorDocument(
                    item.itemId(),
                    vectors.get(i),
                    item.title(),
                    item.category(),
                    item.categoryPath(),
                    item.brand(),
                    item.price(),
                    item.embeddingText(),
                    item.attributes()
            ));
        }
        return documents;
    }
}
