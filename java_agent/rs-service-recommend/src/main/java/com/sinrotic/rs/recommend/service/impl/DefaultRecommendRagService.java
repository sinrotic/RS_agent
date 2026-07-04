package com.sinrotic.rs.recommend.service.impl;

import com.sinrotic.rs.recommend.domain.dto.AgentRagSupportRequestDTO;
import com.sinrotic.rs.recommend.domain.dto.RagPipelineRunRequestDTO;
import com.sinrotic.rs.recommend.domain.vo.AgentRagSupportVO;
import com.sinrotic.rs.recommend.domain.vo.RagAgentContextVO;
import com.sinrotic.rs.recommend.domain.vo.RagGovernanceVO;
import com.sinrotic.rs.recommend.domain.vo.RagItemSupportVO;
import com.sinrotic.rs.recommend.domain.vo.RagPipelineRunVO;
import com.sinrotic.rs.recommend.domain.vo.RagSupportSnippetVO;
import com.sinrotic.rs.recommend.service.RagPipelineService;
import com.sinrotic.rs.recommend.service.RecommendRagService;
import org.springframework.stereotype.Service;

import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;

@Service
public class DefaultRecommendRagService implements RecommendRagService {

    private final RagPipelineService ragPipelineService;

    public DefaultRecommendRagService(RagPipelineService ragPipelineService) {
        this.ragPipelineService = ragPipelineService;
    }

    @Override
    public AgentRagSupportVO support(AgentRagSupportRequestDTO request) {
        AgentRagSupportRequestDTO normalized = request.withDefaults();
        RagPipelineRunVO pipeline = ragPipelineService.run(new RagPipelineRunRequestDTO(
                normalized.requestId(),
                normalized.sessionId(),
                normalized.userQuery(),
                normalized.candidateItemIds(),
                normalized.providers(),
                normalized.topK(),
                normalized.topK(),
                normalized.rerankTopK(),
                normalized.small2big()
        ));
        Map<String, List<RagSupportSnippetVO>> snippetsByItem = pipeline.support().stream()
                .filter(snippet -> snippet.itemId() != null && !snippet.itemId().isBlank())
                .collect(Collectors.groupingBy(RagSupportSnippetVO::itemId));
        List<RagItemSupportVO> itemSupport = normalized.candidateItemIds().stream()
                .filter(snippetsByItem::containsKey)
                .map(itemId -> new RagItemSupportVO(itemId, snippetsByItem.get(itemId).stream()
                        .limit(normalized.maxSupportPerItem())
                        .map(snippet -> new RagSupportSnippetVO(
                                snippet.field(),
                                truncate(snippet.summary(), normalized.maxTextChars()),
                                snippet.hint()
                        ))
                        .toList()))
                .toList();
        return new AgentRagSupportVO(
                normalized.requestId(),
                normalized.userQuery(),
                true,
                pipeline.providers().stream().map(provider -> provider.provider()).toList(),
                itemSupport,
                List.of(),
                new RagAgentContextVO("Use candidate-scoped RAG support when summarizing recommendations.", false),
                new RagGovernanceVO(false, false, false, false)
        );
    }

    private String truncate(String value, int maxChars) {
        if (value == null || value.length() <= maxChars) {
            return value == null ? "" : value;
        }
        return value.substring(0, Math.max(0, maxChars - 3)) + "...";
    }
}
