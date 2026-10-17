package com.sinrotic.rs.user.domain.vo;

import java.time.Instant;

/** 会话活动期限由 User 的时区与时钟计算，调用方无需猜测本地时间的时区。 */
public record SessionActivityVO(String sessionId, String accountId, String profileUserId,
                                String status, Instant expiresAt) { }
