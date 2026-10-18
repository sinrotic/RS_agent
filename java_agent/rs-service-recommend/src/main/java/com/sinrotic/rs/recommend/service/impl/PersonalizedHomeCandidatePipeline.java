package com.sinrotic.rs.recommend.service.impl;

import com.sinrotic.rs.recommend.domain.delivery.RecommendationIdentity;
import com.sinrotic.rs.recommend.domain.dto.HomeRecommendRequestDTO;
import com.sinrotic.rs.recommend.domain.preference.OnlinePreferenceSnapshot;
import com.sinrotic.rs.recommend.domain.preference.PreferenceRankedCandidate;
import com.sinrotic.rs.recommend.service.*;
import java.util.*;
import java.time.Instant;
import java.time.Duration;
import com.sinrotic.rs.recommend.domain.recall.ItemEmbeddingText;
import com.sinrotic.rs.recommend.domain.preference.ItemPreference;
import org.springframework.stereotype.Service;
import org.springframework.web.server.ResponseStatusException;
import org.springframework.http.HttpStatus;

@Service
public class PersonalizedHomeCandidatePipeline {
    private CommercePurchaseSignals purchases;
    @org.springframework.beans.factory.annotation.Autowired(required=false)
    public void setPurchases(CommercePurchaseSignals purchases) {this.purchases=purchases;}
    private static final int RANK_LIMIT = 96;
    private final CatalogEmbeddingTextClient catalog;
    private final UserHistoryClient history;
    private final SemanticItemRecallProvider semantic;
    private final HomeModelRanker model;
    private final RecommendationDeliveryStore deliveries;
    private final PreferenceAwareFinalReranker preferences;
    private TwoTowerRecallProvider twoTower;
    private MultiSourceRecallProvider multiRecall;
    private TrainedRankingClient trainedRanking;
    private double primaryRecallShare;

    @org.springframework.beans.factory.annotation.Value("${rs.recommend.two-tower.primary-share:0}")
    public void setPrimaryRecallShare(double share) {
        if (!Double.isFinite(share) || share < 0 || share > .9) throw new IllegalArgumentException("invalid primary recall share");
        this.primaryRecallShare = share;
    }

    @org.springframework.beans.factory.annotation.Autowired(required = false)
    public void setTrainedRankingClient(TrainedRankingClient client) { this.trainedRanking = client; }

    @org.springframework.beans.factory.annotation.Autowired(required = false)
    public void setMultiSourceRecallProvider(MultiSourceRecallProvider provider) { this.multiRecall = provider; }

    @org.springframework.beans.factory.annotation.Autowired(required = false)
    public void setTwoTowerRecallProvider(TwoTowerRecallProvider provider) { this.twoTower = provider; }

    public PersonalizedHomeCandidatePipeline(CatalogEmbeddingTextClient catalog, UserHistoryClient history,
            SemanticItemRecallProvider semantic, HomeModelRanker model, RecommendationDeliveryStore deliveries,
            PreferenceAwareFinalReranker preferences) {
        this.catalog = catalog;
        this.history = history;
        this.semantic = semantic;
        this.model = model;
        this.deliveries = deliveries;
        this.preferences = preferences;
    }

    public Selection select(String requestId, RecommendationIdentity identity, HomeRecommendRequestDTO request,
            OnlinePreferenceSnapshot snapshot) {
        var degradation = new LinkedHashSet<String>();
        String cursor = request.cursor() == null ? "" : request.cursor();
        var allowedCurrent = new HashSet<String>();
        List<String> previousIds = List.of();
        if (cursor.startsWith("feed:") || cursor.startsWith("rerank:") || cursor.startsWith("similar:")) {
            var previous = deliveries.findByRequestId(cursor.substring(cursor.indexOf(':') + 1))
                    .orElseThrow(() -> new ResponseStatusException(HttpStatus.BAD_REQUEST, "推荐批次已失效，请重新加载"));
            if (!previous.identity().equals(identity) || previous.expiresAt().isBefore(Instant.now())) {
                throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "推荐批次不属于当前会话或已失效");
            }
            if (cursor.startsWith("rerank:")) previous.items().forEach(item -> allowedCurrent.add(item.itemId()));
            else previousIds = previous.items().stream().map(item -> item.itemId()).toList();
        }
        Set<String> excluded = new HashSet<>(deliveries.recentItemIds(identity.profileUserId(), Instant.now().minus(Duration.ofHours(24)), 2000));
        excluded.removeAll(allowedCurrent);
        var recentContentIds = new LinkedHashSet<>(previousIds);
        if (!excluded.isEmpty()) recentContentIds.addAll(deliveries.recentItemIds(identity.profileUserId(), Instant.now().minus(Duration.ofHours(24)), 36));
        recentContentIds.removeAll(allowedCurrent);
        List<ItemEmbeddingText> recentItems;
        try { recentItems = recentContentIds.isEmpty() ? List.of() : catalog.fetchItemEmbeddingTexts(recentContentIds.stream().toList()); }
        catch (RuntimeException error) { recentItems = List.of(); degradation.add("previous_delivery_catalog_unavailable"); }
        final var previousItemIds = new HashSet<>(previousIds);
        var previousItems = recentItems.stream().filter(item -> previousItemIds.contains(item.itemId())).toList();
        List<String> historicalIds;
        try { historicalIds = history.recentItemIds(identity.profileUserId(), 20); }
        catch (RuntimeException error) { historicalIds = List.of(); degradation.add("profile_history_unavailable"); }
        excluded.addAll(historicalIds);
        var likes = snapshot.itemPreferences().values().stream().filter(p -> "like".equals(p.eventType()))
                .sorted(Comparator.comparingLong(ItemPreference::version).reversed()).limit(2).toList();
        // Explicit, recent intent takes precedence over weak historical preferences.
        List<String> seedIds = likes.isEmpty() ? historicalIds.stream()
                .filter(id -> !snapshot.itemPreferences().containsKey(id) || !"dislike".equals(snapshot.itemPreferences().get(id).eventType()))
                .limit(3).toList() : likes.stream().map(ItemPreference::itemId).toList();
        List<ItemEmbeddingText> seeds;
        try { seeds = catalog.fetchItemEmbeddingTexts(seedIds); }
        catch (RuntimeException error) { seeds = List.of(); degradation.add("profile_catalog_unavailable"); }
        Map<String, ItemEmbeddingText> seedMap = new HashMap<>();
        seeds.forEach(item -> seedMap.put(item.itemId(), item));
        List<String> queries = new ArrayList<>();
        for (String id : seedIds) {
            var seed = seedMap.get(id);
            if (seed != null) queries.add(query(seed));
        }
        if (queries.isEmpty() && !likes.isEmpty()) {
            for (var like : likes) queries.add((Objects.toString(like.category(), "") + " " + Objects.toString(like.brand(), "")).trim());
        }
        queries = queries.stream().filter(q -> !q.isBlank()).distinct().limit(2).toList();
        // "Show different" can choose another known interest instead of scoring every batch against the first seed.
        String rankQuery = queries.isEmpty() ? "" : queries.getFirst();
        if (cursor.startsWith("feed:") && !previousItems.isEmpty()) {
            final var previousTitles = previousItems.stream().map(ItemEmbeddingText::title).toList();
            rankQuery = queries.stream().min(Comparator.comparingDouble(q -> previousTitles.stream()
                    .mapToDouble(title -> HomeFeedDiversity.similarity(q, title)).max().orElse(0))).orElse("");
        }
        var sourceById = new HashMap<String, String>();
        var twoTowerIds = new HashSet<String>();
        var multiSourceIds = new LinkedHashMap<String, Set<String>>();
        List<ItemEmbeddingText> popularFallback = List.of();
        List<ItemEmbeddingText> primaryCandidates = List.of();
        List<List<ItemEmbeddingText>> pools = new ArrayList<>();
        if (multiRecall != null) {
            try {
                // 找相似只扩展明确喜欢；普通首页使用正向历史，过滤明确不喜欢的种子。
                var behaviorSeeds = cursor.startsWith("similar:") ? seedIds : historicalIds.stream()
                        .filter(id -> !snapshot.itemPreferences().containsKey(id) || !"dislike".equals(snapshot.itemPreferences().get(id).eventType())).toList();
                var requestedSources = cursor.startsWith("similar:")
                        ? List.of("itemcf_weak", "itemcf_strong", "swing_recall") : MultiSourceRecallProvider.SOURCES;
                var hitsBySource = multiRecall.recall(identity.profileUserId(), behaviorSeeds, requestedSources, 80);
                var ids = hitsBySource.values().stream().flatMap(Collection::stream).map(hit -> hit.itemId()).distinct().toList();
                var byId = new HashMap<String, ItemEmbeddingText>();
                // Catalog 单次最多接受 100 个 ID，逐批回填，不能静默丢失后续召回源。
                for (int offset = 0; offset < ids.size(); offset += 100) {
                    catalog.fetchItemEmbeddingTexts(ids.subList(offset, Math.min(offset + 100, ids.size())))
                            .forEach(item -> byId.put(item.itemId(), item));
                }
                for (var entry : hitsBySource.entrySet()) {
                    String source = entry.getKey();
                    var ordered = entry.getValue().stream().map(hit -> byId.get(hit.itemId())).filter(Objects::nonNull).distinct().toList();
                    multiSourceIds.put(source, new HashSet<>(ordered.stream().map(ItemEmbeddingText::itemId).toList()));
                    ordered.forEach(item -> sourceById.putIfAbsent(item.itemId(), source));
                    if (source.equals("popular")) popularFallback = ordered;
                    else pools.add(ordered);
                }
            } catch (RuntimeException error) { degradation.add("multi_recall_unavailable"); }
        }
        if (twoTower != null && !cursor.startsWith("similar:")) {
            try {
                var hits = twoTower.recall(identity.profileUserId(), requestId + "_two_tower", primaryRecallShare > 0 ? 400 : 120);
                var recalled = new ArrayList<ItemEmbeddingText>();
                var recalledIds = hits.stream().map(hit -> hit.itemId()).distinct().toList();
                for (int offset = 0; offset < recalledIds.size(); offset += 100) {
                    recalled.addAll(catalog.fetchItemEmbeddingTexts(recalledIds.subList(offset, Math.min(offset + 100, recalledIds.size()))));
                }
                var byId = new HashMap<String, ItemEmbeddingText>();
                recalled.forEach(item -> byId.put(item.itemId(), item));
                var ordered = hits.stream().map(hit -> byId.get(hit.itemId())).filter(Objects::nonNull).distinct().toList();
                pools.add(ordered);
                primaryCandidates = ordered;
                ordered.forEach(item -> { sourceById.put(item.itemId(), "two_tower"); twoTowerIds.add(item.itemId()); });
            } catch (RuntimeException error) { degradation.add("two_tower_unavailable"); }
        }
        var categories = new LinkedHashSet<String>();
        for (String id : seedIds) if (seedMap.containsKey(id)) categories.add(seedMap.get(id).category());
        if (categories.isEmpty()) likes.forEach(like -> categories.add(like.category()));
        for (String category : categories.stream().filter(c -> c != null && !c.isBlank()).limit(2).toList()) {
            try {
                var recalled = catalog.categoryCandidates(category, identity.profileUserId() + ":" + requestId, 32);
                pools.add(recalled);
                recalled.forEach(item -> sourceById.put(item.itemId(), likes.isEmpty() ? "profile_category" : "feedback_category"));
            } catch (RuntimeException error) { degradation.add("category_recall_unavailable"); }
        }
        for (int i = 0; i < queries.size(); i++) {
            try {
                var recalled = semantic.recall(requestId + "_" + i, queries.get(i), 120);
                if (recalled.isEmpty()) degradation.add("semantic_recall_empty");
                pools.add(recalled);
                recalled.forEach(item -> sourceById.put(item.itemId(), likes.isEmpty() ? "profile_semantic" : "feedback_semantic"));
            } catch (RuntimeException error) { degradation.add("semantic_recall_unavailable"); }
        }
        List<ItemEmbeddingText> exploration;
        try {
            exploration = catalog.discover(identity.profileUserId() + ":" + requestId, 64);
        } catch (RuntimeException error) {
            exploration = List.of(); degradation.add("catalog_exploration_unavailable");
        }
        exploration.forEach(item -> sourceById.putIfAbsent(item.itemId(), "catalog_exploration"));
        var candidateMap = new LinkedHashMap<String, ItemEmbeddingText>();
        // Interleave query pools so one historical interest cannot consume the entire rank budget.
        int interestBudget = trainedRanking == null ? 72 : 416;
        int recallBudget = trainedRanking == null ? RANK_LIMIT : 480;
        int primaryBudget = (int) Math.floor(interestBudget * primaryRecallShare);
        for (var item : primaryCandidates) {
            if (candidateMap.size() >= primaryBudget) break;
            var feedback = snapshot.itemPreferences().get(item.itemId());
            if (feedback == null || !"dislike".equals(feedback.eventType())) add(candidateMap, item, excluded);
        }
        for (int index = 0; index < 120 && candidateMap.size() < interestBudget; index++) {
            for (var pool : pools) if (index < pool.size() && candidateMap.size() < interestBudget) add(candidateMap, pool.get(index), excluded);
        }
        // 热门只补行为/类目候选不足的缺口，避免挤占个性化与探索席位。
        for (var item : popularFallback) if (candidateMap.size() < interestBudget) add(candidateMap, item, excluded);
        for (var item : exploration) if (candidateMap.size() < recallBudget) add(candidateMap, item, excluded);
        if (!allowedCurrent.isEmpty()) {
            try {
                for (var item : catalog.fetchItemEmbeddingTexts(allowedCurrent.stream().toList())) {
                    add(candidateMap, item, excluded);
                    sourceById.putIfAbsent(item.itemId(), "current_delivery");
                }
            } catch (RuntimeException error) { degradation.add("current_delivery_unavailable"); }
        }
        if (candidateMap.isEmpty()) throw new ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE, "暂时没有可用的新候选商品，请稍后重试");
        var candidates = candidateMap.values().stream().toList();
        int recallCount = candidates.size();
        int primaryRecallCount = (int) candidates.stream().filter(item -> twoTowerIds.contains(item.itemId())).count();
        int coarseCount = 0;
        boolean trainedRanked = false;
        Map<String, Double> scores = new HashMap<>();
        boolean modelRanked = false;
        if (trainedRanking != null) {
            try {
                var protectedIds = new LinkedHashSet<String>();
                allowedCurrent.stream().filter(candidateMap::containsKey).limit(20).forEach(protectedIds::add);
                exploration.stream().map(ItemEmbeddingText::itemId).filter(candidateMap::containsKey).limit(32).forEach(protectedIds::add);
                // 六项统计特征不表达当前语义，保护少量语义候选和反馈保留项穿过压缩阶段。
                pools.stream().flatMap(Collection::stream).map(ItemEmbeddingText::itemId).distinct()
                        .filter(id -> sourceById.getOrDefault(id, "").contains("semantic") && candidateMap.containsKey(id))
                        .limit(16).forEach(protectedIds::add);
                var ranked = trainedRanking.rank(identity.profileUserId(), candidates.stream().map(ItemEmbeddingText::itemId).toList(),
                        List.copyOf(protectedIds), "chain", 200, 96);
                candidates = ranked.items().stream().map(item -> candidateMap.get(item.itemId())).toList();
                ranked.items().forEach(item -> scores.put(item.itemId(), item.score()));
                coarseCount = ranked.coarseCount();
                trainedRanked = true;
            } catch (RuntimeException error) {
                degradation.add("trained_ranking_unavailable");
                // 运行时故障恢复到有界 BGE 路由，不把 500 个候选直接交给旧排序。
                var fallback = new LinkedHashMap<String, ItemEmbeddingText>();
                candidates.stream().filter(item -> !"catalog_exploration".equals(sourceById.get(item.itemId())))
                        .limit(72).forEach(item -> fallback.put(item.itemId(), item));
                exploration.stream().filter(item -> candidateMap.containsKey(item.itemId())).limit(24)
                        .forEach(item -> fallback.putIfAbsent(item.itemId(), item));
                candidates = List.copyOf(fallback.values());
                scores.clear();
            }
        }
        if (!queries.isEmpty()) {
            try {
                var semanticScores = model.score(requestId, rankQuery, candidates);
                if (semanticScores.size() != candidates.size() || candidates.stream().anyMatch(item ->
                        !semanticScores.containsKey(item.itemId()) || !Double.isFinite(semanticScores.get(item.itemId())))) {
                    throw new IllegalStateException("incomplete model ranking");
                }
                for (var item : candidates) {
                    double semanticScore = semanticScores.get(item.itemId());
                    scores.put(item.itemId(), trainedRanked ? .3 * scores.get(item.itemId()) + .7 * semanticScore : semanticScore);
                }
                modelRanked = true;
            } catch (RuntimeException error) { if (!trainedRanked) scores.clear(); degradation.add("model_rank_unavailable"); }
        }
        if (!modelRanked && !trainedRanked) {
            for (int i = 0; i < candidates.size(); i++) scores.put(candidates.get(i).itemId(), .65 - i * .003);
        }
        int pageSize = Math.max(1, Math.min(20, request.pageSize()));
        var explorationIds = sourceById.entrySet().stream().filter(e -> "catalog_exploration".equals(e.getValue()))
                .map(Map.Entry::getKey).collect(java.util.stream.Collectors.toSet());
        var ranked = new HomeFeedDiversity().select(preferences.rerankWithPurchases(candidates, snapshot, candidates.size(), scores,
                        purchases==null ? Map.of() : purchases.load(identity.profileUserId(),candidates.stream().map(ItemEmbeddingText::itemId).toList())),
                explorationIds, recentItems, pageSize, cursor.startsWith("feed:"), cursor.startsWith("similar:"));
        if (ranked.isEmpty()) throw new ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE, "本轮候选与最近浏览商品过于相似，请稍后重试");
        boolean rankedByModel = modelRanked;
        boolean rankedByTrainedModels = trainedRanked;
        var result = ranked.stream().map(item -> {
            var tags = new ArrayList<>(item.reasonTags());
            tags.add(sourceById.getOrDefault(item.item().itemId(), "catalog_exploration"));
            if (twoTowerIds.contains(item.item().itemId()) && !tags.contains("two_tower")) tags.add("two_tower");
            multiSourceIds.forEach((source, ids) -> { if (ids.contains(item.item().itemId()) && !tags.contains(source)) tags.add(source); });
            if (rankedByModel) tags.add("bge_reranker");
            if (rankedByTrainedModels) { tags.add("cold_coarse"); tags.add("deepfm_fine"); }
            return new PreferenceRankedCandidate(item.item(), item.baseScore(), item.preferenceAdjustment(), item.finalScore(), List.copyOf(tags));
        }).toList();
        Map<String, Integer> sources = new TreeMap<>();
        candidates.forEach(item -> sources.merge(sourceById.get(item.itemId()), 1, Integer::sum));
        if (twoTower != null) sources.put("two_tower", (int) candidates.stream().filter(item -> twoTowerIds.contains(item.itemId())).count());
        var finalCandidates = candidates;
        multiSourceIds.forEach((source, ids) -> sources.put(source, (int) finalCandidates.stream().filter(item -> ids.contains(item.itemId())).count()));
        return new Selection(result, Map.of("recall", recallCount, "coarse_rank", coarseCount,
                "fine_rank", trainedRanked || modelRanked ? candidates.size() : 0, "final", result.size(),
                "cold_scored", trainedRanked ? recallCount : 0, "deepfm_scored", trainedRanked ? coarseCount : 0,
                "bge_reranked", modelRanked ? candidates.size() : 0,
                "primary_recall", primaryRecallCount), Map.copyOf(sources),
                List.copyOf(degradation), !result.isEmpty());
    }

    private void add(Map<String, ItemEmbeddingText> items, ItemEmbeddingText item, Set<String> excluded) {
        if (item.itemId() != null && !item.itemId().isBlank() && !excluded.contains(item.itemId())) items.putIfAbsent(item.itemId(), item);
    }
    private String query(ItemEmbeddingText item) {
        String text = Objects.toString(item.title(), "") + ". " + Objects.toString(item.categoryPath(), "");
        return text.substring(0, Math.min(500, text.length()));
    }

    public record Selection(List<PreferenceRankedCandidate> items, Map<String, Integer> stages,
            Map<String, Integer> sources, List<String> degradationReasons, boolean hasMore) { }
}
