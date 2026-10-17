package com.sinrotic.rs.user.mapper;

import com.sinrotic.rs.user.domain.entity.UserSession;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;

/**
 * MyBatis mapper for user sessions.
 */
@Mapper
public interface UserSessionMapper {
    java.util.List<UserSession> findActiveSessions(@Param("afterSessionId") String afterSessionId,
            @Param("cutoff") java.time.LocalDateTime cutoff, @Param("limit") int limit);

    int touchSession(@Param("sessionId") String sessionId, @Param("accountId") String accountId,
            @Param("profileUserId") String profileUserId, @Param("now") java.time.LocalDateTime now,
            @Param("cutoff") java.time.LocalDateTime cutoff);

    int admitSession(@Param("sessionId") String sessionId, @Param("accountId") String accountId,
            @Param("profileUserId") String profileUserId, @Param("now") java.time.LocalDateTime now,
            @Param("cutoff") java.time.LocalDateTime cutoff, @Param("query") String query);

    int expireOwnedSession(@Param("sessionId") String sessionId, @Param("accountId") String accountId,
            @Param("profileUserId") String profileUserId, @Param("cutoff") java.time.LocalDateTime cutoff);

    int insert(UserSession session);

    UserSession findBySessionId(@Param("sessionId") String sessionId);

    java.util.List<UserSession> findByOwner(@Param("accountId") String accountId,
            @Param("profileUserId") String profileUserId, @Param("entryScene") String entryScene,
            @Param("limit") int limit);

    int endSession(
            @Param("sessionId") String sessionId,
            @Param("reason") String reason
    );
}
