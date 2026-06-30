package com.sinrotic.rs.recommend.service;

import com.sinrotic.rs.recommend.domain.recall.UserEmbedding;
import com.sinrotic.rs.recommend.domain.recall.VectorRecallItem;
import com.sinrotic.rs.recommend.service.impl.DefaultTwoTowerRecallProvider;
import org.junit.jupiter.api.Test;

import java.util.ArrayList;
import java.util.List;
import java.util.Optional;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

class DefaultTwoTowerRecallProviderTest {

    @Test
    void cachedUserEmbeddingSkipsModelInferenceAndSearchesVectorIndex() {
        FakeEmbeddingStore store = new FakeEmbeddingStore(Optional.of(new UserEmbedding(
                "two_tower_youtube_dnn_epoch1",
                "user-1",
                List.of(0.1f, 0.2f, 0.3f),
                "cache"
        )));
        FakeUserTowerModelClient modelClient = new FakeUserTowerModelClient(List.of(0.9f, 0.8f, 0.7f));
        FakeVectorRecallClient vectorClient = new FakeVectorRecallClient(List.of(
                new VectorRecallItem("B001", 0.91),
                new VectorRecallItem("B002", 0.72)
        ));
        DefaultTwoTowerRecallProvider provider = new DefaultTwoTowerRecallProvider(
                store,
                new FakeUserHistoryClient(List.of("B010", "B011")),
                modelClient,
                vectorClient
        );

        var candidates = provider.recall("user-1", "req-1", 10);

        assertEquals(0, modelClient.calls);
        assertEquals(List.of(0.1f, 0.2f, 0.3f), vectorClient.lastVector);
        assertEquals("B001", candidates.getFirst().itemId());
        assertEquals("two_tower", candidates.getFirst().source());
        assertEquals(0.91, candidates.getFirst().recallScore());
    }

    @Test
    void missingUserEmbeddingUsesHistoryToInferAndCacheUserVectorBeforeSearch() {
        FakeEmbeddingStore store = new FakeEmbeddingStore(Optional.empty());
        FakeUserHistoryClient historyClient = new FakeUserHistoryClient(List.of("B010", "B011", "B012"));
        FakeUserTowerModelClient modelClient = new FakeUserTowerModelClient(List.of(0.4f, 0.5f, 0.6f));
        FakeVectorRecallClient vectorClient = new FakeVectorRecallClient(List.of(
                new VectorRecallItem("B100", 0.88)
        ));
        DefaultTwoTowerRecallProvider provider = new DefaultTwoTowerRecallProvider(
                store,
                historyClient,
                modelClient,
                vectorClient
        );

        var candidates = provider.recall("user-2", "req-2", 5);

        assertEquals(List.of("B010", "B011", "B012"), modelClient.lastHistoryItemIds);
        assertEquals(List.of(0.4f, 0.5f, 0.6f), store.saved.embedding());
        assertEquals(List.of(0.4f, 0.5f, 0.6f), vectorClient.lastVector);
        assertEquals("B100", candidates.getFirst().itemId());
    }

    @Test
    void missingUserEmbeddingWithTooLittleHistoryReturnsNoTwoTowerCandidates() {
        FakeEmbeddingStore store = new FakeEmbeddingStore(Optional.empty());
        FakeUserTowerModelClient modelClient = new FakeUserTowerModelClient(List.of(0.4f, 0.5f, 0.6f));
        FakeVectorRecallClient vectorClient = new FakeVectorRecallClient(List.of(
                new VectorRecallItem("B100", 0.88)
        ));
        DefaultTwoTowerRecallProvider provider = new DefaultTwoTowerRecallProvider(
                store,
                new FakeUserHistoryClient(List.of("B010")),
                modelClient,
                vectorClient
        );

        var candidates = provider.recall("user-3", "req-3", 5);

        assertTrue(candidates.isEmpty());
        assertEquals(0, modelClient.calls);
        assertEquals(0, vectorClient.calls);
    }

    private static final class FakeEmbeddingStore implements UserEmbeddingStore {
        private final Optional<UserEmbedding> cached;
        private UserEmbedding saved;

        private FakeEmbeddingStore(Optional<UserEmbedding> cached) {
            this.cached = cached;
        }

        @Override
        public Optional<UserEmbedding> find(String modelName, String userId) {
            return cached;
        }

        @Override
        public void save(UserEmbedding embedding) {
            this.saved = embedding;
        }
    }

    private static final class FakeUserHistoryClient implements UserHistoryClient {
        private final List<String> itemIds;

        private FakeUserHistoryClient(List<String> itemIds) {
            this.itemIds = itemIds;
        }

        @Override
        public List<String> recentItemIds(String userId, int limit) {
            return itemIds.stream().limit(limit).toList();
        }
    }

    private static final class FakeUserTowerModelClient implements UserTowerModelClient {
        private final List<Float> embedding;
        private int calls;
        private List<String> lastHistoryItemIds = List.of();

        private FakeUserTowerModelClient(List<Float> embedding) {
            this.embedding = embedding;
        }

        @Override
        public Optional<UserEmbedding> inferUserEmbedding(String modelName, String requestId, String userId, List<String> historyItemIds) {
            calls++;
            lastHistoryItemIds = new ArrayList<>(historyItemIds);
            return Optional.of(new UserEmbedding(modelName, userId, embedding, "user_tower"));
        }
    }

    private static final class FakeVectorRecallClient implements VectorRecallClient {
        private final List<VectorRecallItem> items;
        private int calls;
        private List<Float> lastVector = List.of();

        private FakeVectorRecallClient(List<VectorRecallItem> items) {
            this.items = items;
        }

        @Override
        public List<VectorRecallItem> searchSimilarItems(String collectionName, List<Float> queryVector, int limit) {
            calls++;
            lastVector = new ArrayList<>(queryVector);
            return items.stream().limit(limit).toList();
        }
    }
}
