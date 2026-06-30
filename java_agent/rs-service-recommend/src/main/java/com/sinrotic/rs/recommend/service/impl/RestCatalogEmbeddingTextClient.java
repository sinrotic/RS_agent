package com.sinrotic.rs.recommend.service.impl;

import com.sinrotic.rs.recommend.domain.recall.ItemEmbeddingText;
import com.sinrotic.rs.recommend.service.CatalogEmbeddingTextClient;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.core.ParameterizedTypeReference;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestClient;

import java.util.List;
import java.util.Map;

@Service
public class RestCatalogEmbeddingTextClient implements CatalogEmbeddingTextClient {

    private final RestClient restClient;

    public RestCatalogEmbeddingTextClient(
            RestClient.Builder restClientBuilder,
            @Value("${rs.catalog.base-url:http://rs-service-catalog}") String catalogBaseUrl
    ) {
        this.restClient = restClientBuilder.baseUrl(catalogBaseUrl).build();
    }

    @Override
    public List<ItemEmbeddingText> fetchActiveItemEmbeddingTexts(String afterItemId, int limit) {
        List<ItemEmbeddingText> response = restClient.post()
                .uri("/internal/catalog/context/active-item-embedding-texts")
                .body(Map.of(
                        "after_item_id", afterItemId == null ? "" : afterItemId,
                        "limit", limit
                ))
                .retrieve()
                .body(new ParameterizedTypeReference<>() {
                });
        return response == null ? List.of() : response;
    }
}
