package com.sinrotic.rs.platformtrace.controller.internal;

import com.sinrotic.rs.platformtrace.domain.vo.AgentSessionTraceVO;
import com.sinrotic.rs.platformtrace.domain.vo.AgentTraceEventVO;
import com.sinrotic.rs.platformtrace.domain.vo.PlatformAccountProfileVO;
import com.sinrotic.rs.platformtrace.domain.vo.PlatformInteractionEventVO;
import com.sinrotic.rs.platformtrace.domain.vo.RecommendTraceVO;
import com.sinrotic.rs.platformtrace.service.PlatformTraceService;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/internal/platform-trace")
public class InternalTraceController {

    private final PlatformTraceService traceService;

    public InternalTraceController(PlatformTraceService traceService) {
        this.traceService = traceService;
    }

    @PostMapping("/accounts/profile")
    public PlatformAccountProfileVO saveAccountProfile(@RequestBody PlatformAccountProfileVO profile) {
        traceService.saveAccountProfile(profile);
        return traceService.accountProfile(profile.accountId());
    }

    @PostMapping("/recommend/trace")
    public RecommendTraceVO saveRecommendTrace(@RequestBody RecommendTraceVO trace) {
        traceService.saveRecommendTrace(trace);
        return traceService.recommendTrace(trace.requestId());
    }

    @PostMapping("/agent/turns")
    public AgentSessionTraceVO saveAgentSessionTrace(@RequestBody AgentSessionTraceVO trace) {
        traceService.saveAgentSessionTrace(trace);
        return traceService.agentSessionTurns(trace.sessionId());
    }

    @PostMapping("/agent/events")
    public AgentTraceEventVO saveAgentTraceEvent(@RequestBody AgentTraceEventVO event) {
        return traceService.saveAgentTraceEvent(event);
    }

    @PostMapping("/interactions/events")
    public PlatformInteractionEventVO saveInteractionEvent(@RequestBody PlatformInteractionEventVO event) {
        return traceService.saveInteractionEvent(event);
    }
}
