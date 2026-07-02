package com.sinrotic.rs.platformtrace.controller.platform;

import com.sinrotic.rs.platformtrace.domain.vo.AgentRunMonitorVO;
import com.sinrotic.rs.platformtrace.domain.vo.PlatformSessionOverviewVO;
import com.sinrotic.rs.platformtrace.domain.vo.PlatformTimelineEventVO;
import com.sinrotic.rs.platformtrace.service.PlatformTraceService;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

@RestController
@RequestMapping("/api/platform/sessions")
public class PlatformSessionTraceController {

    private final PlatformTraceService traceService;

    public PlatformSessionTraceController(PlatformTraceService traceService) {
        this.traceService = traceService;
    }

    @GetMapping("/{sessionId}/overview")
    public PlatformSessionOverviewVO sessionOverview(
            @PathVariable String sessionId,
            @RequestParam(name = "account_id", required = false) String accountId,
            @RequestParam(name = "request_id", required = false) String requestId
    ) {
        return traceService.sessionOverview(sessionId, accountId, requestId);
    }

    @GetMapping("/{sessionId}/timeline")
    public List<PlatformTimelineEventVO> sessionTimeline(@PathVariable String sessionId) {
        return traceService.sessionTimeline(sessionId);
    }

    @GetMapping("/{sessionId}/agent-monitor")
    public AgentRunMonitorVO sessionAgentMonitor(
            @PathVariable String sessionId,
            @RequestParam(name = "request_id", required = false) String requestId
    ) {
        return traceService.agentSessionMonitor(sessionId, requestId);
    }
}
