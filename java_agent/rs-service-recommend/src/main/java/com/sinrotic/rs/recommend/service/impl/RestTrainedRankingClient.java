package com.sinrotic.rs.recommend.service.impl;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.sinrotic.rs.recommend.service.TrainedRankingClient;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestClient;
import org.springframework.http.client.JdkClientHttpRequestFactory;
import org.springframework.http.MediaType;
import java.net.http.HttpClient;
import java.time.Duration;
import java.util.*;

@Component
@ConditionalOnProperty(name="rs.recommend.trained-ranking.enabled",havingValue="true")
public class RestTrainedRankingClient implements TrainedRankingClient {
    private final RestClient client;
    private final ObjectMapper mapper;
    private final String version;
    public RestTrainedRankingClient(RestClient.Builder builder,ObjectMapper mapper,
            @Value("${rs.recommend.trained-ranking.base-url:http://172.21.0.1:18119}") String url,
            @Value("${rs.recommend.trained-ranking.version:cold_deepfm_20260914}") String version) {
        this.mapper=mapper;this.version=version;
        var factory=new JdkClientHttpRequestFactory(HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(1)).build());
        factory.setReadTimeout(Duration.ofSeconds(2));
        client=builder.requestFactory(factory).baseUrl(url).build();
    }
    public Result rank(String user,List<String> itemIds,List<String> protectedIds,String stage,int coarseLimit,int fineLimit) {
        var ids=itemIds.stream().distinct().toList();
        if (ids.isEmpty()) return new Result(List.of(),0,0,0);
        if (ids.size()>500) throw new IllegalArgumentException("ranking budget exceeds 500");
        try {
            byte[] body=mapper.writeValueAsBytes(Map.of("profile_user_id",user,"candidate_item_ids",ids,
                "protected_item_ids",protectedIds,"stage",stage,"coarse_limit",coarseLimit,"fine_limit",fineLimit));
            var response=client.post().uri("/internal/ranking/cold-deepfm").contentType(MediaType.APPLICATION_JSON)
                    .contentLength(body.length).body(body).retrieve().body(Map.class);
            if (response==null || !version.equals(response.get("version")) || !stage.equals(response.get("stage"))
                    || !"cold_deepfm_training_features_v2".equals(response.get("feature_version"))
                    || !(response.get("items") instanceof List<?> rows)) throw new IllegalStateException("invalid ranking contract");
            int input=number(response.get("coarse_input_count")).intValue();
            int coarse=number(response.get("coarse_output_count")).intValue();
            int fine=number(response.get("fine_output_count")).intValue();
            int expectedCoarse=stage.equals("fine")?ids.size():Math.min(coarseLimit,ids.size());
            int expectedFine=stage.equals("coarse")?0:Math.min(fineLimit,expectedCoarse);
            if (input!=ids.size() || coarse!=expectedCoarse || fine!=expectedFine || rows.size()!=(stage.equals("coarse")?coarse:fine))
                throw new IllegalStateException("incomplete ranking stages");
            var result=new ArrayList<Item>();var seen=new HashSet<String>();
            for (Object value:rows) {
                if (!(value instanceof Map<?,?> row) || !(row.get("item_id") instanceof String id) || !ids.contains(id) || !seen.add(id))
                    throw new IllegalStateException("invalid ranked identity");
                double cold=number(row.get("cold_score")).doubleValue(), score=number(row.get("score")).doubleValue();
                Double logit=stage.equals("coarse")?null:number(row.get("deepfm_logit")).doubleValue();
                if (!Double.isFinite(cold) || !Double.isFinite(score) || score<0 || score>1 || (logit!=null && !Double.isFinite(logit)))
                    throw new IllegalStateException("invalid ranking score");
                result.add(new Item(id,cold,logit,score));
            }
            if (!seen.containsAll(protectedIds)) throw new IllegalStateException("lost protected candidates");
            return new Result(List.copyOf(result),input,coarse,fine);
        } catch (java.io.IOException error) {throw new IllegalStateException("cannot encode ranking request",error);}
    }
    private Number number(Object value) {
        if (!(value instanceof Number n)) throw new IllegalStateException("missing numeric ranking field");
        return n;
    }
}
