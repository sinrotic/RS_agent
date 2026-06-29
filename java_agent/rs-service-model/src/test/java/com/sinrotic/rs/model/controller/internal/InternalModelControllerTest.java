package com.sinrotic.rs.model.controller.internal;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.sinrotic.rs.model.controller.internal.InternalModelEmbeddingController;
import com.sinrotic.rs.model.controller.internal.InternalModelRankingController;
import com.sinrotic.rs.model.domain.vo.EmbeddingVectorVO;
import com.sinrotic.rs.model.domain.vo.ModelEmbedVO;
import com.sinrotic.rs.model.domain.vo.ModelChatVO;
import com.sinrotic.rs.model.domain.vo.ModelChatStreamEventVO;
import com.sinrotic.rs.model.domain.vo.ModelDefinitionVO;
import com.sinrotic.rs.model.domain.vo.ModelInferVO;
import com.sinrotic.rs.model.domain.vo.ModelMessageVO;
import com.sinrotic.rs.model.domain.vo.ModelRankSignalsVO;
import com.sinrotic.rs.model.domain.vo.ModelRankVO;
import com.sinrotic.rs.model.domain.vo.ModelRegistryVO;
import com.sinrotic.rs.model.domain.vo.ModelRuntimeHealthVO;
import com.sinrotic.rs.model.domain.vo.RankSignalVO;
import com.sinrotic.rs.model.domain.vo.RankedItemVO;
import com.sinrotic.rs.model.service.ModelGatewayService;
import com.sinrotic.rs.model.service.ModelHealthService;
import com.sinrotic.rs.model.service.ModelRegistryService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import java.util.List;
import java.util.Map;

import static org.mockito.ArgumentMatchers.argThat;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.asyncDispatch;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.content;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.request;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

class InternalModelControllerTest {

    private final ObjectMapper objectMapper = new ObjectMapper();

    private MockMvc mockMvc;

    private ModelRegistryService registryService;

    private ModelGatewayService gatewayService;

    private ModelHealthService healthService;

    @BeforeEach
    void setUp() {
        registryService = mock(ModelRegistryService.class);
        gatewayService = mock(ModelGatewayService.class);
        healthService = mock(ModelHealthService.class);
        mockMvc = MockMvcBuilders.standaloneSetup(
                new InternalModelRegistryController(registryService),
                new InternalModelInferenceController(gatewayService),
                new InternalModelEmbeddingController(gatewayService),
                new InternalModelRankingController(gatewayService),
                new InternalModelChatController(gatewayService),
                new InternalModelHealthController(healthService)
        ).build();
    }

    @Test
    void embedDelegatesTextBatchToGateway() throws Exception {
        when(gatewayService.embed(argThat(request ->
                "bge_m3_embedding".equals(request.modelKey())
                        && "emb_req_001".equals(request.requestId())
                        && request.inputs().containsKey("texts")
        ))).thenReturn(new ModelEmbedVO(
                "emb_req_001",
                "bge_m3_embedding",
                "v1",
                "embedding_service",
                24,
                List.of(new EmbeddingVectorVO("text_0", List.of(0.1, 0.2, 0.3), Map.of("source", "query"))),
                Map.of("dimension", 3, "count", 1)
        ));

        mockMvc.perform(post("/internal/model/embed")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(Map.of(
                                "model_key", "bge_m3_embedding",
                                "request_id", "emb_req_001",
                                "inputs", Map.of("texts", List.of("commuter backpack")),
                                "options", Map.of("normalize", true)
                        ))))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.request_id").value("emb_req_001"))
                .andExpect(jsonPath("$.model_key").value("bge_m3_embedding"))
                .andExpect(jsonPath("$.vectors[0].id").value("text_0"))
                .andExpect(jsonPath("$.vectors[0].vector[1]").value(0.2))
                .andExpect(jsonPath("$.usage.dimension").value(3));

        verify(gatewayService).embed(argThat(request ->
                "bge_m3_embedding".equals(request.modelKey())
                        && "emb_req_001".equals(request.requestId())
        ));
    }

    @Test
    void rankDelegatesCandidateBatchToGateway() throws Exception {
        when(gatewayService.rank(argThat(request ->
                "deepfm_ranker".equals(request.modelKey())
                        && "rank_req_001".equals(request.requestId())
                        && request.inputs().containsKey("candidates")
        ))).thenReturn(new ModelRankVO(
                "rank_req_001",
                "deepfm_ranker",
                "v1",
                "triton_onnx",
                31,
                List.of(
                        new RankedItemVO("B002", 0.94, 1, Map.of("stage", "fine")),
                        new RankedItemVO("B001", 0.81, 2, Map.of("stage", "fine"))
                ),
                Map.of("candidate_count", 2)
        ));

        mockMvc.perform(post("/internal/model/rank")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(Map.of(
                                "model_key", "deepfm_ranker",
                                "request_id", "rank_req_001",
                                "inputs", Map.of(
                                        "user_id", "U001",
                                        "candidates", List.of(Map.of("item_id", "B001"), Map.of("item_id", "B002"))
                                ),
                                "options", Map.of("top_k", 2)
                        ))))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.request_id").value("rank_req_001"))
                .andExpect(jsonPath("$.items[0].item_id").value("B002"))
                .andExpect(jsonPath("$.items[0].rank").value(1))
                .andExpect(jsonPath("$.diagnostics.candidate_count").value(2));

        verify(gatewayService).rank(argThat(request ->
                "deepfm_ranker".equals(request.modelKey())
                        && "rank_req_001".equals(request.requestId())
        ));
    }

    @Test
    void rankSignalsDelegatesAgentSignalRequestToGateway() throws Exception {
        when(gatewayService.rankSignals(argThat(request ->
                "qwen_rerank_signal".equals(request.modelKey())
                        && "sig_req_001".equals(request.requestId())
                        && request.inputs().containsKey("items")
        ))).thenReturn(new ModelRankSignalsVO(
                "sig_req_001",
                "qwen_rerank_signal",
                "v1",
                "vllm",
                220,
                List.of(new RankSignalVO("B001", 0.12, 0.88, "matches commute intent", List.of("intent_match"))),
                Map.of("llm_tokens", 42)
        ));

        mockMvc.perform(post("/internal/model/rank-signals")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(Map.of(
                                "model_key", "qwen_rerank_signal",
                                "request_id", "sig_req_001",
                                "inputs", Map.of(
                                        "query", "commuter backpack",
                                        "items", List.of(Map.of("item_id", "B001", "title", "City backpack"))
                                ),
                                "options", Map.of("max_tokens", 128)
                        ))))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.request_id").value("sig_req_001"))
                .andExpect(jsonPath("$.signals[0].item_id").value("B001"))
                .andExpect(jsonPath("$.signals[0].delta").value(0.12))
                .andExpect(jsonPath("$.signals[0].reason").value("matches commute intent"));

        verify(gatewayService).rankSignals(argThat(request ->
                "qwen_rerank_signal".equals(request.modelKey())
                        && "sig_req_001".equals(request.requestId())
        ));
    }

    @Test
    void registryReturnsInternalModelDefinitions() throws Exception {
        when(registryService.listModels()).thenReturn(new ModelRegistryVO(List.of(new ModelDefinitionVO(
                "recommend_coarse_rank",
                "ranking",
                "triton_onnx",
                "v1",
                "minio://rs-models/rank/coarse/v1/model.onnx",
                "http://triton-rank:8000/v2/models/coarse_rank/infer",
                80,
                500,
                "cpu",
                true
        ))));

        mockMvc.perform(get("/internal/model/registry"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.models[0].model_key").value("recommend_coarse_rank"))
                .andExpect(jsonPath("$.models[0].artifact_uri").value("minio://rs-models/rank/coarse/v1/model.onnx"))
                .andExpect(jsonPath("$.models[0].endpoint").value("http://triton-rank:8000/v2/models/coarse_rank/infer"));
    }

    @Test
    void inferDelegatesBatchRequestToGateway() throws Exception {
        when(gatewayService.infer(argThat(request ->
                "recommend_coarse_rank".equals(request.modelKey())
                        && "rec_req_001".equals(request.requestId())
                        && request.options().containsKey("top_k")
        ))).thenReturn(new ModelInferVO(
                "rec_req_001",
                "recommend_coarse_rank",
                "v1",
                "triton_onnx",
                37,
                Map.of("items", List.of(Map.of("item_id", "B001", "score", 0.913, "rank", 1)))
        ));

        mockMvc.perform(post("/internal/model/infer")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(Map.of(
                                "model_key", "recommend_coarse_rank",
                                "request_id", "rec_req_001",
                                "inputs", Map.of("candidate_item_ids", List.of("B001", "B002")),
                                "options", Map.of("top_k", 100, "return_scores", true)
                        ))))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.request_id").value("rec_req_001"))
                .andExpect(jsonPath("$.model_key").value("recommend_coarse_rank"))
                .andExpect(jsonPath("$.outputs.items[0].item_id").value("B001"))
                .andExpect(jsonPath("$.outputs.items[0].score").value(0.913));

        verify(gatewayService).infer(argThat(request ->
                "recommend_coarse_rank".equals(request.modelKey())
                        && "rec_req_001".equals(request.requestId())
        ));
    }

    @Test
    void chatDelegatesLlmRequestToGateway() throws Exception {
        when(gatewayService.chat(argThat(request ->
                "agent_4b".equals(request.modelKey())
                        && "agent_req_001".equals(request.requestId())
                        && request.messages().size() == 1
        ))).thenReturn(new ModelChatVO(
                "agent_req_001",
                "agent_4b",
                "v1",
                "vllm",
                1280,
                new ModelMessageVO("assistant", "I will prioritize affordable commuter backpacks."),
                Map.of("prompt_tokens", 18, "completion_tokens", 16, "total_tokens", 34)
        ));

        mockMvc.perform(post("/internal/model/chat")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(Map.of(
                                "model_key", "agent_4b",
                                "request_id", "agent_req_001",
                                "messages", List.of(Map.of("role", "user", "content", "Find a commuter backpack")),
                                "options", Map.of("temperature", 0.7, "max_tokens", 512)
                        ))))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.request_id").value("agent_req_001"))
                .andExpect(jsonPath("$.message.role").value("assistant"))
                .andExpect(jsonPath("$.usage.total_tokens").value(34));
    }

    @Test
    void streamChatReturnsSseTokenAndDoneEvents() throws Exception {
        when(gatewayService.streamChat(argThat(request ->
                "agent_4b".equals(request.modelKey())
                        && "agent_req_001".equals(request.requestId())
                        && request.messages().size() == 1
        ))).thenReturn(List.of(
                new ModelChatStreamEventVO("token", "agent_req_001", "I ", false),
                new ModelChatStreamEventVO("token", "agent_req_001", "will help.", false),
                new ModelChatStreamEventVO("done", "agent_req_001", "", true)
        ));

        var result = mockMvc.perform(post("/internal/model/chat/stream")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(Map.of(
                                "model_key", "agent_4b",
                                "request_id", "agent_req_001",
                                "messages", List.of(Map.of("role", "user", "content", "Find a commuter backpack"))
                        ))))
                .andExpect(request().asyncStarted())
                .andReturn();

        mockMvc.perform(asyncDispatch(result))
                .andExpect(status().isOk())
                .andExpect(content().contentTypeCompatibleWith(MediaType.TEXT_EVENT_STREAM))
                .andExpect(content().string(org.hamcrest.Matchers.containsString("event: token")))
                .andExpect(content().string(org.hamcrest.Matchers.containsString("\"delta\":\"I \"")))
                .andExpect(content().string(org.hamcrest.Matchers.containsString("event: done")))
                .andExpect(content().string(org.hamcrest.Matchers.containsString("\"done\":true")));

        verify(gatewayService).streamChat(argThat(request ->
                "agent_4b".equals(request.modelKey())
                        && "agent_req_001".equals(request.requestId())
        ));
    }

    @Test
    void modelHealthReturnsSingleModelStatus() throws Exception {
        when(healthService.getModelHealth("agent_4b")).thenReturn(new ModelRuntimeHealthVO(
                "agent_4b",
                "UP",
                "vllm",
                "http://vllm-agent:8000/v1/chat/completions",
                "2026-06-28T12:00:00+08:00",
                18
        ));

        mockMvc.perform(get("/internal/model/agent_4b/health"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.model_key").value("agent_4b"))
                .andExpect(jsonPath("$.status").value("UP"))
                .andExpect(jsonPath("$.endpoint").value("http://vllm-agent:8000/v1/chat/completions"));
    }
}
