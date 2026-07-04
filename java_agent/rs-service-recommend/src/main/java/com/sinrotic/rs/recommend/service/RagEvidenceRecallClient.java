package com.sinrotic.rs.recommend.service;

import com.sinrotic.rs.recommend.domain.dto.RagPipelineRunRequestDTO;
import com.sinrotic.rs.recommend.domain.rag.RagEvidenceHit;

import java.util.List;

public interface RagEvidenceRecallClient {

    String providerName();

    List<RagEvidenceHit> retrieve(RagPipelineRunRequestDTO request);
}
