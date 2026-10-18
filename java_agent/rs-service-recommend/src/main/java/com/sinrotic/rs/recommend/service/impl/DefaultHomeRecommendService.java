package com.sinrotic.rs.recommend.service.impl;

import com.sinrotic.rs.recommend.domain.dto.HomeRecommendRequestDTO;
import com.sinrotic.rs.recommend.domain.delivery.RecommendationDeliveryItem;
import com.sinrotic.rs.recommend.domain.delivery.RecommendationIdentity;
import com.sinrotic.rs.recommend.domain.recall.ItemEmbeddingText;
import com.sinrotic.rs.recommend.domain.preference.OnlinePreferenceSnapshot;
import com.sinrotic.rs.recommend.domain.preference.PreferenceRankedCandidate;
import com.sinrotic.rs.recommend.domain.vo.HomeRecommendConfigVO;
import com.sinrotic.rs.recommend.domain.vo.HomeRecommendVO;
import com.sinrotic.rs.recommend.domain.vo.RecommendDisplayVO;
import com.sinrotic.rs.recommend.domain.vo.RecommendItemVO;
import com.sinrotic.rs.recommend.domain.vo.RecommendTraceItemVO;
import com.sinrotic.rs.recommend.domain.vo.RecommendTraceVO;
import com.sinrotic.rs.recommend.service.CatalogEmbeddingTextClient;
import com.sinrotic.rs.recommend.service.HomeRecommendService;
import com.sinrotic.rs.recommend.service.RecommendTraceService;
import com.sinrotic.rs.recommend.service.RecommendationDeliveryService;
import com.sinrotic.rs.recommend.service.OnlinePreferenceStore;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.UUID;

/**
 * Serves personalized Catalog-backed recommendations and records their delivery and trace.
 * Convenience constructors retain the legacy catalog pager for isolated compatibility tests.
 */
@Service
public class DefaultHomeRecommendService implements HomeRecommendService {
    private CommercePurchaseSignals purchases;
    @org.springframework.beans.factory.annotation.Autowired(required=false)
    public void setPurchases(CommercePurchaseSignals purchases) {this.purchases=purchases;}

    private static final HomeRecommendConfigVO HOME_CONFIG = new HomeRecommendConfigVO(500, 100, 50, 20, 8);

    private final RecommendTraceService recommendTraceService;
    private final CatalogEmbeddingTextClient catalogEmbeddingTextClient;
    private final RecommendationDeliveryService recommendationDeliveryService;
    private final OnlinePreferenceStore onlinePreferenceStore;
    private final PreferenceAwareFinalReranker preferenceReranker;
    private PersonalizedHomeCandidatePipeline personalizedPipeline;
    private HomeRecommendationMetrics homeMetrics;
    private SessionPreferenceReader sessionPreferenceReader;

    @Autowired
    public void setSessionPreferenceReader(SessionPreferenceReader reader) { this.sessionPreferenceReader = reader; }
    private final java.util.concurrent.locks.ReentrantLock[] profileLocks = java.util.stream.IntStream.range(0, 64)
            .mapToObj(i -> new java.util.concurrent.locks.ReentrantLock()).toArray(java.util.concurrent.locks.ReentrantLock[]::new);

    @Autowired
    public void setHomeMetrics(HomeRecommendationMetrics metrics) { this.homeMetrics = metrics; }

    @Autowired
    public void setPersonalizedPipeline(PersonalizedHomeCandidatePipeline pipeline) {
        this.personalizedPipeline = pipeline;
    }

    public DefaultHomeRecommendService(RecommendTraceService recommendTraceService) {
        this(recommendTraceService, (afterItemId, limit) -> List.of());
    }

    public DefaultHomeRecommendService(
            RecommendTraceService recommendTraceService,
            CatalogEmbeddingTextClient catalogEmbeddingTextClient
    ) {
        this(
                recommendTraceService,
                catalogEmbeddingTextClient,
                new DefaultRecommendationDeliveryService(
                        new InMemoryRecommendationDeliveryStore(),
                        java.time.Clock.systemUTC(),
                        java.time.Duration.ofHours(24)
                ),
                new InMemoryOnlinePreferenceStore(),
                new PreferenceAwareFinalReranker()
        );
    }

    @Autowired
    public DefaultHomeRecommendService(
            RecommendTraceService recommendTraceService,
            CatalogEmbeddingTextClient catalogEmbeddingTextClient,
            RecommendationDeliveryService recommendationDeliveryService,
            OnlinePreferenceStore onlinePreferenceStore,
            PreferenceAwareFinalReranker preferenceReranker
    ) {
        this.recommendTraceService = recommendTraceService;
        this.catalogEmbeddingTextClient = catalogEmbeddingTextClient;
        this.recommendationDeliveryService = recommendationDeliveryService;
        this.onlinePreferenceStore = onlinePreferenceStore;
        this.preferenceReranker = preferenceReranker;
    }

    @Override
    public HomeRecommendVO recommendHome(HomeRecommendRequestDTO request) {
        return recommend(
                new RecommendationIdentity(request.sessionId(), request.sessionId(), request.sessionId()),
                request, false
        );
    }

    @Override
    public HomeRecommendVO recommendHome(RecommendationIdentity identity, HomeRecommendRequestDTO request) {
        return recommend(identity,request,true);
    }

    private HomeRecommendVO recommend(RecommendationIdentity identity, HomeRecommendRequestDTO request, boolean ownedSession) {
        var lock = profileLocks[Math.floorMod(identity.profileUserId().hashCode(), profileLocks.length)];
        lock.lock();
        try {
            if (ownedSession && sessionPreferenceReader != null) sessionPreferenceReader.restore(identity);
            return recommendHomeExclusive(identity, request);
        }
        finally { lock.unlock(); }
    }

    private HomeRecommendVO recommendHomeExclusive(RecommendationIdentity identity, HomeRecommendRequestDTO request) {
        String requestId = "rec_req_" + UUID.randomUUID();
        OnlinePreferenceSnapshot preference = onlinePreferenceStore.load(identity);
        if (personalizedPipeline != null) return personalizedHome(requestId, identity, request, preference);
        List<ItemEmbeddingText> candidates = new ArrayList<>();
        List<PreferenceRankedCandidate> rankedCandidates = List.of();
        String scannedCursor = request.cursor() == null ? "" : request.cursor();
        boolean hasMore = false;
        // Fetch only the remaining display capacity, plus one unconsumed lookahead.
        // A bounded scan can return a short page with a continuation cursor.
        for (int batch = 0; batch < 10 && rankedCandidates.size() < request.pageSize(); batch++) {
            int remaining = request.pageSize() - rankedCandidates.size();
            var fetched = loadCatalogCandidates(scannedCursor, remaining + 1).stream()
                    .filter(item -> item.itemId() != null)
                    .sorted(java.util.Comparator.comparing(ItemEmbeddingText::itemId)).toList();
            String previousCursor = scannedCursor;
            fetched = fetched.stream().filter(item -> item.itemId().compareTo(previousCursor) > 0).toList();
            var consumed = fetched.stream().limit(remaining).toList();
            hasMore = fetched.size() > remaining;
            if (consumed.isEmpty()) break;
            candidates.addAll(consumed);
            scannedCursor = consumed.getLast().itemId();
            rankedCandidates = preferenceReranker.rerankWithPurchases(candidates, preference, request.pageSize(),java.util.Map.of(),
                    purchases==null ? java.util.Map.of() : purchases.load(identity.profileUserId(),candidates.stream().map(ItemEmbeddingText::itemId).toList()));
            if (!hasMore) break;
        }
        List<RecommendItemVO> items = toRecommendItems(rankedCandidates);
        String nextCursor = hasMore ? scannedCursor : "";
        HomeRecommendVO response = new HomeRecommendVO(
                requestId,
                request.sessionId(),
                request.scene(),
                identity.profileUserId(),
                items,
                hasMore,
                nextCursor,
                HOME_CONFIG,
                preference.version(),
                preference.appliedFeedbackEventIds()
        );
        recommendationDeliveryService.record(
                requestId, identity, request.scene(), preference.version(), toDeliveryItems(rankedCandidates));
        recommendTraceService.saveTrace(buildTrace(response));
        return response;
    }

    private HomeRecommendVO personalizedHome(String requestId, RecommendationIdentity identity,
            HomeRecommendRequestDTO request, OnlinePreferenceSnapshot preference) {
        long started = System.nanoTime();
        var selection = personalizedPipeline.select(requestId, identity, request, preference);
        var items = selection.items().stream().map(candidate -> {
            int rank = selection.items().indexOf(candidate) + 1;
            String reason = candidate.reasonTags().stream().anyMatch(tag -> tag.startsWith("feedback_")) ? "根据你最近喜欢的商品寻找相似选择"
                    : candidate.reasonTags().contains("two_tower") ? "根据你的历史行为推荐可能感兴趣的商品"
                    : candidate.reasonTags().stream().anyMatch(tag -> java.util.Set.of("itemcf_weak", "itemcf_strong", "swing_recall", "usercf_recall").contains(tag)) ? "根据相似兴趣和商品关联为你推荐"
                    : candidate.reasonTags().contains("category") ? "根据你常关注的类目推荐"
                    : candidate.reasonTags().contains("popular") ? "为你补充热门商品选择"
                    : candidate.reasonTags().stream().anyMatch(tag -> tag.startsWith("profile_")) ? "根据你的历史兴趣推荐"
                    : "为你探索其他品类的商品";
            return new RecommendItemVO(candidate.item().itemId(), rank, candidate.finalScore(), reason,
                    candidate.reasonTags(), new RecommendDisplayVO(candidate.item().title(), candidate.item().category(), "", "",candidate.item().price()));
        }).toList();
        String mode = selection.degradationReasons().isEmpty()
                ? (selection.sources().entrySet().stream().anyMatch(source -> source.getValue() > 0 && (source.getKey().startsWith("profile_") || source.getKey().startsWith("feedback_") || java.util.Set.of("two_tower", "itemcf_weak", "itemcf_strong", "swing_recall", "usercf_recall", "category").contains(source.getKey()))) ? "personalized" : "discovery")
                : "degraded";
        var config = new HomeRecommendConfigVO(selection.stages().get("recall"), selection.stages().get("coarse_rank"),
                selection.stages().get("fine_rank"), request.pageSize(), Math.min(8, request.pageSize()));
        var response = new HomeRecommendVO(requestId, request.sessionId(), request.scene(), identity.profileUserId(),
                items, selection.hasMore(), selection.hasMore() ? "feed:" + requestId : "", config,
                preference.version(), preference.appliedFeedbackEventIds(), mode, selection.degradationReasons());
        recommendationDeliveryService.record(requestId, identity, request.scene(), preference.version(), toDeliveryItems(selection.items()));
        recommendTraceService.saveTrace(new RecommendTraceVO(requestId, request.sessionId(), identity.profileUserId(), request.scene(),
                Map.of("recall_pool_size", config.recallPoolSize(), "fine_rank_size", config.fineRankSize(), "final_return_size", request.pageSize()),
                selection.stages(), selection.sources(), items.stream().map(item -> new RecommendTraceItemVO(item.itemId(), item.rank(),
                        item.score(), item.sourceTags(), 1, 1, item.reason())).toList()));
        if (homeMetrics != null) homeMetrics.record(mode, selection, System.nanoTime() - started);
        return response;
    }

    private List<RecommendationDeliveryItem> toDeliveryItems(List<PreferenceRankedCandidate> candidates) {
        List<RecommendationDeliveryItem> items = new ArrayList<>(candidates.size());
        for (int index = 0; index < candidates.size(); index++) {
            PreferenceRankedCandidate ranked = candidates.get(index);
            ItemEmbeddingText candidate = ranked.item();
            items.add(new RecommendationDeliveryItem(
                    candidate.itemId(),
                    index + 1,
                    ranked.finalScore(),
                    candidate.category(),
                    candidate.brand(),
                    candidate.attributes()
            ));
        }
        return List.copyOf(items);
    }

    private List<ItemEmbeddingText> loadCatalogCandidates(String cursor, int limit) {
        try {
            return catalogEmbeddingTextClient.fetchActiveItemEmbeddingTexts(cursor, limit);
        } catch (RuntimeException ignored) {
            return List.of();
        }
    }

    private List<RecommendItemVO> toRecommendItems(List<PreferenceRankedCandidate> candidates) {
        List<RecommendItemVO> items = new ArrayList<>(candidates.size());
        for (int index = 0; index < candidates.size(); index++) {
            PreferenceRankedCandidate ranked = candidates.get(index);
            ItemEmbeddingText candidate = ranked.item();
            List<String> tags = new ArrayList<>();
            tags.add("catalog_cold_start");
            tags.addAll(ranked.reasonTags());
            items.add(new RecommendItemVO(
                    candidate.itemId(),
                    index + 1,
                    ranked.finalScore(),
                    ranked.reasonTags().isEmpty()
                            ? "Catalog cold-start candidate"
                            : "Adjusted by your explicit preferences",
                    List.copyOf(tags),
                    new RecommendDisplayVO(candidate.title(), candidate.category(), "", "",candidate.price())
            ));
        }
        return List.copyOf(items);
    }

    private RecommendTraceVO buildTrace(HomeRecommendVO response) {
        return new RecommendTraceVO(
                response.requestId(),
                response.sessionId(),
                response.profileUserId(),
                response.scene(),
                Map.of(
                        "recall_pool_size", HOME_CONFIG.recallPoolSize(),
                        "coarse_rank_size", HOME_CONFIG.coarseRankSize(),
                        "fine_rank_size", HOME_CONFIG.fineRankSize(),
                        "final_return_size", HOME_CONFIG.finalReturnSize()
                ),
                Map.of(
                        "recall", response.items().size(),
                        "coarse_rank", response.items().size(),
                        "fine_rank", response.items().size(),
                        "final", response.items().size()
                ),
                Map.of("catalog_cold_start", response.items().size()),
                response.items().stream()
                        .map(item -> new RecommendTraceItemVO(
                                item.itemId(),
                                item.rank(),
                                item.score(),
                                item.sourceTags(),
                                1,
                                1,
                                item.reason()
                        ))
                        .toList()
        );
    }
}
