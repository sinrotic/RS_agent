package com.sinrotic.rs.recommend.service.impl;

import com.sinrotic.rs.recommend.domain.dto.AgentRecommendCandidatesRequestDTO;
import com.sinrotic.rs.recommend.domain.dto.AgentRecommendToolRequestDTO;
import com.sinrotic.rs.recommend.domain.dto.HomeRecommendRequestDTO;
import com.sinrotic.rs.recommend.domain.vo.AgentRecommendCandidateItemVO;
import com.sinrotic.rs.recommend.domain.vo.AgentRecommendCandidatesVO;
import com.sinrotic.rs.recommend.domain.vo.HomeRecommendVO;
import com.sinrotic.rs.recommend.domain.vo.RecommendItemVO;
import com.sinrotic.rs.recommend.service.AgentRecommendService;
import com.sinrotic.rs.recommend.service.HomeRecommendService;
import org.springframework.stereotype.Service;

import java.math.BigDecimal;
import java.util.List;
import java.util.Map;

/**
 * Bridges agent candidate requests to the homepage recommendation pipeline.
 */
@Service
public class DefaultAgentRecommendService implements AgentRecommendService {

    private final HomeRecommendService homeRecommendService;

    public DefaultAgentRecommendService(HomeRecommendService homeRecommendService) {
        this.homeRecommendService = homeRecommendService;
    }

    @Override
    public AgentRecommendCandidatesVO candidates(AgentRecommendCandidatesRequestDTO request) {
        HomeRecommendVO homeResponse = homeRecommendService.recommendHome(new HomeRecommendRequestDTO(
                request.profileUserId(),
                request.scene(),
                request.limit(),
                "",
                true
        ).withDefaults());
        return new AgentRecommendCandidatesVO(
                homeResponse.requestId(),
                request.agentId(),
                request.taskId(),
                request.profileUserId(),
                filterCandidatesForAgent(toAgentCandidates(homeResponse.items()), request.constraints())
        );
    }

    @Override
    public AgentRecommendCandidatesVO semanticRecall(AgentRecommendToolRequestDTO request) {
        return runHomeBackedTool(request, request.returnCount());
    }

    @Override
    public AgentRecommendCandidatesVO profilePipeline(AgentRecommendToolRequestDTO request) {
        return runHomeBackedTool(request, request.returnCount());
    }

    @Override
    public AgentRecommendCandidatesVO coldFallback(AgentRecommendToolRequestDTO request) {
        return runHomeBackedTool(request, request.returnCount());
    }

    @Override
    public AgentRecommendCandidatesVO rerankCandidates(AgentRecommendToolRequestDTO request) {
        return runHomeBackedTool(request, request.returnCount());
    }

    private AgentRecommendCandidatesVO runHomeBackedTool(
            AgentRecommendToolRequestDTO request,
            int returnCount
    ) {
        HomeRecommendVO homeResponse = homeRecommendService.recommendHome(new HomeRecommendRequestDTO(
                firstNonBlank(request.sessionId(), request.profileUserId()),
                request.scene(),
                returnCount,
                "",
                true
        ).withDefaults());
        return new AgentRecommendCandidatesVO(
                homeResponse.requestId(),
                request.agentId(),
                request.taskId(),
                request.profileUserId(),
                filterCandidatesForAgent(toAgentCandidates(homeResponse.items()), request.constraints())
        );
    }

    public List<AgentRecommendCandidateItemVO> filterCandidatesForAgent(
            List<AgentRecommendCandidateItemVO> candidates,
            Map<String, Object> constraints
    ) {
        BigDecimal priceMin = decimalConstraint(constraints, "price_min", "min_price", "budget_min");
        BigDecimal priceMax = decimalConstraint(constraints, "price_max", "max_price", "budget_max", "budget");
        if (priceMin == null && priceMax == null) {
            return candidates;
        }
        return candidates.stream()
                .filter(candidate -> matchesPrice(candidate.price(), priceMin, priceMax))
                .toList();
    }

    private boolean matchesPrice(BigDecimal price, BigDecimal priceMin, BigDecimal priceMax) {
        if (price == null) {
            return true;
        }
        if (priceMin != null && price.compareTo(priceMin) < 0) {
            return false;
        }
        return priceMax == null || price.compareTo(priceMax) <= 0;
    }

    private BigDecimal decimalConstraint(Map<String, Object> constraints, String... keys) {
        if (constraints == null || constraints.isEmpty()) {
            return null;
        }
        for (String key : keys) {
            Object value = constraints.get(key);
            BigDecimal decimal = toDecimal(value);
            if (decimal != null) {
                return decimal;
            }
        }
        return null;
    }

    private BigDecimal toDecimal(Object value) {
        if (value instanceof Number number) {
            return new BigDecimal(number.toString());
        }
        if (value instanceof String text && !text.isBlank()) {
            try {
                return new BigDecimal(text.trim());
            } catch (NumberFormatException ignored) {
                return null;
            }
        }
        return null;
    }

    private List<AgentRecommendCandidateItemVO> toAgentCandidates(List<RecommendItemVO> items) {
        return items.stream()
                .map(item -> new AgentRecommendCandidateItemVO(
                        item.itemId(),
                        titleOf(item),
                        categoryOf(item),
                        null,
                        "",
                        valueOrEmpty(item.reason()),
                        valueOrEmpty(item.reason())
                ))
                .toList();
    }

    private String titleOf(RecommendItemVO item) {
        if (item.display() == null || item.display().title() == null || item.display().title().isBlank()) {
            return item.itemId();
        }
        return item.display().title();
    }

    private String categoryOf(RecommendItemVO item) {
        if (item.display() == null) {
            return "";
        }
        return valueOrEmpty(item.display().category());
    }

    private String valueOrEmpty(String value) {
        if (value == null) {
            return "";
        }
        return value;
    }

    private String firstNonBlank(String primary, String fallback) {
        if (primary != null && !primary.isBlank()) {
            return primary;
        }
        return fallback;
    }
}
