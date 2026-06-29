package com.sinrotic.rs.searchrag.service.impl;

import com.sinrotic.rs.searchrag.domain.dto.AgentRagSupportRequestDTO;
import com.sinrotic.rs.searchrag.domain.vo.AgentRagSupportVO;
import com.sinrotic.rs.searchrag.domain.vo.RagAgentContextVO;
import com.sinrotic.rs.searchrag.domain.vo.RagGovernanceVO;
import com.sinrotic.rs.searchrag.domain.vo.RagItemSupportVO;
import com.sinrotic.rs.searchrag.domain.vo.RagSupportSnippetVO;
import com.sinrotic.rs.searchrag.service.AgentRagService;
import org.springframework.stereotype.Service;

import java.util.List;

/**
 * Minimal Agent RAG pipeline implementation until ES, Milvus, rerank, and small2big clients are wired.
 */
@Service
public class DefaultAgentRagService implements AgentRagService {

    @Override
    public AgentRagSupportVO support(AgentRagSupportRequestDTO request) {
        List<RagItemSupportVO> itemSupport = request.candidateItemIds().stream()
                .limit(request.rerankTopK())
                .map(itemId -> new RagItemSupportVO(
                        itemId,
                        List.of(new RagSupportSnippetVO(
                                "evidence",
                                "RAG evidence pipeline is ready for Elasticsearch BM25 and Milvus vector support.",
                                request.small2big()
                                        ? "small2big parent profile compressed"
                                        : "candidate-scoped evidence"
                        ))
                ))
                .toList();
        return new AgentRagSupportVO(
                request.requestId(),
                request.userQuery(),
                true,
                request.providers(),
                itemSupport,
                List.of(),
                new RagAgentContextVO("Use candidate-scoped RAG support when summarizing recommendations.", false),
                new RagGovernanceVO(false, false, false, false)
        );
    }
}
