package com.sinrotic.rs.searchrag.service.impl;

import com.sinrotic.rs.searchrag.domain.dto.RagPipelineRunRequestDTO;
import com.sinrotic.rs.searchrag.domain.vo.RagPipelineProviderStatusVO;
import com.sinrotic.rs.searchrag.domain.vo.RagPipelineRunVO;
import com.sinrotic.rs.searchrag.domain.vo.RagPipelineStageCountsVO;
import com.sinrotic.rs.searchrag.domain.vo.RagSupportSnippetVO;
import com.sinrotic.rs.searchrag.service.RagPipelineService;
import org.springframework.stereotype.Service;

import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;

/**
 * Minimal internal pipeline implementation until ES, Milvus, rerank, and small2big clients are wired.
 */
@Service
public class DefaultRagPipelineService implements RagPipelineService {

    @Override
    public RagPipelineRunVO run(RagPipelineRunRequestDTO request) {
        List<RagPipelineProviderStatusVO> providers = request.providers().stream()
                .map(provider -> new RagPipelineProviderStatusVO(provider, "READY", 0, 0))
                .toList();
        Map<String, Integer> sourceDistribution = request.providers().stream()
                .collect(Collectors.toMap(provider -> provider, provider -> 0));
        int supportCount = Math.min(request.candidateItemIds().size(), request.rerankTopK());
        List<RagSupportSnippetVO> support = request.candidateItemIds().stream()
                .limit(request.rerankTopK())
                .map(itemId -> new RagSupportSnippetVO(
                        "evidence",
                        "RAG pipeline placeholder support for item " + itemId + ".",
                        request.small2big()
                                ? "small2big parent profile compressed"
                                : "candidate-scoped evidence"
                ))
                .toList();
        return new RagPipelineRunVO(
                request.requestId(),
                "run",
                providers,
                sourceDistribution,
                new RagPipelineStageCountsVO(0, 0, supportCount, request.small2big() ? supportCount : 0, supportCount),
                support
        );
    }
}
