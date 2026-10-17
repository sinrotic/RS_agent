package com.sinrotic.rs.user.service;

import com.sinrotic.rs.user.domain.entity.AuthSessionCurrentAccountRecord;
import com.sinrotic.rs.user.exception.UserServiceException;
import com.sinrotic.rs.user.mapper.*;
import com.sinrotic.rs.user.service.token.*;
import org.junit.jupiter.api.Test;
import org.springframework.data.redis.core.*;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.time.*;
import java.util.*;
import java.util.concurrent.atomic.AtomicBoolean;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;

class RedisAuthRevocationTest {
    @Test
    void logoutRevokesKnownTokenEvenWhenIndependentSessionIndexHasDisappeared() throws Exception {
        Map<String,String> cache = new HashMap<>();
        StringRedisTemplate redis = mock(StringRedisTemplate.class);
        ValueOperations<String,String> values = mock(ValueOperations.class);
        when(redis.opsForValue()).thenReturn(values);
        when(values.get(anyString())).thenAnswer(i -> cache.get(i.getArgument(0)));
        doAnswer(i -> { cache.put(i.getArgument(0),i.getArgument(1)); return null; })
                .when(values).set(anyString(),anyString(),any(Duration.class));
        when(redis.delete(anyString())).thenAnswer(i -> cache.remove(i.getArgument(0))!=null);
        RedisTokenSessionStore store = new RedisTokenSessionStore(redis);
        String hash = HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256")
                .digest("fake-access".getBytes(StandardCharsets.UTF_8)));
        LocalDateTime expiry = LocalDateTime.now().plusMinutes(30);
        store.save(new TokenSession("session","account","name","name","profile",hash,"refresh-hash",
                expiry,expiry.plusDays(30),"active"));
        cache.remove("auth:session:session");
        AuthSessionMapper mapper = mock(AuthSessionMapper.class);
        AtomicBoolean revoked = new AtomicBoolean();
        when(mapper.findCurrentAccountByAccessTokenHash(hash)).thenAnswer(i ->
                new AuthSessionCurrentAccountRecord("session","account","profile",expiry,
                        revoked.get() ? LocalDateTime.now() : null,"name","name","active"));
        when(mapper.revokeSession("session","logout")).thenAnswer(i -> { revoked.set(true); return 1; });
        AuthService auth = new AuthService(mock(AuthAccountMapper.class),mock(AccountProfileBindingMapper.class),
                mapper,mock(ProfileUserMapper.class),store);
        auth.logout("Bearer fake-access");
        assertThat(revoked).isTrue();
        assertThat(cache).doesNotContainKeys("auth:access:"+hash,"auth:refresh:refresh-hash");
        assertThatThrownBy(() -> auth.currentAccount("Bearer fake-access")).isInstanceOf(UserServiceException.class);
    }
}
