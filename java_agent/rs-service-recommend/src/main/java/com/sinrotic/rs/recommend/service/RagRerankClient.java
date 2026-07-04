package com.sinrotic.rs.recommend.service;

import com.sinrotic.rs.recommend.domain.rag.RagEvidenceHit;

import java.util.List;

public interface RagRerankClient {

    List<RagEvidenceHit> rerank(String modelKey, String requestId, String query, List<RagEvidenceHit> candidates, int limit);
}
