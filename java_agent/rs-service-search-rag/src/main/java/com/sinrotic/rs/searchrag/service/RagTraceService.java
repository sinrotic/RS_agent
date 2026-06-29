package com.sinrotic.rs.searchrag.service;

import com.sinrotic.rs.searchrag.domain.vo.RagHealthVO;
import com.sinrotic.rs.searchrag.domain.vo.RagTraceVO;

/**
 * Platform observation contract for RAG traces.
 */
public interface RagTraceService {

    RagTraceVO getTrace(String requestId);

    RagHealthVO health();
}
