package com.sinrotic.rs.recommend.service.impl;

import com.sinrotic.rs.recommend.domain.dto.AgentRagSupportRequestDTO;
import com.sinrotic.rs.recommend.domain.vo.AgentRagSupportVO;
import com.sinrotic.rs.recommend.domain.vo.RagAgentContextVO;
import com.sinrotic.rs.recommend.domain.vo.RagGovernanceVO;
import com.sinrotic.rs.recommend.domain.vo.RagItemSupportVO;
import com.sinrotic.rs.recommend.domain.vo.RagSupportSnippetVO;
import com.sinrotic.rs.recommend.service.RecommendRagService;
import org.springframework.stereotype.Service;

import java.util.List;

@Service
public class DefaultRecommendRagService implements RecommendRagService {

    @Override
    public AgentRagSupportVO support(AgentRagSupportRequestDTO request) {
        AgentRagSupportRequestDTO normalized = request.withDefaults();
        List<RagItemSupportVO> itemSupport = normalized.candidateItemIds().stream()
                .limit(normalized.rerankTopK())
                .map(itemId -> new RagItemSupportVO(
                        itemId,
                        List.of(new RagSupportSnippetVO(
                                "evidence",
                                "RAG evidence pipeline is ready for candidate-scoped Elasticsearch BM25 and Milvus vector support.",
                                normalized.small2big()
                                        ? "small2big parent profile compressed"
                                        : "candidate-scoped evidence"
                        ))
                ))
                .toList();
        return new AgentRagSupportVO(
                normalized.requestId(),
                normalized.userQuery(),
                true,
                normalized.providers(),
                itemSupport,
                List.of(),
                new RagAgentContextVO("Use candidate-scoped RAG support when summarizing recommendations.", false),
                new RagGovernanceVO(false, false, false, false)
        );
    }
}
