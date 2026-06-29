package com.sinrotic.rs.recommend.controller.platform;

import com.sinrotic.rs.recommend.domain.vo.RecommendTraceVO;
import com.sinrotic.rs.recommend.service.RecommendTraceService;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * Exposes recommendation trace details for platform observation and demos.
 */
@RestController
@RequestMapping("/api/platform/recommend")
public class PlatformRecommendTraceController {

    private final RecommendTraceService recommendTraceService;

    public PlatformRecommendTraceController(RecommendTraceService recommendTraceService) {
        this.recommendTraceService = recommendTraceService;
    }

    @GetMapping("/{requestId}/trace")
    public RecommendTraceVO getTrace(@PathVariable String requestId) {
        return recommendTraceService.getTrace(requestId);
    }
}
