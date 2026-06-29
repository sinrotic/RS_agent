package com.sinrotic.rs.platformtrace.service.client;

import com.sinrotic.rs.platformtrace.domain.vo.AgentSessionTraceVO;
import com.sinrotic.rs.platformtrace.domain.vo.PlatformAccountProfileVO;
import com.sinrotic.rs.platformtrace.domain.vo.RecommendTraceVO;
import org.springframework.boot.autoconfigure.condition.ConditionalOnMissingBean;
import org.springframework.stereotype.Component;

import java.util.Optional;

@Component
@ConditionalOnMissingBean(PlatformTraceDownstreamClient.class)
public class NoopPlatformTraceDownstreamClient implements PlatformTraceDownstreamClient {

    @Override
    public Optional<PlatformAccountProfileVO> fetchAccountProfile(String accountId) {
        return Optional.empty();
    }

    @Override
    public Optional<RecommendTraceVO> fetchRecommendTrace(String requestId) {
        return Optional.empty();
    }

    @Override
    public Optional<AgentSessionTraceVO> fetchAgentSessionTrace(String sessionId) {
        return Optional.empty();
    }
}
