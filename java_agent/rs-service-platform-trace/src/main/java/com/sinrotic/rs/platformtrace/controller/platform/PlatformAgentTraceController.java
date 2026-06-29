package com.sinrotic.rs.platformtrace.controller.platform;

import com.sinrotic.rs.platformtrace.domain.vo.AgentSessionTraceVO;
import com.sinrotic.rs.platformtrace.domain.vo.AgentTraceEventsVO;
import com.sinrotic.rs.platformtrace.service.PlatformTraceService;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/platform/agent")
public class PlatformAgentTraceController {

    private final PlatformTraceService traceService;

    public PlatformAgentTraceController(PlatformTraceService traceService) {
        this.traceService = traceService;
    }

    @GetMapping("/{sessionId}/turns")
    public AgentSessionTraceVO agentSessionTurns(@PathVariable String sessionId) {
        return traceService.agentSessionTurns(sessionId);
    }

    @GetMapping("/requests/{requestId}/events")
    public AgentTraceEventsVO agentRequestEvents(@PathVariable String requestId) {
        return traceService.agentRequestEvents(requestId);
    }
}
