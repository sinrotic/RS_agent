package com.sinrotic.rs.model.service.impl;

import com.sinrotic.rs.model.domain.vo.ModelHealthVO;
import com.sinrotic.rs.model.domain.vo.ModelRuntimeHealthVO;
import com.sinrotic.rs.model.service.ModelHealthService;
import org.springframework.stereotype.Service;

import java.util.List;
import java.util.Map;

@Service
public class MockModelHealthService implements ModelHealthService {

    @Override
    public ModelHealthVO getHealth() {
        return new ModelHealthVO(
                "UP",
                Map.of("status", "UP", "model_count", 10, "enabled_model_count", 10),
                List.of(
                        Map.of("name", "embedding-service", "type", "embedding", "status", "UP"),
                        Map.of("name", "ranker-service", "type", "onnx/triton", "status", "UP"),
                        Map.of("name", "triton-rank", "type", "triton", "status", "UP"),
                        Map.of("name", "vllm-agent", "type", "vllm", "status", "UP")
                )
        );
    }

    @Override
    public ModelRuntimeHealthVO getModelHealth(String modelKey) {
        String runtime = runtimeFor(modelKey);
        String endpoint = endpointFor(modelKey);
        return new ModelRuntimeHealthVO(
                modelKey,
                "UP",
                runtime,
                endpoint,
                "2026-06-28T12:00:00+08:00",
                18
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
        if (modelKey.contains("cold")) {
            return "onnxruntime";
        }
        return "triton_onnx";
    }

    private String endpointFor(String modelKey) {
        if (modelKey == null) {
            return "mock://model-runtime";
        }
        if (modelKey.contains("qwen") || modelKey.contains("agent")) {
            return "http://vllm-agent:8000/v1/chat/completions";
        }
        if (modelKey.contains("bge") || modelKey.contains("two_tower")) {
            return "http://embedding-service:8000/" + modelKey;
        }
        if (modelKey.contains("deepfm") || modelKey.contains("cold")) {
            return "http://ranker-service:8000/" + modelKey;
        }
        return "http://triton-rank:8000/v2/models/" + modelKey + "/infer";
    }
}
