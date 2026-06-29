package com.sinrotic.rs.user.service;

import com.sinrotic.rs.user.domain.dto.LoginRequestDTO;
import com.sinrotic.rs.user.domain.dto.RefreshTokenRequestDTO;
import com.sinrotic.rs.user.domain.dto.RegisterRequestDTO;
import com.sinrotic.rs.user.domain.entity.AuthAccountLoginRecord;
import com.sinrotic.rs.user.domain.entity.AuthSessionCurrentAccountRecord;
import com.sinrotic.rs.user.domain.entity.AuthSessionRefreshRecord;
import com.sinrotic.rs.user.domain.vo.AuthTokenVO;
import com.sinrotic.rs.user.domain.vo.CurrentAccountVO;
import com.sinrotic.rs.user.mapper.AccountProfileBindingMapper;
import com.sinrotic.rs.user.mapper.AuthAccountMapper;
import com.sinrotic.rs.user.mapper.AuthSessionMapper;
import com.sinrotic.rs.user.mapper.ProfileUserMapper;
import com.sinrotic.rs.user.service.token.TokenSession;
import com.sinrotic.rs.user.service.token.TokenSessionStore;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;

import java.time.LocalDateTime;
import java.util.Optional;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class AuthServiceTest {

    @Test
    void registerCreatesAccountBindingAndAuthSessionFromRandomReviewUser() {
        AuthAccountMapper authAccountMapper = mock(AuthAccountMapper.class);
        AccountProfileBindingMapper bindingMapper = mock(AccountProfileBindingMapper.class);
        AuthSessionMapper authSessionMapper = mock(AuthSessionMapper.class);
        ProfileUserMapper profileUserMapper = mock(ProfileUserMapper.class);
        AuthService authService = new AuthService(
                authAccountMapper,
                bindingMapper,
                authSessionMapper,
                profileUserMapper
        );

        when(authAccountMapper.countByUsername("alice")).thenReturn(0);
        when(profileUserMapper.selectRandomReviewUserId()).thenReturn("review_user_001");

        AuthTokenVO response = authService.register(new RegisterRequestDTO(
                "alice",
                "123456",
                "Alice",
                "random",
                "recent_2y",
                null
        ));

        assertThat(response.accountId()).startsWith("acc_");
        assertThat(response.username()).isEqualTo("alice");
        assertThat(response.nickname()).isEqualTo("Alice");
        assertThat(response.profileUserId()).isEqualTo("review_user_001");
        assertThat(response.accessToken()).isNotBlank();
        assertThat(response.refreshToken()).isNotBlank();
        assertThat(response.expiresIn()).isEqualTo(1800);

        ArgumentCaptor<String> passwordHash = ArgumentCaptor.forClass(String.class);
        verify(authAccountMapper).insertAccount(
                eq(response.accountId()),
                eq("alice"),
                passwordHash.capture(),
                eq("Alice"),
                eq(null)
        );
        assertThat(passwordHash.getValue()).isNotEqualTo("123456");
        assertThat(passwordHash.getValue()).startsWith("$2");

        verify(bindingMapper).insertBinding(
                org.mockito.ArgumentMatchers.startsWith("bind_"),
                eq(response.accountId()),
                eq("review_user_001"),
                eq("random"),
                eq("recent_2y")
        );
        verify(authSessionMapper).insertSession(
                org.mockito.ArgumentMatchers.startsWith("authsess_"),
                eq(response.accountId()),
                eq("review_user_001"),
                org.mockito.ArgumentMatchers.matches("[0-9a-f]{64}"),
                org.mockito.ArgumentMatchers.matches("[0-9a-f]{64}"),
                any(LocalDateTime.class),
                any(LocalDateTime.class),
                eq(null),
                eq(null)
        );
    }

    @Test
    void loginVerifiesPasswordAndCreatesNewAuthSession() {
        AuthAccountMapper authAccountMapper = mock(AuthAccountMapper.class);
        AccountProfileBindingMapper bindingMapper = mock(AccountProfileBindingMapper.class);
        AuthSessionMapper authSessionMapper = mock(AuthSessionMapper.class);
        ProfileUserMapper profileUserMapper = mock(ProfileUserMapper.class);
        AuthService authService = new AuthService(
                authAccountMapper,
                bindingMapper,
                authSessionMapper,
                profileUserMapper
        );
        String passwordHash = new BCryptPasswordEncoder().encode("123456");

        when(authAccountMapper.findLoginAccountByUsername("alice")).thenReturn(new AuthAccountLoginRecord(
                "acc_001",
                "alice",
                passwordHash,
                "Alice",
                "active",
                0L
        ));
        when(bindingMapper.findActiveProfileUserIdByAccountId("acc_001")).thenReturn("review_user_001");

        AuthTokenVO response = authService.login(new LoginRequestDTO("alice", "123456"));

        assertThat(response.accountId()).isEqualTo("acc_001");
        assertThat(response.username()).isEqualTo("alice");
        assertThat(response.nickname()).isEqualTo("Alice");
        assertThat(response.profileUserId()).isEqualTo("review_user_001");
        assertThat(response.accessToken()).isNotBlank();
        assertThat(response.refreshToken()).isNotBlank();
        assertThat(response.expiresIn()).isEqualTo(1800);

        verify(authAccountMapper).findLoginAccountByUsername("alice");
        verify(bindingMapper).findActiveProfileUserIdByAccountId("acc_001");
        verify(authSessionMapper).insertSession(
                org.mockito.ArgumentMatchers.startsWith("authsess_"),
                eq("acc_001"),
                eq("review_user_001"),
                org.mockito.ArgumentMatchers.matches("[0-9a-f]{64}"),
                org.mockito.ArgumentMatchers.matches("[0-9a-f]{64}"),
                any(LocalDateTime.class),
                any(LocalDateTime.class),
                eq(null),
                eq(null)
        );
    }

    @Test
    void loginStoresOnlineTokenSessionForRedisBackedValidation() {
        AuthAccountMapper authAccountMapper = mock(AuthAccountMapper.class);
        AccountProfileBindingMapper bindingMapper = mock(AccountProfileBindingMapper.class);
        AuthSessionMapper authSessionMapper = mock(AuthSessionMapper.class);
        ProfileUserMapper profileUserMapper = mock(ProfileUserMapper.class);
        TokenSessionStore tokenSessionStore = mock(TokenSessionStore.class);
        AuthService authService = new AuthService(
                authAccountMapper,
                bindingMapper,
                authSessionMapper,
                profileUserMapper,
                tokenSessionStore
        );
        String passwordHash = new BCryptPasswordEncoder().encode("123456");

        when(authAccountMapper.findLoginAccountByUsername("alice")).thenReturn(new AuthAccountLoginRecord(
                "acc_001",
                "alice",
                passwordHash,
                "Alice",
                "active",
                0L
        ));
        when(bindingMapper.findActiveProfileUserIdByAccountId("acc_001")).thenReturn("review_user_001");

        authService.login(new LoginRequestDTO("alice", "123456"));

        ArgumentCaptor<TokenSession> session = ArgumentCaptor.forClass(TokenSession.class);
        verify(tokenSessionStore).save(session.capture());
        assertThat(session.getValue().sessionId()).startsWith("authsess_");
        assertThat(session.getValue().accountId()).isEqualTo("acc_001");
        assertThat(session.getValue().profileUserId()).isEqualTo("review_user_001");
        assertThat(session.getValue().accessTokenHash()).matches("[0-9a-f]{64}");
        assertThat(session.getValue().refreshTokenHash()).matches("[0-9a-f]{64}");
    }

    @Test
    void currentAccountUsesOnlineTokenSessionBeforeDatabaseLookup() {
        AuthAccountMapper authAccountMapper = mock(AuthAccountMapper.class);
        AccountProfileBindingMapper bindingMapper = mock(AccountProfileBindingMapper.class);
        AuthSessionMapper authSessionMapper = mock(AuthSessionMapper.class);
        ProfileUserMapper profileUserMapper = mock(ProfileUserMapper.class);
        TokenSessionStore tokenSessionStore = mock(TokenSessionStore.class);
        AuthService authService = new AuthService(
                authAccountMapper,
                bindingMapper,
                authSessionMapper,
                profileUserMapper,
                tokenSessionStore
        );
        when(tokenSessionStore.findByAccessTokenHash(org.mockito.ArgumentMatchers.matches("[0-9a-f]{64}")))
                .thenReturn(Optional.of(new TokenSession(
                        "authsess_001",
                        "acc_001",
                        "alice",
                        "Alice",
                        "review_user_001",
                        "access-hash",
                        "refresh-hash",
                        LocalDateTime.now().plusMinutes(10),
                        LocalDateTime.now().plusDays(1),
                        "active"
                )));

        CurrentAccountVO response = authService.currentAccount("Bearer access-token");

        assertThat(response.accountId()).isEqualTo("acc_001");
        assertThat(response.username()).isEqualTo("alice");
        assertThat(response.nickname()).isEqualTo("Alice");
        assertThat(response.profileUserId()).isEqualTo("review_user_001");
        verify(authSessionMapper, never()).findCurrentAccountByAccessTokenHash(any());
    }

    @Test
    void refreshRevokesOldSessionAndCreatesNewAuthSession() {
        AuthAccountMapper authAccountMapper = mock(AuthAccountMapper.class);
        AccountProfileBindingMapper bindingMapper = mock(AccountProfileBindingMapper.class);
        AuthSessionMapper authSessionMapper = mock(AuthSessionMapper.class);
        ProfileUserMapper profileUserMapper = mock(ProfileUserMapper.class);
        AuthService authService = new AuthService(
                authAccountMapper,
                bindingMapper,
                authSessionMapper,
                profileUserMapper
        );
        when(authSessionMapper.findRefreshSessionByRefreshTokenHash(org.mockito.ArgumentMatchers.matches("[0-9a-f]{64}")))
                .thenReturn(new AuthSessionRefreshRecord(
                        "authsess_old",
                        "acc_001",
                        "review_user_001",
                        LocalDateTime.now().plusDays(1),
                        null,
                        "alice",
                        "Alice",
                        "active"
                ));

        AuthTokenVO response = authService.refresh(new RefreshTokenRequestDTO("old-refresh-token"));

        assertThat(response.accountId()).isEqualTo("acc_001");
        assertThat(response.username()).isEqualTo("alice");
        assertThat(response.nickname()).isEqualTo("Alice");
        assertThat(response.profileUserId()).isEqualTo("review_user_001");
        assertThat(response.accessToken()).isNotBlank();
        assertThat(response.refreshToken()).isNotBlank();
        assertThat(response.refreshToken()).isNotEqualTo("old-refresh-token");
        assertThat(response.expiresIn()).isEqualTo(1800);

        verify(authSessionMapper).revokeSession("authsess_old", "refresh");
        verify(authSessionMapper).insertSession(
                org.mockito.ArgumentMatchers.startsWith("authsess_"),
                eq("acc_001"),
                eq("review_user_001"),
                org.mockito.ArgumentMatchers.matches("[0-9a-f]{64}"),
                org.mockito.ArgumentMatchers.matches("[0-9a-f]{64}"),
                any(LocalDateTime.class),
                any(LocalDateTime.class),
                eq(null),
                eq(null)
        );
    }

    @Test
    void refreshRevokesOldOnlineSessionAndStoresNewOnlineSession() {
        AuthAccountMapper authAccountMapper = mock(AuthAccountMapper.class);
        AccountProfileBindingMapper bindingMapper = mock(AccountProfileBindingMapper.class);
        AuthSessionMapper authSessionMapper = mock(AuthSessionMapper.class);
        ProfileUserMapper profileUserMapper = mock(ProfileUserMapper.class);
        TokenSessionStore tokenSessionStore = mock(TokenSessionStore.class);
        AuthService authService = new AuthService(
                authAccountMapper,
                bindingMapper,
                authSessionMapper,
                profileUserMapper,
                tokenSessionStore
        );
        when(authSessionMapper.findRefreshSessionByRefreshTokenHash(org.mockito.ArgumentMatchers.matches("[0-9a-f]{64}")))
                .thenReturn(new AuthSessionRefreshRecord(
                        "authsess_old",
                        "acc_001",
                        "review_user_001",
                        LocalDateTime.now().plusDays(1),
                        null,
                        "alice",
                        "Alice",
                        "active"
                ));

        authService.refresh(new RefreshTokenRequestDTO("old-refresh-token"));

        verify(tokenSessionStore).revokeSession("authsess_old");
        verify(tokenSessionStore).save(any(TokenSession.class));
    }

    @Test
    void currentAccountLoadsAccountFromValidBearerAccessToken() {
        AuthAccountMapper authAccountMapper = mock(AuthAccountMapper.class);
        AccountProfileBindingMapper bindingMapper = mock(AccountProfileBindingMapper.class);
        AuthSessionMapper authSessionMapper = mock(AuthSessionMapper.class);
        ProfileUserMapper profileUserMapper = mock(ProfileUserMapper.class);
        AuthService authService = new AuthService(
                authAccountMapper,
                bindingMapper,
                authSessionMapper,
                profileUserMapper
        );
        when(authSessionMapper.findCurrentAccountByAccessTokenHash(org.mockito.ArgumentMatchers.matches("[0-9a-f]{64}")))
                .thenReturn(new AuthSessionCurrentAccountRecord(
                        "authsess_001",
                        "acc_001",
                        "review_user_001",
                        LocalDateTime.now().plusMinutes(10),
                        null,
                        "alice",
                        "Alice",
                        "active"
                ));

        CurrentAccountVO response = authService.currentAccount("Bearer access-token");

        assertThat(response.accountId()).isEqualTo("acc_001");
        assertThat(response.username()).isEqualTo("alice");
        assertThat(response.nickname()).isEqualTo("Alice");
        assertThat(response.profileUserId()).isEqualTo("review_user_001");
        assertThat(response.profile()).isNull();
        verify(authSessionMapper).findCurrentAccountByAccessTokenHash(
                org.mockito.ArgumentMatchers.matches("[0-9a-f]{64}")
        );
    }

    @Test
    void logoutRevokesCurrentAccessTokenSession() {
        AuthAccountMapper authAccountMapper = mock(AuthAccountMapper.class);
        AccountProfileBindingMapper bindingMapper = mock(AccountProfileBindingMapper.class);
        AuthSessionMapper authSessionMapper = mock(AuthSessionMapper.class);
        ProfileUserMapper profileUserMapper = mock(ProfileUserMapper.class);
        AuthService authService = new AuthService(
                authAccountMapper,
                bindingMapper,
                authSessionMapper,
                profileUserMapper
        );
        when(authSessionMapper.findCurrentAccountByAccessTokenHash(org.mockito.ArgumentMatchers.matches("[0-9a-f]{64}")))
                .thenReturn(new AuthSessionCurrentAccountRecord(
                        "authsess_001",
                        "acc_001",
                        "review_user_001",
                        LocalDateTime.now().plusMinutes(10),
                        null,
                        "alice",
                        "Alice",
                        "active"
                ));

        authService.logout("Bearer access-token");

        verify(authSessionMapper).findCurrentAccountByAccessTokenHash(
                org.mockito.ArgumentMatchers.matches("[0-9a-f]{64}")
        );
        verify(authSessionMapper).revokeSession("authsess_001", "logout");
    }

    @Test
    void logoutRevokesOnlineSession() {
        AuthAccountMapper authAccountMapper = mock(AuthAccountMapper.class);
        AccountProfileBindingMapper bindingMapper = mock(AccountProfileBindingMapper.class);
        AuthSessionMapper authSessionMapper = mock(AuthSessionMapper.class);
        ProfileUserMapper profileUserMapper = mock(ProfileUserMapper.class);
        TokenSessionStore tokenSessionStore = mock(TokenSessionStore.class);
        AuthService authService = new AuthService(
                authAccountMapper,
                bindingMapper,
                authSessionMapper,
                profileUserMapper,
                tokenSessionStore
        );
        when(tokenSessionStore.findByAccessTokenHash(org.mockito.ArgumentMatchers.matches("[0-9a-f]{64}")))
                .thenReturn(Optional.of(new TokenSession(
                        "authsess_001",
                        "acc_001",
                        "alice",
                        "Alice",
                        "review_user_001",
                        "access-hash",
                        "refresh-hash",
                        LocalDateTime.now().plusMinutes(10),
                        LocalDateTime.now().plusDays(1),
                        "active"
                )));

        authService.logout("Bearer access-token");

        verify(tokenSessionStore).revokeSession("authsess_001");
        verify(authSessionMapper).revokeSession("authsess_001", "logout");
    }
}
