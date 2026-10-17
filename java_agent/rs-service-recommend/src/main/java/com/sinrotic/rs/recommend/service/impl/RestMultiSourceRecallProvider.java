package com.sinrotic.rs.recommend.service.impl;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.sinrotic.rs.recommend.domain.vo.PipelineCandidateVO;
import com.sinrotic.rs.recommend.service.MultiSourceRecallProvider;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestClient;
import org.springframework.http.client.JdkClientHttpRequestFactory;
import org.springframework.http.MediaType;
import java.net.http.HttpClient;
import java.time.Duration;
import java.util.*;

@Component
@ConditionalOnProperty(name="rs.recommend.multi-recall.enabled", havingValue="true")
public class RestMultiSourceRecallProvider implements MultiSourceRecallProvider {
    private final RestClient client;
    private final ObjectMapper mapper;
    private final String version;

    public RestMultiSourceRecallProvider(RestClient.Builder builder, ObjectMapper mapper,
            @Value("${rs.recommend.multi-recall.base-url:http://172.21.0.1:18118}") String url,
            @Value("${rs.recommend.multi-recall.version:multi_recall_20260913}") String version) {
        this.mapper = mapper;
        this.version = version;
        var factory = new JdkClientHttpRequestFactory(HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(1)).build());
        factory.setReadTimeout(Duration.ofSeconds(2));
        client = builder.requestFactory(factory).baseUrl(url).build();
    }

    public Map<String,List<PipelineCandidateVO>> recall(String user, List<String> history, List<String> sources, int limit) {
        var requested = sources.stream().filter(SOURCES::contains).distinct().toList();
        if (requested.isEmpty()) return Map.of();
        try {
            byte[] body = mapper.writeValueAsBytes(Map.of("profile_user_id",user,"history_item_ids",history.stream().distinct().limit(80).toList(),
                    "sources",requested,"limit",Math.max(1,Math.min(120,limit))));
            var response = client.post().uri("/internal/recall/multi").contentType(MediaType.APPLICATION_JSON)
                    .contentLength(body.length).body(body).retrieve().body(Map.class);
            if (response == null || !version.equals(response.get("version")) || !(response.get("sources") instanceof Map<?,?> raw))
                throw new IllegalStateException("invalid multi recall version/response");
            var result = new LinkedHashMap<String,List<PipelineCandidateVO>>();
            for (String source : requested) {
                if (!(raw.get(source) instanceof List<?> rows) || rows.size() > Math.max(1,Math.min(120,limit)))
                    throw new IllegalStateException("invalid source rows");
                var candidates = new ArrayList<PipelineCandidateVO>();
                for (Object value : rows) {
                    if (!(value instanceof Map<?,?> row) || !(row.get("item_id") instanceof String id) || id.isBlank()
                            || !(row.get("score") instanceof Number score) || !Double.isFinite(score.doubleValue()))
                        throw new IllegalStateException("invalid candidate");
                    candidates.add(new PipelineCandidateVO(id,source,score.doubleValue(),null,null,null));
                }
                result.put(source,List.copyOf(candidates));
            }
            return result;
        } catch (java.io.IOException error) { throw new IllegalStateException("cannot encode recall request",error); }
    }
}
