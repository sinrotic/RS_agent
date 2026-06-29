package com.sinrotic.rs.recommend.service;

import com.sinrotic.rs.recommend.domain.vo.RecommendTraceVO;

/**
 * Stores and retrieves recommendation traces by request id.
 */
public interface RecommendTraceService {

    void saveTrace(RecommendTraceVO trace);

    RecommendTraceVO getTrace(String requestId);
}
