package com.sinrotic.rs.model.service.impl;

import com.sinrotic.rs.model.domain.dto.*;
import com.sinrotic.rs.model.domain.vo.*;
import com.sinrotic.rs.model.service.ModelGatewayService;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Profile;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestClient;
import org.springframework.web.client.RestClientException;
import org.springframework.web.client.ResourceAccessException;
import org.springframework.web.server.ResponseStatusException;

import java.util.List;

/** Production calls use explicit runtime endpoints; absent capabilities never return synthetic inference. */
@Service
@Profile("!mock-models")
public class HttpModelGatewayService implements ModelGatewayService, com.sinrotic.rs.model.service.ModelTraceService {
    private static final org.slf4j.Logger LOGGER = org.slf4j.LoggerFactory.getLogger(HttpModelGatewayService.class);
    private final RestClient embeddingClient;
    private final RestClient rerankClient;
    private final java.util.Map<String, ModelRequestTraceVO> traces = new java.util.LinkedHashMap<>();

    public HttpModelGatewayService(RestClient.Builder builder,
            @Value("${rs.model.runtime.embedding-base-url:}") String embeddingBaseUrl,
            @Value("${rs.model.runtime.rerank-base-url:}") String rerankBaseUrl) {
        // 在服务生命周期内复用客户端和连接，避免每次推理重新创建 HTTP 客户端。
        this.embeddingClient = configuredClient(builder, embeddingBaseUrl);
        this.rerankClient = configuredClient(builder, rerankBaseUrl);
    }

    @Override
    public ModelEmbedVO embed(ModelEmbedRequestDTO request) {
        if (!"bge-m3".equals(request.modelKey()) && !"bge_m3_embedding".equals(request.modelKey())) throw unavailable();
        return post(embeddingClient, "/internal/model/embed", request.requestId(), request.modelKey(), request, ModelEmbedVO.class);
    }

    @Override
    public ModelRankVO rank(ModelRankRequestDTO request) {
        if (!"bge-reranker-v2-m3".equals(request.modelKey()) && !"bge_reranker".equals(request.modelKey())) throw unavailable();
        return post(rerankClient, "/internal/model/rank", request.requestId(), request.modelKey(), request, ModelRankVO.class);
    }

    private RestClient configuredClient(RestClient.Builder builder, String baseUrl) {
        return baseUrl == null || baseUrl.isBlank() ? null : builder.clone().baseUrl(baseUrl).build();
    }

    private <T> T post(RestClient client, String path, String requestId, String modelKey, Object request, Class<T> type) {
        if (client == null) throw unavailable();
        long started = System.nanoTime();
        try {
            T response;
            try {
                response = client.post().uri(path).body(request).retrieve().body(type);
            } catch (ResourceAccessException connectionFailure) {
                // embed/rank 是只读推理，连接中断允许按相同输入重试一次；HTTP 错误与解码错误不重试。
                LOGGER.warn("模型运行时连接失败，重试一次 request_id={} error_type={}", requestId,
                        connectionFailure.getMostSpecificCause().getClass().getSimpleName());
                response = client.post().uri(path).body(request).retrieve().body(type);
            }
            if (response == null) throw unavailable();
            recordTrace(requestId, modelKey, started, "SUCCESS", null);
            return response;
        } catch (RestClientException failure) {
            recordTrace(requestId, modelKey, started, "FAILED", "MODEL_RUNTIME_UNAVAILABLE");
            throw new ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE, "Model runtime is unavailable", failure);
        }
    }

    private synchronized void recordTrace(String requestId, String modelKey, long started, String status, String error) {
        if (requestId == null || requestId.isBlank()) return;
        traces.put(requestId, new ModelRequestTraceVO(requestId, modelKey, "runtime", "http",
                (System.nanoTime() - started) / 1_000_000, status, error));
        while (traces.size() > 1000) traces.remove(traces.keySet().iterator().next());
    }

    @Override
    public synchronized ModelRequestTraceVO getTrace(String requestId) {
        var trace = traces.get(requestId);
        if (trace == null) throw new ResponseStatusException(HttpStatus.NOT_FOUND, "Model trace not found");
        return trace;
    }

    @Override public ModelInferVO infer(ModelInferRequestDTO request) { throw unavailable(); }
    @Override public ModelRankSignalsVO rankSignals(ModelRankSignalsRequestDTO request) { throw unavailable(); }
    @Override public ModelChatVO chat(ModelChatRequestDTO request) { throw unavailable(); }
    @Override public List<ModelChatStreamEventVO> streamChat(ModelChatRequestDTO request) { throw unavailable(); }

    private ResponseStatusException unavailable() {
        return new ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE, "Requested model capability is not configured");
    }
}
