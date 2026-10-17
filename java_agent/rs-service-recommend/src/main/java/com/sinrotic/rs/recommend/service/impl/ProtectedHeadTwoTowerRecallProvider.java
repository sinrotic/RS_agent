package com.sinrotic.rs.recommend.service.impl;

import com.sinrotic.rs.recommend.domain.vo.PipelineCandidateVO;
import com.sinrotic.rs.recommend.service.TwoTowerRecallProvider;
import com.sinrotic.rs.recommend.service.UserHistoryClient;
import java.util.*;

/** 固定保留兼容模型头部，其余候选由主三塔提供；不混合不同空间的余弦得分。 */
public final class ProtectedHeadTwoTowerRecallProvider implements TwoTowerRecallProvider {
    private final TwoTowerRecallProvider primary;
    private final TwoTowerRecallProvider legacy;
    private final UserHistoryClient history;
    private final int headCount;

    public ProtectedHeadTwoTowerRecallProvider(TwoTowerRecallProvider primary, TwoTowerRecallProvider legacy,
            UserHistoryClient history, int headCount) {
        if (headCount < 1 || headCount > 50) throw new IllegalArgumentException("invalid protected head count");
        this.primary = Objects.requireNonNull(primary);
        this.legacy = Objects.requireNonNull(legacy);
        this.history = Objects.requireNonNull(history);
        this.headCount = headCount;
    }

    @Override public List<PipelineCandidateVO> recall(String userId, String requestId, int limit) {
        if (userId == null || userId.isBlank() || limit <= 0) return List.of();
        int budget = Math.min(500, limit);
        var seen = new HashSet<>(history.recentItemIds(userId, 80));
        var main = primary.recall(userId, requestId + "_primary", Math.min(500, budget + seen.size() + headCount));
        if (main.isEmpty()) return List.of();
        // 任一依赖失败由现有首页路线记录two_tower_unavailable并走其他召回。
        var old = legacy.recall(userId, requestId + "_protected", Math.min(500, headCount + seen.size()));
        var selected = new LinkedHashMap<String, PipelineCandidateVO>();
        for (var hit : old) {
            if (!seen.contains(hit.itemId())) selected.putIfAbsent(hit.itemId(), hit);
            if (selected.size() >= Math.min(headCount, budget)) break;
        }
        for (var hit : main) {
            if (selected.size() >= budget) break;
            if (!seen.contains(hit.itemId())) selected.putIfAbsent(hit.itemId(), hit);
        }
        return List.copyOf(selected.values());
    }
}
