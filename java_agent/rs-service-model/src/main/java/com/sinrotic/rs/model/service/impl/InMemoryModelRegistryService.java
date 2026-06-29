package com.sinrotic.rs.model.service.impl;

import com.sinrotic.rs.model.domain.vo.ModelDefinitionVO;
import com.sinrotic.rs.model.domain.vo.ModelRegistryVO;
import com.sinrotic.rs.model.service.ModelRegistryService;
import org.springframework.stereotype.Service;

import java.util.List;

@Service
public class InMemoryModelRegistryService implements ModelRegistryService {

    private final List<ModelDefinitionVO> models = List.of(
            new ModelDefinitionVO(
                    "bge_m3_embedding",
                    "embedding",
                    "embedding_service",
                    "v1",
                    "minio://rs-models/embedding/bge-m3/v1/",
                    "http://embedding-service:8000/embed",
                    300,
                    32,
                    "gpu_or_cpu",
                    true
            ),
            new ModelDefinitionVO(
                    "two_tower_user_encoder",
                    "embedding",
                    "triton_onnx",
                    "v1",
                    "minio://rs-models/embedding/two_tower/user_encoder/v1/model.onnx",
                    "http://embedding-service:8000/two-tower/user/embed",
                    100,
                    128,
                    "gpu_or_cpu",
                    true
            ),
            new ModelDefinitionVO(
                    "deepfm_ranker",
                    "ranking",
                    "triton_onnx",
                    "v1",
                    "minio://rs-models/rank/deepfm/v1/model.onnx",
                    "http://ranker-service:8000/rank/deepfm",
                    150,
                    500,
                    "gpu_or_cpu",
                    true
            ),
            new ModelDefinitionVO(
                    "cold_coarse_ranker",
                    "ranking",
                    "onnxruntime",
                    "v1",
                    "minio://rs-models/rank/cold_coarse/v1/model.onnx",
                    "http://ranker-service:8000/rank/cold-coarse",
                    50,
                    1000,
                    "cpu",
                    true
            ),
            new ModelDefinitionVO(
                    "qwen_agent_chat",
                    "llm",
                    "vllm",
                    "v1",
                    "minio://rs-models/llm/qwen-agent/v1/",
                    "http://vllm-agent:8000/v1/chat/completions",
                    30000,
                    null,
                    "gpu",
                    true
            ),
            new ModelDefinitionVO(
                    "qwen_rerank_signal",
                    "rank_signal",
                    "vllm",
                    "v1",
                    "minio://rs-models/llm/qwen-rerank-signal/v1/",
                    "http://vllm-agent:8000/v1/chat/completions",
                    5000,
                    null,
                    "gpu",
                    true
            ),
            new ModelDefinitionVO(
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
            ),
            new ModelDefinitionVO(
                    "recommend_fine_rank",
                    "ranking",
                    "triton_onnx",
                    "v1",
                    "minio://rs-models/rank/fine/v1/model.onnx",
                    "http://triton-rank:8000/v2/models/fine_rank/infer",
                    150,
                    100,
                    "cpu_or_gpu",
                    true
            ),
            new ModelDefinitionVO(
                    "recommend_user_encoder",
                    "embedding",
                    "triton_onnx",
                    "v1",
                    "minio://rs-models/embedding/user_encoder/v1/model.onnx",
                    "http://triton-rank:8000/v2/models/user_encoder/infer",
                    100,
                    64,
                    "cpu_or_gpu",
                    true
            ),
            new ModelDefinitionVO(
                    "agent_4b",
                    "llm",
                    "vllm",
                    "v1",
                    "minio://rs-models/llm/agent-4b/v1/",
                    "http://vllm-agent:8000/v1/chat/completions",
                    30000,
                    null,
                    "gpu",
                    true
            )
    );

    @Override
    public ModelRegistryVO listModels() {
        return new ModelRegistryVO(models);
    }

    @Override
    public ModelRegistryVO listPlatformModels() {
        return new ModelRegistryVO(models.stream()
                .map(ModelDefinitionVO::toPlatformView)
                .toList());
    }

    @Override
    public ModelDefinitionVO getModel(String modelKey) {
        return findModel(modelKey);
    }

    @Override
    public ModelDefinitionVO getPlatformModel(String modelKey) {
        return findModel(modelKey).toPlatformView();
    }

    private ModelDefinitionVO findModel(String modelKey) {
        return models.stream()
                .filter(model -> model.modelKey().equals(modelKey))
                .findFirst()
                .orElseThrow(() -> new IllegalArgumentException("Unknown model_key: " + modelKey));
    }
}
