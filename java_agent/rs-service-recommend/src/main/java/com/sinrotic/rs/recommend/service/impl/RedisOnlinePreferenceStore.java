package com.sinrotic.rs.recommend.service.impl;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.sinrotic.rs.recommend.domain.delivery.RecommendationIdentity;
import com.sinrotic.rs.recommend.domain.feedback.RecommendationFeedbackEvent;
import com.sinrotic.rs.recommend.domain.preference.OnlinePreferenceSnapshot;
import com.sinrotic.rs.recommend.service.OnlinePreferenceStore;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.script.DefaultRedisScript;
import org.springframework.stereotype.Component;
import org.springframework.beans.factory.annotation.Autowired;

import java.time.Duration;
import java.time.Clock;
import java.time.Instant;
import java.util.List;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

@Component
@ConditionalOnProperty(name = "rs.recommend.feedback.projection", havingValue = "redis")
public class RedisOnlinePreferenceStore implements OnlinePreferenceStore {
    private static final Logger log = LoggerFactory.getLogger(RedisOnlinePreferenceStore.class);

    private static final DefaultRedisScript<Long> COMPARE_AND_SET = new DefaultRedisScript<>("""
            local current = redis.call('GET', KEYS[1]) or ''
            if current ~= ARGV[1] then return 0 end
            redis.call('SET', KEYS[1], ARGV[2], 'PX', ARGV[3])
            return 1
            """, Long.class);

    private final StringRedisTemplate redis;
    private final ObjectMapper objectMapper;
    private final Clock clock;

    @Autowired
    public RedisOnlinePreferenceStore(StringRedisTemplate redis, ObjectMapper objectMapper) {
        this(redis, objectMapper, Clock.systemUTC());
    }

    public RedisOnlinePreferenceStore(StringRedisTemplate redis, ObjectMapper objectMapper, Clock clock) {
        this.redis = redis;
        this.objectMapper = objectMapper;
        this.clock = clock;
    }

    @Override
    public synchronized OnlinePreferenceSnapshot apply(RecommendationFeedbackEvent event) {
        if (!event.eventType().preferenceChanging()) {
            return load(event.identity());
        }
        restoreSession(event, null, event.receivedAt().plus(PreferenceProjectionSupport.SESSION_TTL));
        restoreProfile(event, null);
        return load(event.identity());
    }

    @Override
    public OnlinePreferenceSnapshot load(RecommendationIdentity identity) {
        return PreferenceProjectionSupport.merge(loadProfile(identity.profileUserId()),
                PreferenceProjectionSupport.session(read(sessionKey(identity)),clock.instant()));
    }

    @Override
    public OnlinePreferenceSnapshot loadProfile(String profileUserId) {
        return PreferenceProjectionSupport.profile(read("rs:pref:v2:profile:" + profileUserId),clock.instant());
    }

    @Override
    public synchronized OnlinePreferenceSnapshot applyReversal(
            RecommendationFeedbackEvent reversal,
            RecommendationFeedbackEvent restoredPreferenceEvent
    ) {
        return applyReversal(reversal,restoredPreferenceEvent,
                restoredPreferenceEvent != null && restoredPreferenceEvent.identity().sessionId().equals(reversal.identity().sessionId())
                        ? restoredPreferenceEvent : null);
    }

    @Override
    public synchronized OnlinePreferenceSnapshot applyReversal(RecommendationFeedbackEvent reversal,
            RecommendationFeedbackEvent profileRestored, RecommendationFeedbackEvent sessionRestored) {
        restoreSession(reversal,sessionRestored,reversal.receivedAt().plus(PreferenceProjectionSupport.SESSION_TTL));
        restoreProfile(reversal,profileRestored);
        return load(reversal.identity());
    }

    @Override
    public synchronized void restoreProfile(RecommendationFeedbackEvent event, RecommendationFeedbackEvent restored) {
        update(profileKey(event.identity()),false,current -> PreferenceProjectionSupport.change(
                current,event,restored,"profile",null,clock.instant()));
    }

    @Override
    public synchronized void restoreSession(RecommendationFeedbackEvent event, RecommendationFeedbackEvent restored,Instant expiresAt) {
        if (!expiresAt.isAfter(clock.instant())) return;
        update(sessionKey(event.identity()),true,current -> PreferenceProjectionSupport.change(
                current,event,restored,"session",expiresAt,clock.instant()));
    }

    private OnlinePreferenceSnapshot read(String key) {
        return decode(redis.opsForValue().get(key), key);
    }

    private OnlinePreferenceSnapshot decode(String value, String key) {
        if (value == null || value.isBlank()) {
            return OnlinePreferenceSnapshot.empty();
        }
        try {
            var snapshot = objectMapper.readValue(value, OnlinePreferenceSnapshot.class);
            if (snapshot != null) return snapshot;
        } catch (JsonProcessingException exception) {
            // Redis 不是事实来源。损坏值降级为空视图，写入仍以原始字符串进行 CAS，避免覆盖并发修复。
        }
        log.warn("在线偏好缓存无法解析，将从持久反馈重建：key={}", key);
        return OnlinePreferenceSnapshot.empty();
    }

    private OnlinePreferenceSnapshot update(String key, boolean session,
            java.util.function.UnaryOperator<OnlinePreferenceSnapshot> change) {
        for (int attempt = 0; attempt < 16; attempt++) {
            String before = redis.opsForValue().get(key);
            var current = decode(before, key);
            var next = change.apply(current);
            if (next.equals(current)) return current;
            if (session && next.expiresAt() == null) return next;
            Duration ttl = session ? Duration.between(clock.instant(), next.expiresAt()) : PreferenceProjectionSupport.PROFILE_TTL;
            if (ttl.toMillis() <= 0) return next;
            try {
                Long applied = redis.execute(COMPARE_AND_SET, List.of(key), before == null ? "" : before,
                        objectMapper.writeValueAsString(next), Long.toString(ttl.toMillis()));
                if (Long.valueOf(1).equals(applied)) return next;
            } catch (JsonProcessingException exception) {
                throw new IllegalStateException("cannot serialize online preference", exception);
            }
        }
        throw new IllegalStateException("online preference changed concurrently; retry from outbox");
    }

    private String sessionKey(RecommendationIdentity identity) {
        return "rs:pref:v2:session:" + identity.profileUserId() + ":" + identity.sessionId();
    }

    private String profileKey(RecommendationIdentity identity) {
        return "rs:pref:v2:profile:" + identity.profileUserId();
    }
}
