package com.sinrotic.rs.searchrag.controller.platform;

import com.sinrotic.rs.searchrag.domain.vo.RagHealthVO;
import com.sinrotic.rs.searchrag.domain.vo.RagTraceVO;
import com.sinrotic.rs.searchrag.service.RagTraceService;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * Exposes RAG trace and provider readiness for platform observation.
 */
@RestController
@RequestMapping("/api/platform/rag")
public class PlatformRagTraceController {

    private final RagTraceService ragTraceService;

    public PlatformRagTraceController(RagTraceService ragTraceService) {
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
