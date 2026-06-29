package com.sinrotic.rs.model.service.impl;

import com.sinrotic.rs.model.domain.dto.ModelChatRequestDTO;
import com.sinrotic.rs.model.domain.dto.ModelEmbedRequestDTO;
import com.sinrotic.rs.model.domain.dto.ModelInferRequestDTO;
import com.sinrotic.rs.model.domain.dto.ModelRankRequestDTO;
import com.sinrotic.rs.model.domain.dto.ModelRankSignalsRequestDTO;
import com.sinrotic.rs.model.domain.vo.EmbeddingVectorVO;
import com.sinrotic.rs.model.domain.vo.ModelChatVO;
import com.sinrotic.rs.model.domain.vo.ModelChatStreamEventVO;
import com.sinrotic.rs.model.domain.vo.ModelEmbedVO;
import com.sinrotic.rs.model.domain.vo.ModelInferVO;
import com.sinrotic.rs.model.domain.vo.ModelMessageVO;
import com.sinrotic.rs.model.domain.vo.ModelRankSignalsVO;
import com.sinrotic.rs.model.domain.vo.ModelRankVO;
import com.sinrotic.rs.model.domain.vo.RankSignalVO;
import com.sinrotic.rs.model.domain.vo.RankedItemVO;
import com.sinrotic.rs.model.service.ModelGatewayService;
import org.springframework.stereotype.Service;

import java.util.List;
import java.util.Map;

@Service
public class MockModelGatewayService implements ModelGatewayService {

    @Override
    public ModelInferVO infer(ModelInferRequestDTO request) {
        String requestId = request.requestId() == null ? "model_req_mock" : request.requestId();
        return new ModelInferVO(
                requestId,
                request.modelKey(),
                "v1",
                runtimeFor(request.modelKey()),
                12,
                Map.of("items", List.of(Map.of("item_id", "B001", "score", 0.9, "rank", 1)))
        );
    }

    @Override
    public ModelEmbedVO embed(ModelEmbedRequestDTO request) {
        String requestId = request.requestId() == null ? "embed_req_mock" : request.requestId();
        return new ModelEmbedVO(
                requestId,
                request.modelKey(),
                "v1",
                runtimeFor(request.modelKey()),
                18,
                List.of(new EmbeddingVectorVO("text_0", List.of(0.11, 0.22, 0.33), Map.of("mock", true))),
                Map.of("dimension", 3, "count", 1)
        );
    }

    @Override
    public ModelRankVO rank(ModelRankRequestDTO request) {
        String requestId = request.requestId() == null ? "rank_req_mock" : request.requestId();
        return new ModelRankVO(
                requestId,
                request.modelKey(),
                "v1",
                runtimeFor(request.modelKey()),
                21,
                List.of(
                        new RankedItemVO("B001", 0.91, 1, Map.of("mock", true)),
                        new RankedItemVO("B002", 0.74, 2, Map.of("mock", true))
                ),
                Map.of("candidate_count", 2)
        );
    }

    @Override
    public ModelRankSignalsVO rankSignals(ModelRankSignalsRequestDTO request) {
        String requestId = request.requestId() == null ? "signal_req_mock" : request.requestId();
        return new ModelRankSignalsVO(
                requestId,
                request.modelKey(),
                "v1",
                runtimeFor(request.modelKey()),
                180,
                List.of(new RankSignalVO("B001", 0.08, 0.86, "mock intent signal", List.of("intent_match"))),
                Map.of("llm_tokens", 16)
        );
    }

    @Override
    public ModelChatVO chat(ModelChatRequestDTO request) {
        String requestId = request.requestId() == null ? "chat_req_mock" : request.requestId();
        return new ModelChatVO(
                requestId,
                request.modelKey(),
                "v1",
                "vllm",
                128,
                new ModelMessageVO("assistant", "This is a mock response from rs-service-model."),
                Map.of("prompt_tokens", 1, "completion_tokens", 1, "total_tokens", 2)
        );
    }

    @Override
    public List<ModelChatStreamEventVO> streamChat(ModelChatRequestDTO request) {
        String requestId = request.requestId() == null ? "chat_req_mock" : request.requestId();
        return List.of(
                new ModelChatStreamEventVO("token", requestId, "This ", false),
                new ModelChatStreamEventVO("token", requestId, "is ", false),
                new ModelChatStreamEventVO("token", requestId, "a mock streamed response.", false),
                new ModelChatStreamEventVO("done", requestId, "", true)
        );
    }

    private String runtimeFor(String modelKey) {
        if (modelKey == null) {
            return "mock";
        }
        if (modelKey.contains("qwen") || modelKey.contains("agent")) {
            return "vllm";
        }
        if (modelKey.contains("bge")) {
            return "embedding_service";
        }
        return "triton_onnx";
    }
}
