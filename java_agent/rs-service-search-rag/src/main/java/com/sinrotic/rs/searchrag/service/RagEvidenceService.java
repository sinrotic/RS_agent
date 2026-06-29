package com.sinrotic.rs.searchrag.service;

import com.sinrotic.rs.searchrag.domain.dto.RagBatchEvidenceRequestDTO;
import com.sinrotic.rs.searchrag.domain.vo.RagEvidenceBatchVO;

/**
 * Internal item evidence lookup contract.
 */
public interface RagEvidenceService {

    RagEvidenceBatchVO batchEvidence(RagBatchEvidenceRequestDTO request);
}
