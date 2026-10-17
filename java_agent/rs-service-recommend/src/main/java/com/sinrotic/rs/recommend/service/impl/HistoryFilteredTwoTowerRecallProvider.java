package com.sinrotic.rs.recommend.service.impl;

import com.sinrotic.rs.recommend.domain.vo.PipelineCandidateVO;
import com.sinrotic.rs.recommend.service.TwoTowerRecallProvider;
import com.sinrotic.rs.recommend.service.UserHistoryClient;
import java.util.*;

/** 单模型召回，保留历史排除和ID去重；没有兼容模型调用或保护位置。 */
public final class HistoryFilteredTwoTowerRecallProvider implements TwoTowerRecallProvider {
    private final TwoTowerRecallProvider primary;
    private final UserHistoryClient history;

    public HistoryFilteredTwoTowerRecallProvider(TwoTowerRecallProvider primary, UserHistoryClient history) {
        this.primary = Objects.requireNonNull(primary);
        this.history = Objects.requireNonNull(history);
    }

    @Override public List<PipelineCandidateVO> recall(String userId, String requestId, int limit) {
        if (userId == null || userId.isBlank() || limit <= 0) return List.of();
        int budget = Math.min(500,limit);
        var seen = new HashSet<>(history.recentItemIds(userId,80));
        var hits = primary.recall(userId,requestId,Math.min(500,budget+seen.size()));
        var selected = new LinkedHashMap<String,PipelineCandidateVO>();
        for (var hit : hits) {
            if (selected.size() >= budget) break;
            if (!seen.contains(hit.itemId())) selected.putIfAbsent(hit.itemId(),hit);
        }
        return List.copyOf(selected.values());
    }
}
