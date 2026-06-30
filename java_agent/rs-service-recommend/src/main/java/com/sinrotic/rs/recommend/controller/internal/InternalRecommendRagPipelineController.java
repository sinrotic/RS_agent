package com.sinrotic.rs.recommend.controller.internal;

import com.sinrotic.rs.recommend.domain.dto.RagPipelineRunRequestDTO;
import com.sinrotic.rs.recommend.domain.vo.RagPipelineRunVO;
import com.sinrotic.rs.recommend.service.RagPipelineService;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * Exposes recommendation RAG pipeline stages for internal callers and debugging.
 */
@RestController
@RequestMapping("/internal/recommend/rag/pipeline")
public class InternalRecommendRagPipelineController {

    private final RagPipelineService ragPipelineService;

    public InternalRecommendRagPipelineController(RagPipelineService ragPipelineService) {
        this.ragPipelineService = ragPipelineService;
    }

    @PostMapping("/run")
    public RagPipelineRunVO run(@RequestBody RagPipelineRunRequestDTO request) {
        return ragPipelineService.run(request.withDefaults());
    }
}
