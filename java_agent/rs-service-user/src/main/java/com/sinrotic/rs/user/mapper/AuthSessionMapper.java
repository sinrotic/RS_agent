package com.sinrotic.rs.user.mapper;

import com.sinrotic.rs.user.domain.entity.AuthSessionCurrentAccountRecord;
import com.sinrotic.rs.user.domain.entity.AuthSessionRefreshRecord;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;

import java.time.LocalDateTime;

/**
 * MyBatis mapper for auth sessions and token records.
 */
@Mapper
public interface AuthSessionMapper {

    AuthSessionCurrentAccountRecord findCurrentAccountByAccessTokenHash(
            @Param("accessTokenHash") String accessTokenHash
    );

    AuthSessionRefreshRecord findRefreshSessionByRefreshTokenHash(
            @Param("refreshTokenHash") String refreshTokenHash
    );

    int insertSession(
            @Param("sessionId") String sessionId,
            @Param("accountId") String accountId,
            @Param("profileUserId") String profileUserId,
            @Param("accessTokenHash") String accessTokenHash,
            @Param("refreshTokenHash") String refreshTokenHash,
            @Param("accessExpiresAt") LocalDateTime accessExpiresAt,
            @Param("refreshExpiresAt") LocalDateTime refreshExpiresAt,
            @Param("userAgent") String userAgent,
            @Param("ip") String ip
    );

    int revokeSession(
            @Param("sessionId") String sessionId,
            @Param("reason") String reason
    );
}
