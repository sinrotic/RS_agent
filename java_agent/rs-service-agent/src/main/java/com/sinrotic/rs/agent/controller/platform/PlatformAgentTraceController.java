package com.sinrotic.rs.agent.controller.platform;

import com.sinrotic.rs.agent.controller.GatewayRoleGuard;
import com.sinrotic.rs.agent.domain.vo.AgentSessionTraceVO;
import com.sinrotic.rs.agent.service.AgentTraceService;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/platform/agent")
public class PlatformAgentTraceController {

    private final AgentTraceService traceService;

    public PlatformAgentTraceController(AgentTraceService traceService) {
        this.traceService = traceService;
    }

    @GetMapping("/{sessionId}/turns")
    public AgentSessionTraceVO sessionTurns(
            @RequestHeader("X-User-Roles") String roles,
            @PathVariable String sessionId
    ) {
        GatewayRoleGuard.requireAny(roles, "ADMIN", "OBSERVER");
        return traceService.platformSessionTrace(sessionId);
    }
}
