package com.sinrotic.rs.recommend.controller.internal;

import com.sinrotic.rs.recommend.domain.dto.RagBatchEvidenceRequestDTO;
import com.sinrotic.rs.recommend.domain.vo.RagEvidenceBatchVO;
import com.sinrotic.rs.recommend.service.RagEvidenceService;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * Exposes item-scoped recommendation RAG evidence for internal services.
 */
@RestController
@RequestMapping("/internal/recommend/rag")
public class InternalRecommendRagEvidenceController {

    private final RagEvidenceService ragEvidenceService;

    public InternalRecommendRagEvidenceController(RagEvidenceService ragEvidenceService) {
        this.ragEvidenceService = ragEvidenceService;
    }

    @PostMapping("/batch-evidence")
    public RagEvidenceBatchVO batchEvidence(@RequestBody RagBatchEvidenceRequestDTO request) {
        return ragEvidenceService.batchEvidence(request.withDefaults());
    }
}
