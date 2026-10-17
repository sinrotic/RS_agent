package com.sinrotic.rs.gateway.filter;

import org.junit.jupiter.api.Test;
import org.springframework.data.redis.core.*;
import reactor.core.publisher.Mono;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.time.LocalDateTime;
import java.util.*;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;

class RedisGatewayTokenValidatorTest {
    @Test
    void orphanAccessEntryCannotAuthenticateWithoutItsLiveCanonicalSession() throws Exception {
        String token = "local-fake-access";
        String hash = HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(token.getBytes(StandardCharsets.UTF_8)));
        Map<String,String> cache = new HashMap<>();
        String payload = "{\"sessionId\":\"session\",\"accountId\":\"account\",\"profileUserId\":\"profile\","
                +"\"accessTokenHash\":\""+hash+"\",\"accountStatus\":\"active\",\"accessExpiresAt\":\""
                +LocalDateTime.now().plusMinutes(30)+"\"}";
        cache.put("auth:access:"+hash,payload);
        ReactiveStringRedisTemplate redis = mock(ReactiveStringRedisTemplate.class);
        ReactiveValueOperations<String,String> values = mock(ReactiveValueOperations.class);
        when(redis.opsForValue()).thenReturn(values);
        when(values.get(anyString())).thenAnswer(i -> Mono.justOrEmpty(cache.get(i.getArgument(0))));
        var validator = new RedisGatewayTokenValidator(redis);
        assertThat(validator.validate(token).block()).isNull();
        cache.put("auth:session:session",payload);
        assertThat(validator.validate(token).block().accountId()).isEqualTo("account");
        // User 的 JavaTimeModule 默认输出日期数组；兼容已有登录态。
        var mapper = new com.fasterxml.jackson.databind.ObjectMapper()
                .registerModule(new com.fasterxml.jackson.datatype.jsr310.JavaTimeModule());
        var root = (com.fasterxml.jackson.databind.node.ObjectNode) mapper.readTree(payload);
        root.set("accessExpiresAt",mapper.valueToTree(LocalDateTime.now().plusMinutes(30)));
        String arrayDatePayload = mapper.writeValueAsString(root);
        cache.put("auth:access:"+hash,arrayDatePayload);
        cache.put("auth:session:session",arrayDatePayload);
        assertThat(validator.validate(token).block().accountId()).isEqualTo("account");
        root.set("accessExpiresAt",mapper.valueToTree(LocalDateTime.now().minusSeconds(1)));
        String expired = mapper.writeValueAsString(root);
        cache.put("auth:access:"+hash,expired);
        cache.put("auth:session:session",expired);
        assertThat(validator.validate(token).block()).isNull();
        cache.put("auth:access:"+hash,payload);
        cache.put("auth:session:session",arrayDatePayload);
        assertThat(validator.validate(token).block()).isNull();
        cache.remove("auth:session:session");
        assertThat(validator.validate(token).block()).isNull();
    }
}
