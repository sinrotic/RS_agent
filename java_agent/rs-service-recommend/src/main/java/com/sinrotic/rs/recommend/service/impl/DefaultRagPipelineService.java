package com.sinrotic.rs.recommend.service.impl;

import com.sinrotic.rs.recommend.domain.dto.RagPipelineRunRequestDTO;
import com.sinrotic.rs.recommend.domain.rag.RagEvidenceHit;
import com.sinrotic.rs.recommend.domain.vo.RagPipelineProviderStatusVO;
import com.sinrotic.rs.recommend.domain.vo.RagPipelineRunVO;
import com.sinrotic.rs.recommend.domain.vo.RagPipelineStageCountsVO;
import com.sinrotic.rs.recommend.domain.vo.RagSupportSnippetVO;
import com.sinrotic.rs.recommend.service.RagEvidenceRecallClient;
import com.sinrotic.rs.recommend.service.RagPipelineService;
import com.sinrotic.rs.recommend.service.RagRerankClient;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.stream.Collectors;

@Service
public class DefaultRagPipelineService implements RagPipelineService {

    private final List<RagEvidenceRecallClient> recallClients;
    private final RagRerankClient rerankClient;
    private final int rrfK;
    private final String rerankModelKey;

    public DefaultRagPipelineService(
            List<RagEvidenceRecallClient> recallClients,
            RagRerankClient rerankClient,
            @Value("${rs.recommend.rag.rrf-k:60}") int rrfK,
            @Value("${rs.recommend.rag.rerank-model-key:bge-reranker-v2-m3}") String rerankModelKey
    ) {
        this.recallClients = recallClients == null ? List.of() : List.copyOf(recallClients);
        this.rerankClient = rerankClient;
        this.rrfK = Math.max(1, rrfK);
        this.rerankModelKey = rerankModelKey;
    }

    @Override
    public RagPipelineRunVO run(RagPipelineRunRequestDTO request) {
        RagPipelineRunRequestDTO normalized = request.withDefaults();
        Set<String> requestedProviders = Set.copyOf(normalized.providers());
        Map<String, RagEvidenceRecallClient> clients = recallClients.stream()
                .collect(Collectors.toMap(RagEvidenceRecallClient::providerName, client -> client, (left, ignored) -> left));

        List<RagPipelineProviderStatusVO> providers = new ArrayList<>();
        List<RagEvidenceHit> rawHits = new ArrayList<>();
        for (String provider : normalized.providers()) {
            RagEvidenceRecallClient client = clients.get(provider);
            if (client == null) {
                providers.add(new RagPipelineProviderStatusVO(provider, "UNAVAILABLE", 0, 0));
                continue;
            }
            long start = System.nanoTime();
            try {
                List<RagEvidenceHit> hits = client.retrieve(normalized);
                rawHits.addAll(rankProviderHits(provider, hits));
                providers.add(new RagPipelineProviderStatusVO(provider, "READY", hits.size(), elapsedMillis(start)));
            } catch (RuntimeException ex) {
                providers.add(new RagPipelineProviderStatusVO(provider, "DOWN", 0, elapsedMillis(start)));
            }
        }

        Map<String, Integer> sourceDistribution = requestedProviders.stream()
                .collect(Collectors.toMap(provider -> provider, provider -> 0, (left, ignored) -> left, LinkedHashMap::new));
        for (RagEvidenceHit hit : rawHits) {
            sourceDistribution.computeIfPresent(hit.provider(), (ignored, count) -> count + 1);
        }

        List<RagEvidenceHit> merged = rrfMerge(rawHits).stream()
                .limit(normalized.mergedTopK())
                .toList();
        List<RagEvidenceHit> reranked = rerankEvidence(normalized, merged);
        if (reranked.isEmpty()) {
            reranked = merged.stream().limit(normalized.rerankTopK()).toList();
        }
        List<RagEvidenceHit> selected = reranked.stream()
                .limit(normalized.rerankTopK())
                .toList();
        List<RagEvidenceHit> expanded = normalized.small2big() ? expandSmallToBig(selected) : selected;
        int small2bigCount = countExpanded(selected, expanded);
        List<RagSupportSnippetVO> support = expanded.stream()
                .map(hit -> new RagSupportSnippetVO(
                        hit.itemId(),
                        hit.field(),
                        truncate(hit.text(), 1200),
                        supportHint(hit)
                ))
                .toList();
        return new RagPipelineRunVO(
                normalized.requestId(),
                "run",
                providers,
                sourceDistribution,
                new RagPipelineStageCountsVO(rawHits.size(), merged.size(), selected.size(), small2bigCount, support.size()),
                support
        );
    }

    private List<RagEvidenceHit> expandSmallToBig(List<RagEvidenceHit> hits) {
        return hits.stream()
                .map(this::expandSmallHit)
                .toList();
    }

    private RagEvidenceHit expandSmallHit(RagEvidenceHit hit) {
        String expandedText = expandedText(hit);
        if (expandedText.isBlank() || expandedText.equals(hit.text())) {
            return hit;
        }
        return new RagEvidenceHit(
                hit.provider(),
                hit.itemId(),
                expandedField(hit.field()),
                expandedText,
                hit.source(),
                hit.score(),
                hit.rank(),
                hit.metadata()
        );
    }

    private String expandedText(RagEvidenceHit hit) {
        String direct = firstMetadataText(
                hit,
                "full_text",
                "parent_text",
                "item_text",
                "catalog_text",
                "product_text",
                "product_description",
                "description"
        );
        if (!direct.isBlank()) {
            return direct;
        }
        return composeMetadataText(hit);
    }

    private String composeMetadataText(RagEvidenceHit hit) {
        List<String> parts = new ArrayList<>();
        appendPart(parts, "title", metadataText(hit, "title"));
        appendPart(parts, "brand", metadataText(hit, "brand"));
        appendPart(parts, "category", firstMetadataText(hit, "category_path", "categoryPath", "category"));
        appendPart(parts, "attributes", metadataText(hit, "attributes"));
        appendPart(parts, "summary", metadataText(hit, "summary"));
        appendPart(parts, "description", metadataText(hit, "description"));
        return String.join("\n", parts);
    }

    private void appendPart(List<String> parts, String label, String value) {
        if (!value.isBlank()) {
            parts.add(label + ": " + value);
        }
    }

    private String firstMetadataText(RagEvidenceHit hit, String... keys) {
        for (String key : keys) {
            String value = metadataText(hit, key);
            if (!value.isBlank()) {
                return value;
            }
        }
        return "";
    }

    private String metadataText(RagEvidenceHit hit, String key) {
        Object value = hit.metadata().get(key);
        return value == null ? "" : value.toString().trim();
    }

    private String expandedField(String field) {
        if (field == null || field.isBlank()) {
            return "evidence_full";
        }
        return field.endsWith("_full") ? field : field + "_full";
    }

    private int countExpanded(List<RagEvidenceHit> original, List<RagEvidenceHit> expanded) {
        int count = 0;
        int size = Math.min(original.size(), expanded.size());
        for (int i = 0; i < size; i++) {
            if (!original.get(i).text().equals(expanded.get(i).text())) {
                count++;
            }
        }
        return count;
    }

    private List<RagEvidenceHit> rerankEvidence(RagPipelineRunRequestDTO request, List<RagEvidenceHit> merged) {
        try {
            return rerankClient.rerank(
                    rerankModelKey,
                    request.requestId(),
                    request.query(),
                    merged,
                    request.rerankTopK()
            );
        } catch (RuntimeException ex) {
            return List.of();
        }
    }

    private List<RagEvidenceHit> rankProviderHits(String provider, List<RagEvidenceHit> hits) {
        List<RagEvidenceHit> ranked = new ArrayList<>();
        for (int i = 0; i < hits.size(); i++) {
            RagEvidenceHit hit = hits.get(i);
            int rank = hit.rank() > 0 ? hit.rank() : i + 1;
            ranked.add(new RagEvidenceHit(provider, hit.itemId(), hit.field(), hit.text(), hit.source(), hit.score(), rank, hit.metadata()));
        }
        return ranked;
    }

    private List<RagEvidenceHit> rrfMerge(List<RagEvidenceHit> hits) {
        Map<String, RagEvidenceHit> rows = new LinkedHashMap<>();
        Map<String, Double> scores = new LinkedHashMap<>();
        for (RagEvidenceHit hit : hits) {
            if (hit.itemId().isBlank() || hit.text().isBlank()) {
                continue;
            }
            rows.putIfAbsent(hit.key(), hit);
            scores.merge(hit.key(), 1.0d / (rrfK + hit.rank()), Double::sum);
        }
        return rows.entrySet().stream()
                .map(entry -> entry.getValue().withScore(scores.getOrDefault(entry.getKey(), 0.0d)))
                .sorted(Comparator
                        .comparingDouble(RagEvidenceHit::score).reversed()
                        .thenComparing(RagEvidenceHit::itemId)
                        .thenComparing(RagEvidenceHit::field)
                        .thenComparing(RagEvidenceHit::text))
                .toList();
    }

    private String supportHint(RagEvidenceHit hit) {
        String provider = hit.provider().isBlank() ? "rag" : hit.provider();
        String source = hit.source().isBlank() ? "candidate-scoped evidence" : hit.source();
        return "item " + hit.itemId() + " from " + provider + " / " + source;
    }

    private String truncate(String value, int maxChars) {
        if (value == null || value.length() <= maxChars) {
            return value == null ? "" : value;
        }
        return value.substring(0, Math.max(0, maxChars - 3)) + "...";
    }

    private long elapsedMillis(long startNanos) {
        return Math.max(0, (System.nanoTime() - startNanos) / 1_000_000);
    }
}
