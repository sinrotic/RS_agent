package com.sinrotic.rs.recommend.service;

import com.sinrotic.rs.recommend.domain.vo.RagHealthVO;
import com.sinrotic.rs.recommend.domain.vo.RagTraceVO;

public interface RagTraceService {

    RagTraceVO getTrace(String requestId);

    RagHealthVO health();
}
