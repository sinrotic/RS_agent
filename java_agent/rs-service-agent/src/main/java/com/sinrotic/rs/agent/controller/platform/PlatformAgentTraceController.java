package com.sinrotic.rs.agent.controller.platform;

import com.sinrotic.rs.agent.domain.vo.AgentSessionTraceVO;
import com.sinrotic.rs.agent.service.AgentTraceService;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/platform/agent")
public class PlatformAgentTraceController {

    private final AgentTraceService traceService;

    public PlatformAgentTraceController(AgentTraceService traceService) {
        this.traceService = traceService;
    }

    @GetMapping("/{sessionId}/turns")
    public AgentSessionTraceVO sessionTurns(@PathVariable String sessionId) {
        return traceService.platformSessionTrace(sessionId);
    }
}
