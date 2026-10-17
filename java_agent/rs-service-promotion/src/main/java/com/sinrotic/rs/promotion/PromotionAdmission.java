package com.sinrotic.rs.promotion;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.script.DefaultRedisScript;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Component;
import org.springframework.web.server.ResponseStatusException;
import java.util.List;

@Component
public class PromotionAdmission {
    private final StringRedisTemplate redis;
    private final int limit;
    private static final DefaultRedisScript<Long> SCRIPT = new DefaultRedisScript<>("""
            local count = tonumber(redis.call('GET', KEYS[1]) or '0')
            if count >= tonumber(ARGV[1]) then return 0 end
            local next = redis.call('INCR', KEYS[1])
            if next == 1 then redis.call('PEXPIRE', KEYS[1], 1000) end
            return 1
            """, Long.class);
    public PromotionAdmission(StringRedisTemplate redis, @Value("${rs.promotion.claims-per-second:200}") int limit) {
        this.redis = redis; this.limit = Math.max(1,limit);
    }
    public void check(String campaignId) {
        if (campaignId == null || campaignId.isBlank() || campaignId.length() > 64)
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST,"活动标识不合法");
        Long allowed;
        try { allowed = redis.execute(SCRIPT,List.of("promotion:admission:"+campaignId),Integer.toString(limit)); }
        catch (org.springframework.dao.DataAccessException unavailable) {
            throw new ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE,"领券暂不可用，请稍后重试");
        }
        if (!Long.valueOf(1).equals(allowed)) throw new ResponseStatusException(HttpStatus.TOO_MANY_REQUESTS,"领取人数较多，请稍后重试");
    }
}
