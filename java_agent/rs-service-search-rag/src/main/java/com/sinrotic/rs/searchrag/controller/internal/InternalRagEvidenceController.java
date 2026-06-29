package com.sinrotic.rs.searchrag.controller.internal;

import com.sinrotic.rs.searchrag.domain.dto.RagBatchEvidenceRequestDTO;
import com.sinrotic.rs.searchrag.domain.vo.RagEvidenceBatchVO;
import com.sinrotic.rs.searchrag.service.RagEvidenceService;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * Exposes item-scoped RAG evidence for internal services.
 */
@RestController
@RequestMapping("/internal/rag")
public class InternalRagEvidenceController {

    private final RagEvidenceService ragEvidenceService;

    public InternalRagEvidenceController(RagEvidenceService ragEvidenceService) {
        this.ragEvidenceService = ragEvidenceService;
    }

    @PostMapping("/batch-evidence")
    public RagEvidenceBatchVO batchEvidence(@RequestBody RagBatchEvidenceRequestDTO request) {
        return ragEvidenceService.batchEvidence(request.withDefaults());
    }
}
