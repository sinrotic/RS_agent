package com.sinrotic.rs.recommend.service;

import com.sinrotic.rs.recommend.domain.preference.ActiveRecommendationSession;
import java.time.Instant;
import java.util.List;

/** 推荐交付和反馈写入前，向 Session 权威服务核验身份及活动状态。 */
public interface RecommendationSessionValidator {
    default List<ActiveRecommendationSession> activeSessions(
            String afterSessionId, int limit) {
        throw new UnsupportedOperationException("活跃会话必须由 User 服务提供");
    }
    default Instant activeUntil(String accountId, String profileUserId, String sessionId) {
        throw new UnsupportedOperationException("会话期限必须由 User 服务提供");
    }
    void requireActive(String accountId, String profileUserId, String sessionId);
}
