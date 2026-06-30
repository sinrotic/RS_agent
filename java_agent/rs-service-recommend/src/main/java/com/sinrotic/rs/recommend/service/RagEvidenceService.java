package com.sinrotic.rs.recommend.service;

import com.sinrotic.rs.recommend.domain.dto.RagBatchEvidenceRequestDTO;
import com.sinrotic.rs.recommend.domain.vo.RagEvidenceBatchVO;

public interface RagEvidenceService {

    RagEvidenceBatchVO batchEvidence(RagBatchEvidenceRequestDTO request);
}
