package com.sinrotic.rs.recommend.service.impl;

import com.sinrotic.rs.recommend.domain.vo.RecommendTraceVO;
import com.sinrotic.rs.recommend.service.RecommendTraceService;
import org.springframework.stereotype.Service;

import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

/**
 * In-memory trace store for the first recommendation service iteration.
 */
@Service
public class InMemoryRecommendTraceService implements RecommendTraceService {

    private final Map<String, RecommendTraceVO> traces = new ConcurrentHashMap<>();

    @Override
    public void saveTrace(RecommendTraceVO trace) {
        if (trace != null && trace.requestId() != null && !trace.requestId().isBlank()) {
            traces.put(trace.requestId(), trace);
        }
    }

    @Override
    public RecommendTraceVO getTrace(String requestId) {
        return traces.get(requestId);
    }
}
