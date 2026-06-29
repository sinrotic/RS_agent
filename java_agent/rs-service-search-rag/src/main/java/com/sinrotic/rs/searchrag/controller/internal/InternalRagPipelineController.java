package com.sinrotic.rs.searchrag.controller.internal;

import com.sinrotic.rs.searchrag.domain.dto.RagPipelineRunRequestDTO;
import com.sinrotic.rs.searchrag.domain.vo.RagPipelineRunVO;
import com.sinrotic.rs.searchrag.service.RagPipelineService;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * Exposes internal RAG pipeline stages for service-to-service callers and debugging.
 */
@RestController
@RequestMapping("/internal/rag/pipeline")
public class InternalRagPipelineController {

    private final RagPipelineService ragPipelineService;

    public InternalRagPipelineController(RagPipelineService ragPipelineService) {
        this.ragPipelineService = ragPipelineService;
    }

    @PostMapping("/run")
    public RagPipelineRunVO run(@RequestBody RagPipelineRunRequestDTO request) {
        return ragPipelineService.run(request.withDefaults());
    }
}
