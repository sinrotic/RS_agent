package com.sinrotic.rs.recommend.controller.platform;

import com.sinrotic.rs.recommend.domain.vo.RagHealthVO;
import com.sinrotic.rs.recommend.domain.vo.RagTraceVO;
import com.sinrotic.rs.recommend.service.RagTraceService;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * Exposes recommendation RAG trace and provider readiness for platform observation.
 */
@RestController
@RequestMapping("/api/platform/recommend/rag")
public class PlatformRecommendRagTraceController {

    private final RagTraceService ragTraceService;

    public PlatformRecommendRagTraceController(RagTraceService ragTraceService) {
        this.ragTraceService = ragTraceService;
    }

    @GetMapping("/{requestId}/trace")
    public RagTraceVO getTrace(@PathVariable String requestId) {
        return ragTraceService.getTrace(requestId);
    }

    @GetMapping("/health")
    public RagHealthVO health() {
        return ragTraceService.health();
    }
}
