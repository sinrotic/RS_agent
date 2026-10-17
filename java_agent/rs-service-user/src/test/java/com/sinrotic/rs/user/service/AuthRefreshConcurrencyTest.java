package com.sinrotic.rs.user.service;

import com.sinrotic.rs.user.domain.dto.RefreshTokenRequestDTO;
import com.sinrotic.rs.user.domain.entity.AuthSessionRefreshRecord;
import com.sinrotic.rs.user.exception.UserServiceException;
import com.sinrotic.rs.user.mapper.*;
import com.sinrotic.rs.user.service.token.TokenSessionStore;
import org.junit.jupiter.api.Test;
import java.time.LocalDateTime;
import java.util.List;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicInteger;
import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

class AuthRefreshConcurrencyTest {
    @Test
    void onlyOneConcurrentRefreshCanConsumeTheOldSession() throws Exception {
        var sessions = mock(AuthSessionMapper.class);
        var tokens = mock(TokenSessionStore.class);
        var service = new AuthService(mock(AuthAccountMapper.class), mock(AccountProfileBindingMapper.class),
                sessions, mock(ProfileUserMapper.class), tokens);
        var barrier = new CyclicBarrier(2);
        var revocations = new AtomicInteger();
        when(sessions.findRefreshSessionByRefreshTokenHash(anyString())).thenAnswer(call -> {
            barrier.await(5, TimeUnit.SECONDS);
            return new AuthSessionRefreshRecord("old", "account", "profile", LocalDateTime.now().plusDays(1),
                    null, "user", "user", "active");
        });
        when(sessions.revokeSession("old", "refresh")).thenAnswer(call -> revocations.getAndIncrement() == 0 ? 1 : 0);
        try (var pool = Executors.newFixedThreadPool(2)) {
            Callable<Boolean> refresh = () -> {
                try { service.refresh(new RefreshTokenRequestDTO("same-token")); return true; }
                catch (UserServiceException rejected) { return false; }
            };
            var results = pool.invokeAll(List.of(refresh, refresh));
            int successes = 0;
            for (var result : results) if (result.get(5, TimeUnit.SECONDS)) successes++;
            assertThat(successes).isEqualTo(1);
        }
        verify(tokens, times(1)).revokeSession(eq("old"),eq(null),anyString());
        verify(tokens, times(1)).save(any());
    }
}
