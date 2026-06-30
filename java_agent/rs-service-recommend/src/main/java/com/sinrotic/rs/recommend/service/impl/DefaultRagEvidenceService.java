package com.sinrotic.rs.recommend.service.impl;

import com.sinrotic.rs.recommend.domain.dto.RagBatchEvidenceRequestDTO;
import com.sinrotic.rs.recommend.domain.vo.RagEvidenceBatchVO;
import com.sinrotic.rs.recommend.domain.vo.RagEvidenceItemVO;
import com.sinrotic.rs.recommend.domain.vo.RagSupportSnippetVO;
import com.sinrotic.rs.recommend.service.RagEvidenceService;
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
                                "Recommendation RAG evidence placeholder for item " + itemId + ".",
                                request.includeParentProfile()
                                        ? "small2big parent profile compressed"
                                        : "candidate-scoped evidence"
                        ))
                ))
                .toList();
        return new RagEvidenceBatchVO(request.requestId(), items);
    }
}
