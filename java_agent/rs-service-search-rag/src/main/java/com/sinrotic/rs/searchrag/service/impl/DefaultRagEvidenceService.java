package com.sinrotic.rs.searchrag.service.impl;

import com.sinrotic.rs.searchrag.domain.dto.RagBatchEvidenceRequestDTO;
import com.sinrotic.rs.searchrag.domain.vo.RagEvidenceBatchVO;
import com.sinrotic.rs.searchrag.domain.vo.RagEvidenceItemVO;
import com.sinrotic.rs.searchrag.domain.vo.RagSupportSnippetVO;
import com.sinrotic.rs.searchrag.service.RagEvidenceService;
import org.springframework.stereotype.Service;

import java.util.List;

/**
 * Minimal item evidence implementation until ES and Milvus evidence readers are wired.
 */
@Service
public class DefaultRagEvidenceService implements RagEvidenceService {

    @Override
    public RagEvidenceBatchVO batchEvidence(RagBatchEvidenceRequestDTO request) {
        List<RagEvidenceItemVO> items = request.itemIds().stream()
                .map(itemId -> new RagEvidenceItemVO(
                        itemId,
                        List.of(new RagSupportSnippetVO(
                                "evidence",
                                "RAG evidence placeholder for item " + itemId + ".",
                                request.includeParentProfile()
                                        ? "small2big parent profile compressed"
                                        : "candidate-scoped evidence"
                        ))
                ))
                .toList();
        return new RagEvidenceBatchVO(request.requestId(), items);
    }
}
