package com.sinrotic.rs.platformtrace.service.client;

import com.sinrotic.rs.platformtrace.domain.vo.AgentSessionTraceVO;
import com.sinrotic.rs.platformtrace.domain.vo.PlatformAccountProfileVO;
import com.sinrotic.rs.platformtrace.domain.vo.RecommendTraceVO;

import java.util.Optional;

public interface PlatformTraceDownstreamClient {

    Optional<PlatformAccountProfileVO> fetchAccountProfile(String accountId);

    Optional<RecommendTraceVO> fetchRecommendTrace(String requestId);

    Optional<AgentSessionTraceVO> fetchAgentSessionTrace(String sessionId);
}
