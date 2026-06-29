package com.sinrotic.rs.model.service.impl;

import com.sinrotic.rs.model.domain.vo.ModelRequestTraceVO;
import com.sinrotic.rs.model.service.ModelTraceService;
import org.springframework.stereotype.Service;

@Service
public class MockModelTraceService implements ModelTraceService {

    @Override
    public ModelRequestTraceVO getTrace(String requestId) {
        String modelKey = requestId != null && requestId.startsWith("agent") ? "agent_4b" : "recommend_coarse_rank";
        String runtime = "agent_4b".equals(modelKey) ? "vllm" : "triton_onnx";
        return new ModelRequestTraceVO(
                requestId,
                modelKey,
                "v1",
                runtime,
                128,
                "SUCCESS",
                null
        );
    }
}
