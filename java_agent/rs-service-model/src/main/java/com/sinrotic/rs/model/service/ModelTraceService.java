package com.sinrotic.rs.model.service;

import com.sinrotic.rs.model.domain.vo.ModelRequestTraceVO;

public interface ModelTraceService {

    ModelRequestTraceVO getTrace(String requestId);
}
