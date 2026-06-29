package com.sinrotic.rs.platformtrace.controller.platform;

import com.sinrotic.rs.platformtrace.domain.vo.RecommendTraceVO;
import com.sinrotic.rs.platformtrace.service.PlatformTraceService;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/platform/recommend")
public class PlatformRecommendTraceController {

    private final PlatformTraceService traceService;

    public PlatformRecommendTraceController(PlatformTraceService traceService) {
        this.traceService = traceService;
    }

    @GetMapping("/{requestId}/trace")
    public RecommendTraceVO recommendTrace(@PathVariable String requestId) {
        return traceService.recommendTrace(requestId);
    }
}
