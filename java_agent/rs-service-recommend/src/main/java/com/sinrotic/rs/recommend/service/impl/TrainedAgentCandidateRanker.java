package com.sinrotic.rs.recommend.service.impl;

import com.sinrotic.rs.recommend.domain.dto.AgentRecommendToolRequestDTO;
import com.sinrotic.rs.recommend.domain.delivery.*;
import com.sinrotic.rs.recommend.domain.recall.ItemEmbeddingText;
import com.sinrotic.rs.recommend.domain.vo.*;
import com.sinrotic.rs.recommend.service.*;
import org.springframework.stereotype.Service;
import java.util.*;

/** Agent 候选的在线最终处理。训练模型可选，偏好、约束、交付与追踪始终执行。 */
@Service
public class TrainedAgentCandidateRanker {
    private final TrainedRankingClient ranking;
    private final HomeModelRanker relevance;
    private final CatalogEmbeddingTextClient catalog;
    private final OnlinePreferenceStore preferences;
    private final PreferenceAwareFinalReranker adjustment;
    private final RecommendationDeliveryService deliveries;
    private final RecommendTraceService traces;
    private SessionPreferenceReader sessionPreferences;
    @org.springframework.beans.factory.annotation.Autowired
    public void setSessionPreferenceReader(SessionPreferenceReader reader) { this.sessionPreferences = reader; }
    private RecommendationStageObservation observation = new RecommendationStageObservation(false);
    @org.springframework.beans.factory.annotation.Autowired
    public void setObservation(RecommendationStageObservation observation) { this.observation = observation; }
    public TrainedAgentCandidateRanker(@org.springframework.lang.Nullable TrainedRankingClient ranking,HomeModelRanker relevance,CatalogEmbeddingTextClient catalog,
            OnlinePreferenceStore preferences,PreferenceAwareFinalReranker adjustment,RecommendationDeliveryService deliveries,RecommendTraceService traces) {
        this.ranking=ranking;this.relevance=relevance;this.catalog=catalog;this.preferences=preferences;
        this.adjustment=adjustment;this.deliveries=deliveries;this.traces=traces;
    }

    public boolean trainedRankingEnabled() { return ranking != null; }

    public AgentRecommendCandidatesVO rerank(AgentRecommendToolRequestDTO request) {
        if (!trainedRankingEnabled()) throw new org.springframework.web.server.ResponseStatusException(
                org.springframework.http.HttpStatus.SERVICE_UNAVAILABLE,"训练排序未启用");
        var ids=request.candidateItemIds().stream().distinct().limit(500).toList();
        var items=new ArrayList<ItemEmbeddingText>();
        for (int offset=0;offset<ids.size();offset+=100)
            items.addAll(catalog.fetchItemEmbeddingTexts(ids.subList(offset,Math.min(offset+100,ids.size()))));
        return rank(request,items,"existing_candidates");
    }

    public AgentRecommendCandidatesVO rank(AgentRecommendToolRequestDTO request,List<ItemEmbeddingText> input,String source) {
        String requestId="rec_req_agent_rank_"+UUID.randomUUID();
        String session=request.sessionId()==null || request.sessionId().isBlank()?request.taskId():request.sessionId();
        var identity=new RecommendationIdentity(request.accountId(),request.profileUserId(),session);
        var budget=AgentRecommendationBudget.from(request.constraints());
        if (sessionPreferences==null) throw new IllegalStateException("Agent 会话偏好读取器未配置");
        sessionPreferences.restore(identity);
        var preference=preferences.load(identity);
        var unique=new LinkedHashMap<String,ItemEmbeddingText>();
        input.stream().filter(item->budget.matches(item.price())).forEach(item->unique.putIfAbsent(item.itemId(),item));
        var candidates=unique.values().stream().limit(500).toList();
        int recallCount=candidates.size(),coarseCount=0;boolean trained=false,bge=false;
        var scores=new HashMap<String,Double>();var fineRanks=new HashMap<String,Integer>();
        var tags=new ArrayList<String>();var degradation=new ArrayList<String>();
        tags.add(source);
        if (!candidates.isEmpty()) {
            if (trainedRankingEnabled()) try {
                var protectedIds=request.query().isBlank()?List.<String>of():candidates.stream().limit(16).map(ItemEmbeddingText::itemId).toList();
                var rankingIds=candidates.stream().map(ItemEmbeddingText::itemId).toList();
                var result=observation.measure("cold_deepfm", () -> ranking.rank(request.profileUserId(),rankingIds,protectedIds,"chain",200,96));
                candidates=result.items().stream().map(item->unique.get(item.itemId())).toList();
                result.items().forEach(item->scores.put(item.itemId(),item.score()));
                for (int i=0;i<result.items().size();i++) fineRanks.put(result.items().get(i).itemId(),i+1);
                coarseCount=result.coarseCount();trained=true;tags.addAll(List.of("cold_coarse","deepfm_fine"));
            } catch (RuntimeException error) {
                candidates=candidates.stream().limit(96).toList();degradation.add("trained_ranking_unavailable");
            }
            if (trainedRankingEnabled() && !request.query().isBlank()) {
                try {
                    var rankingCandidates=candidates;
                    var semantic=observation.measure("bge_rerank", () -> relevance.score(requestId,request.query(),rankingCandidates));
                    if (semantic.size()!=candidates.size() || candidates.stream().anyMatch(item->
                            !semantic.containsKey(item.itemId()) || !Double.isFinite(semantic.get(item.itemId()))))
                        throw new IllegalStateException("incomplete relevance scoring");
                    for (var item:candidates) scores.put(item.itemId(),trained?.3*scores.get(item.itemId())+.7*semantic.get(item.itemId()):semantic.get(item.itemId()));
                    bge=true;tags.add("bge_reranker");
                } catch (RuntimeException error) {degradation.add("model_rank_unavailable");}
            }
            if (!trained && !bge) for (int i=0;i<candidates.size();i++) scores.put(candidates.get(i).itemId(),.65-i*.003);
        }
        int limit=Math.max(1,Math.min(20,request.returnCount()));
        var adjusted=adjustment.rerank(candidates,preference,candidates.size(),scores);
        var selected=new HomeFeedDiversity().select(adjusted,Set.of(),List.of(),limit,false,true);
        var deliveryItems=new ArrayList<RecommendationDeliveryItem>();var traceItems=new ArrayList<RecommendTraceItemVO>();
        var result=new ArrayList<AgentRecommendCandidateItemVO>();
        for (var candidate:selected) {
            var item=candidate.item();int rank=result.size()+1;
            String reason=request.query().isBlank()?"根据你的偏好推荐":"结合你的需求与偏好推荐";
            deliveryItems.add(new RecommendationDeliveryItem(item.itemId(),rank,candidate.finalScore(),item.category(),item.brand(),item.attributes()));
            var itemTags=new ArrayList<>(tags);itemTags.addAll(candidate.reasonTags());
            traceItems.add(new RecommendTraceItemVO(item.itemId(),rank,candidate.finalScore(),itemTags,null,fineRanks.get(item.itemId()),reason));
            result.add(new AgentRecommendCandidateItemVO(item.itemId(),item.title(),item.categoryPath(),item.price(),"",item.embeddingText(),reason));
        }
        observation.measure("delivery_persist", () -> { deliveries.record(requestId,identity,request.scene(),preference.version(),deliveryItems); return null; });
        var trace = new RecommendTraceVO(requestId,session,request.profileUserId(),request.scene(),
                Map.of("ranking_degraded",degradation.isEmpty()?0:1),
                Map.of("recall",recallCount,"coarse_rank",coarseCount,"fine_rank",trained||bge?candidates.size():0,
                        "cold_scored",trained?recallCount:0,"deepfm_scored",trained?coarseCount:0,"bge_reranked",bge?candidates.size():0,"final",result.size()),
                Map.of(source,recallCount),traceItems);
        observation.measure("recommend_trace", () -> { traces.saveTrace(trace); return null; });
        return new AgentRecommendCandidatesVO(requestId,request.agentId(),request.taskId(),request.profileUserId(),List.copyOf(result),List.copyOf(degradation));
    }

}
