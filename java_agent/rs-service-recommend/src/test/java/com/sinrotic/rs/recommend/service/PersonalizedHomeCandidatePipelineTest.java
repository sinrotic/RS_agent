package com.sinrotic.rs.recommend.service;

import com.sinrotic.rs.recommend.domain.delivery.*;
import com.sinrotic.rs.recommend.domain.dto.HomeRecommendRequestDTO;
import com.sinrotic.rs.recommend.domain.preference.*;
import com.sinrotic.rs.recommend.domain.recall.ItemEmbeddingText;
import com.sinrotic.rs.recommend.service.impl.*;
import org.junit.jupiter.api.Test;
import java.math.BigDecimal;
import java.time.Instant;
import java.util.*;
import java.util.concurrent.atomic.AtomicReference;
import static org.junit.jupiter.api.Assertions.*;

class PersonalizedHomeCandidatePipelineTest {
    private static ItemEmbeddingText item(String id, String category) {
        return new ItemEmbeddingText(id, category + " " + id, category + " " + id, category, category,
                "brand-" + id, BigDecimal.TEN, Map.of());
    }
    private final RecommendationIdentity identity = new RecommendationIdentity("account", "audio", "session");
    private final HomeRecommendRequestDTO request = new HomeRecommendRequestDTO("session", "home", 6, "", false);
    private final List<ItemEmbeddingText> audio = java.util.stream.IntStream.range(0, 30).mapToObj(i -> item("a" + i, "Headphones")).toList();
    private final List<ItemEmbeddingText> office = java.util.stream.IntStream.range(0, 30).mapToObj(i -> item("o" + i, "Office")).toList();
    private final InMemoryRecommendationDeliveryStore deliveries = new InMemoryRecommendationDeliveryStore();
    private final AtomicReference<String> rankQuery = new AtomicReference<>();
    private final CatalogEmbeddingTextClient catalog = new CatalogEmbeddingTextClient() {
        public List<ItemEmbeddingText> fetchActiveItemEmbeddingTexts(String cursor, int limit) { return office; }
        public List<ItemEmbeddingText> fetchItemEmbeddingTexts(List<String> ids) {
            return ids.stream().map(id -> item(id, id.startsWith("a") ? "Headphones" : "Office")).toList();
        }
    };
    private PersonalizedHomeCandidatePipeline pipeline(HomeModelRanker model) {
        return new PersonalizedHomeCandidatePipeline(catalog, (profile, limit) -> List.of(profile.equals("audio") ? "audio-seed" : "office-seed"),
                (id, query, limit) -> query.contains("Headphones") ? audio : office, model, deliveries, new PreferenceAwareFinalReranker());
    }
    private HomeModelRanker model() {
        return (id, query, candidates) -> {
            rankQuery.set(query);
            Map<String, Double> scores = new HashMap<>();
            candidates.forEach(c -> scores.put(c.itemId(), c.category().equals(query.contains("Headphones") ? "Headphones" : "Office") ? .95 : .1));
            return scores;
        };
    }
    private Set<String> ids(PersonalizedHomeCandidatePipeline.Selection result) {
        return result.items().stream().map(c -> c.item().itemId()).collect(java.util.stream.Collectors.toSet());
    }
    @Test void differentHistoriesProduceDifferentCandidatesAndModelScores() {
        var pipeline = pipeline(model());
        var first = pipeline.select("r1", identity, request, OnlinePreferenceSnapshot.empty());
        var second = pipeline.select("r2", new RecommendationIdentity("other", "office", "other-session"), request, OnlinePreferenceSnapshot.empty());
        assertEquals(6, first.items().size());
        assertNotEquals(ids(first), ids(second));
        assertTrue(first.items().stream().anyMatch(c -> c.baseScore() == .95));
        assertEquals(6, first.stages().get("final"));
    }
    @Test void latestLikeChangesRecallIntentInsteadOfOnlyReorderingOldPage() {
        var liked = new ItemPreference("feedback", "like", "office-liked", "Office", "", Map.of(), 1, Instant.now());
        var result = pipeline(model()).select("r1", identity, request,
                new OnlinePreferenceSnapshot(1, Map.of(liked.itemId(), liked), List.of("feedback")));
        assertTrue(rankQuery.get() != null && rankQuery.get().contains("Office"));
        assertTrue(result.items().stream().anyMatch(c -> c.item().itemId().startsWith("o")));
    }
    @Test void recentDeliveryIsExcludedAcrossSessionsAndOutagesAreVisible() {
        deliveries.save(new RecommendationDelivery("previous", new RecommendationIdentity("account", "audio", "old-session"), "home", 0,
                audio.stream().limit(8).map(c -> new RecommendationDeliveryItem(c.itemId(), 1, .9, c.category(), c.brand(), Map.of())).toList(),
                Instant.now().minusSeconds(60), Instant.now().plusSeconds(3600)));
        var result = pipeline((id, query, candidates) -> { throw new IllegalStateException("model down"); })
                .select("r1", identity, request, OnlinePreferenceSnapshot.empty());
        assertEquals(6, result.items().size());
        assertTrue(Collections.disjoint(ids(result), audio.stream().limit(8).map(ItemEmbeddingText::itemId).toList()));
        assertTrue(result.degradationReasons().contains("model_rank_unavailable"));
    }
    @Test void feedbackCursorCannotReadAnotherProfilesDelivery() {
        deliveries.save(new RecommendationDelivery("foreign", new RecommendationIdentity("other", "other", "other"), "home", 0,
                List.of(), Instant.now(), Instant.now().plusSeconds(3600)));
        assertThrows(org.springframework.web.server.ResponseStatusException.class, () -> pipeline(model()).select("r1", identity,
                new HomeRecommendRequestDTO("session", "home", 6, "rerank:foreign", false), OnlinePreferenceSnapshot.empty()));
    }

    @Test void homeEntryUsesPipelineRecordsDeliveryAndReportsRealStageCounts() {
        var trace = new InMemoryRecommendTraceService();
        var service = new DefaultHomeRecommendService(trace, catalog,
                new DefaultRecommendationDeliveryService(deliveries, java.time.Clock.systemUTC(), java.time.Duration.ofHours(24)),
                new InMemoryOnlinePreferenceStore(), new PreferenceAwareFinalReranker());
        service.setPersonalizedPipeline(pipeline(model()));
        var first = service.recommendHome(identity, request);
        assertEquals("personalized", first.recommendationMode());
        assertTrue(first.items().stream().anyMatch(item -> item.sourceTags().contains("bge_reranker")));
        assertTrue(trace.getTrace(first.requestId()).stageCounts().get("recall") > first.items().size());
        assertTrue(deliveries.findByRequestId(first.requestId()).isPresent());
        var next = service.recommendHome(identity, new HomeRecommendRequestDTO("session", "home", 6, first.nextCursor(), false));
        assertTrue(Collections.disjoint(first.items().stream().map(item -> item.itemId()).toList(),
                next.items().stream().map(item -> item.itemId()).toList()));
    }

    @Test void uncoveredSemanticCategoryStillFindsSimilarCatalogItems() {
        var software = java.util.stream.IntStream.range(0, 20).mapToObj(i -> item("software-" + i, "Software")).toList();
        var categoryCatalog = new CatalogEmbeddingTextClient() {
            public List<ItemEmbeddingText> fetchActiveItemEmbeddingTexts(String cursor, int limit) { return office; }
            public List<ItemEmbeddingText> fetchItemEmbeddingTexts(List<String> ids) { return List.of(item("liked", "Software")); }
            public List<ItemEmbeddingText> categoryCandidates(String category, String seed, int limit) { return software; }
        };
        var pipeline = new PersonalizedHomeCandidatePipeline(categoryCatalog, (id, limit) -> List.of(),
                (id, query, limit) -> List.of(), (id, query, candidates) -> candidates.stream().collect(
                java.util.stream.Collectors.toMap(ItemEmbeddingText::itemId, c -> c.category().equals("Software") ? .9 : .01)),
                deliveries, new PreferenceAwareFinalReranker());
        var preference = new ItemPreference("like", "like", "liked", "Software", "", Map.of(), 1, Instant.now());
        var result = pipeline.select("r1", identity, request, new OnlinePreferenceSnapshot(1, Map.of("liked", preference), List.of("like")));
        assertTrue(result.items().stream().filter(c -> c.item().category().equals("Software")).count() >= 3);
    }

    @Test void genericMetadataFlagsDoNotCreateAnInterestBoost() {
        var discontinued = Map.of("Is Discontinued By Manufacturer", "Yes");
        var candidate = new ItemEmbeddingText("unrelated", "speaker", "speaker", "Audio", "Audio", "B", BigDecimal.TEN, discontinued);
        var liked = new ItemPreference("like", "like", "book", "Books", "A", discontinued, 1, Instant.now());
        var result = new PreferenceAwareFinalReranker().rerank(List.of(candidate),
                new OnlinePreferenceSnapshot(1, Map.of("book", liked), List.of("like")), 1);
        assertEquals(0, result.getFirst().preferenceAdjustment());
    }

    // Replays the production pattern: identical backpack models have different IDs and categories.
    @Test void refreshDoesNotSubstituteColorVariantsAndActuallyShowsExploration() {
        var current = new ArrayList<ItemEmbeddingText>();
        var previous = new ArrayList<ItemEmbeddingText>();
        for (int i = 0; i < 6; i++) {
            previous.add(backpack("old-" + i, "Gray", "category-" + i, i));
            current.add(backpack("new-" + i, "Black", "other-category-" + i, i));
        }
        var exploration = explorationProducts();
        var all = new HashMap<String, ItemEmbeddingText>();
        previous.forEach(item -> all.put(item.itemId(), item));
        current.forEach(item -> all.put(item.itemId(), item));
        var replayCatalog = new CatalogEmbeddingTextClient() {
            public List<ItemEmbeddingText> fetchActiveItemEmbeddingTexts(String cursor, int limit) { return exploration; }
            public List<ItemEmbeddingText> fetchItemEmbeddingTexts(List<String> ids) {
                return ids.stream().map(all::get).filter(Objects::nonNull).toList();
            }
        };
        deliveries.save(new RecommendationDelivery("previous", identity, "home", 0,
                previous.stream().map(c -> new RecommendationDeliveryItem(c.itemId(), 1, .99, c.category(), c.brand(), c.attributes())).toList(),
                Instant.now().minusSeconds(30), Instant.now().plusSeconds(3600)));
        var pipeline = new PersonalizedHomeCandidatePipeline(replayCatalog, (id, limit) -> List.of("old-0"),
                (id, query, limit) -> current, (id, query, candidates) -> candidates.stream().collect(
                java.util.stream.Collectors.toMap(ItemEmbeddingText::itemId, c -> c.itemId().startsWith("new-") ? .99 : .01)),
                deliveries, new PreferenceAwareFinalReranker());
        var result = pipeline.select("r2", identity, new HomeRecommendRequestDTO("session", "home", 6, "feed:previous", false), OnlinePreferenceSnapshot.empty());
        assertEquals(6, result.items().size());
        assertTrue(result.items().stream().noneMatch(c -> c.item().itemId().startsWith("new-")),
                "换批不能用上一批同品牌同型号的换色商品补满，哪怕 ID 和类目不同");
    }

    @Test void firstPageReservesRealExplorationEvenWhenSemanticScoresDominate() {
        var semanticItems = java.util.stream.IntStream.range(0, 6)
                .mapToObj(i -> backpack("bag-" + i, "Black", "category-" + i, i)).toList();
        var replayCatalog = new CatalogEmbeddingTextClient() {
            public List<ItemEmbeddingText> fetchActiveItemEmbeddingTexts(String cursor, int limit) { return explorationProducts(); }
            public List<ItemEmbeddingText> fetchItemEmbeddingTexts(List<String> ids) { return List.of(semanticItems.getFirst()); }
        };
        var pipeline = new PersonalizedHomeCandidatePipeline(replayCatalog, (id, limit) -> List.of("seed"),
                (id, query, limit) -> semanticItems, (id, query, candidates) -> candidates.stream().collect(
                java.util.stream.Collectors.toMap(ItemEmbeddingText::itemId, c -> c.itemId().startsWith("bag-") ? .99 : .01)),
                deliveries, new PreferenceAwareFinalReranker());
        var result = pipeline.select("first", identity, request, OnlinePreferenceSnapshot.empty());
        assertTrue(result.items().stream().filter(c -> c.reasonTags().contains("catalog_exploration")).count() >= 2,
                "无偏好加分的语义商品不能冒充探索席位");
    }

    @Test void similarCursorCannotReadAnotherAccountsDelivery() {
        deliveries.save(new RecommendationDelivery("foreign", new RecommendationIdentity("other", "other", "other"), "home", 0,
                List.of(), Instant.now(), Instant.now().plusSeconds(3600)));
        assertThrows(org.springframework.web.server.ResponseStatusException.class, () -> pipeline(model()).select("r1", identity,
                new HomeRecommendRequestDTO("session", "home", 6, "similar:foreign", false), OnlinePreferenceSnapshot.empty()));
    }

    private static ItemEmbeddingText backpack(String id, String color, String category, int model) {
        return new ItemEmbeddingText(id, "Convertible Laptop Backpack", "CoolBELL Convertible Laptop Backpack 17.3 Inch Messenger Bag Shoulder Bag " + color,
                category, category, "brand-" + model, BigDecimal.TEN, Map.of("Item model number", "5602-" + model));
    }

    private static List<ItemEmbeddingText> explorationProducts() {
        var titles = List.of("Wireless Noise Cancelling Headphones", "Mechanical Gaming Keyboard", "Ceramic Coffee Mug",
                "Wooden Book Shelf", "Stainless Steel Cooking Pan", "Digital Alarm Clock", "USB Desk Fan", "Yoga Exercise Mat");
        return java.util.stream.IntStream.range(0, titles.size()).mapToObj(i -> new ItemEmbeddingText("explore-" + i,
                titles.get(i), titles.get(i), "category-" + i, "category-" + i, "brand-" + i, BigDecimal.TEN, Map.of())).toList();
    }

    @Test void trainedTwoTowerCandidatesParticipateInHomeRankingWithProvenance() {
        var pipeline = pipeline((id, query, candidates) -> candidates.stream().collect(
                java.util.stream.Collectors.toMap(ItemEmbeddingText::itemId, c -> c.itemId().equals("tower-item") ? 1.0 : .1)));
        pipeline.setTwoTowerRecallProvider((user, id, limit) -> List.of(
                new com.sinrotic.rs.recommend.domain.vo.PipelineCandidateVO("tower-item", "two_tower", .9, null, null, null)));
        var result = pipeline.select("two-tower", identity, request, OnlinePreferenceSnapshot.empty());
        assertEquals(1, result.sources().get("two_tower"));
        assertTrue(result.items().stream().anyMatch(c -> c.item().itemId().equals("tower-item")
                && c.reasonTags().contains("two_tower") && c.reasonTags().contains("bge_reranker")));
    }

    @Test void twoTowerOutageFallsBackButIsNotSilentlyReportedHealthy() {
        var pipeline = pipeline(model());
        pipeline.setPrimaryRecallShare(.65);
        pipeline.setTwoTowerRecallProvider((user, id, limit) -> { throw new IllegalStateException("runtime down"); });
        var result = pipeline.select("outage", identity, request, OnlinePreferenceSnapshot.empty());
        assertEquals(6, result.items().size());
        assertEquals(0, result.sources().get("two_tower"));
        assertTrue(result.degradationReasons().contains("two_tower_unavailable"));
    }

    @Test void collaborativeSourcesRetainOverlappingProvenanceAndRealCounts() {
        var pipeline = pipeline((id, query, candidates) -> candidates.stream().collect(
                java.util.stream.Collectors.toMap(ItemEmbeddingText::itemId, c -> c.itemId().equals("collaborative-item") ? 1.0 : .1)));
        pipeline.setMultiSourceRecallProvider((user, history, sources, limit) -> Map.of(
                "itemcf_weak", List.of(new com.sinrotic.rs.recommend.domain.vo.PipelineCandidateVO("collaborative-item", "itemcf_weak", .8, null, null, null)),
                "swing_recall", List.of(new com.sinrotic.rs.recommend.domain.vo.PipelineCandidateVO("collaborative-item", "swing_recall", .2, null, null, null)),
                "usercf_recall", List.of()));
        var result = pipeline.select("multi", identity, request, OnlinePreferenceSnapshot.empty());
        assertEquals(1, result.sources().get("itemcf_weak"));
        assertEquals(1, result.sources().get("swing_recall"));
        assertEquals(0, result.sources().get("usercf_recall"));
        assertTrue(result.items().stream().anyMatch(c -> c.item().itemId().equals("collaborative-item")
                && c.reasonTags().containsAll(List.of("itemcf_weak", "swing_recall", "bge_reranker"))));
    }

    @Test void multiRecallOutageDoesNotRemoveExistingHomeSources() {
        var pipeline = pipeline(model());
        pipeline.setMultiSourceRecallProvider((user, history, sources, limit) -> { throw new IllegalStateException("down"); });
        var result = pipeline.select("multi-down", identity, request, OnlinePreferenceSnapshot.empty());
        assertEquals(6, result.items().size());
        assertTrue(result.degradationReasons().contains("multi_recall_unavailable"));
    }

    @Test void sourcesBeyondCatalogBatchLimitAreHydratedAndRankBudgetIsBounded() {
        var boundedCatalog = new CatalogEmbeddingTextClient() {
            public List<ItemEmbeddingText> fetchActiveItemEmbeddingTexts(String cursor, int limit) { return office; }
            public List<ItemEmbeddingText> fetchItemEmbeddingTexts(List<String> ids) {
                assertTrue(ids.size() <= 100, "Catalog 的批次上限必须被调用方遵守");
                return ids.stream().map(id -> item(id, "Office")).toList();
            }
        };
        var pipeline = new PersonalizedHomeCandidatePipeline(boundedCatalog, (user, limit) -> List.of("seed"),
                (id, query, limit) -> audio, model(), deliveries, new PreferenceAwareFinalReranker());
        pipeline.setMultiSourceRecallProvider((user, history, sources, limit) -> {
            var result = new LinkedHashMap<String, List<com.sinrotic.rs.recommend.domain.vo.PipelineCandidateVO>>();
            for (String source : List.of("itemcf_weak", "swing_recall", "usercf_recall")) {
                result.put(source, java.util.stream.IntStream.range(0, 80).mapToObj(i ->
                        new com.sinrotic.rs.recommend.domain.vo.PipelineCandidateVO(source+i,source,.8,null,null,null)).toList());
            }
            return result;
        });
        var result = pipeline.select("many",identity,request,OnlinePreferenceSnapshot.empty());
        assertTrue(result.sources().get("usercf_recall") > 0);
        assertTrue(result.sources().get("swing_recall") > 0);
        assertTrue(result.stages().get("recall") <= 96);
    }

    @Test void primaryRecallReservesMajorityAndHydratesBeyondCatalogBatchLimit() {
        var batchSizes = new ArrayList<Integer>();
        var boundedCatalog = new CatalogEmbeddingTextClient() {
            public List<ItemEmbeddingText> fetchActiveItemEmbeddingTexts(String cursor, int limit) { return office; }
            public List<ItemEmbeddingText> fetchItemEmbeddingTexts(List<String> ids) {
                assertTrue(ids.size() <= 100); batchSizes.add(ids.size());
                return ids.stream().map(id -> item(id, "Office")).toList();
            }
        };
        var pipeline = new PersonalizedHomeCandidatePipeline(boundedCatalog, (user, limit) -> List.of("tower-0"),
                (id, query, limit) -> audio, model(), deliveries, new PreferenceAwareFinalReranker());
        pipeline.setPrimaryRecallShare(.65);
        pipeline.setTwoTowerRecallProvider((user, id, limit) -> {
            assertEquals(400, limit);
            return java.util.stream.IntStream.range(0, 400).mapToObj(i ->
                    new com.sinrotic.rs.recommend.domain.vo.PipelineCandidateVO("tower-"+i,"two_tower",.8,null,null,null)).toList();
        });
        pipeline.setTrainedRankingClient((user,ids,protectedIds,stage,coarse,fine)-> {
            assertFalse(ids.contains("tower-0"));
            assertTrue(ids.stream().filter(id -> id.startsWith("tower-")).count() >= 270);
            assertTrue(ids.size() <= 480);
            return new TrainedRankingClient.Result(ids.stream().map(id->new TrainedRankingClient.Item(id,.2,.3,.57)).toList(),ids.size(),ids.size(),ids.size());
        });
        var result = pipeline.select("primary", identity, request, OnlinePreferenceSnapshot.empty());
        assertTrue(result.sources().get("two_tower") >= 270);
        assertTrue(result.stages().get("primary_recall") >= 270);
        assertEquals(4, batchSizes.stream().filter(size -> size == 100).count());
        assertFalse(result.degradationReasons().contains("trained_ranking_unavailable"));
        assertEquals(6, result.items().size());
    }

    @Test void trainedRankingReportsRealStagesAndKeepsModelProvenance() {
        var pipeline=pipeline(model());
        pipeline.setTrainedRankingClient((user,ids,protectedIds,stage,coarse,fine)->new TrainedRankingClient.Result(
                ids.stream().map(id->new TrainedRankingClient.Item(id,.2,.3,.57)).toList(),ids.size(),ids.size(),ids.size()));
        var result=pipeline.select("trained",identity,request,OnlinePreferenceSnapshot.empty());
        assertEquals(result.stages().get("recall"),result.stages().get("cold_scored"));
        assertEquals(result.stages().get("coarse_rank"),result.stages().get("deepfm_scored"));
        assertTrue(result.items().stream().allMatch(c->c.reasonTags().containsAll(List.of("cold_coarse","deepfm_fine","bge_reranker"))));
    }

    @Test void trainedRankingFailureUsesBoundedFallbackWithoutFakeModelTags() {
        var pipeline=pipeline(model());
        pipeline.setTrainedRankingClient((user,ids,protectedIds,stage,coarse,fine)->{throw new IllegalStateException("down");});
        var result=pipeline.select("trained-down",identity,request,OnlinePreferenceSnapshot.empty());
        assertEquals(6,result.items().size());
        assertTrue(result.degradationReasons().contains("trained_ranking_unavailable"));
        assertEquals(0,result.stages().get("cold_scored"));
        assertTrue(result.items().stream().noneMatch(c->c.reasonTags().contains("deepfm_fine")));
    }
}
