package com.sinrotic.rs.user.controller.auth;

import com.sinrotic.rs.user.domain.dto.LoginRequestDTO;
import com.sinrotic.rs.user.domain.dto.RefreshTokenRequestDTO;
import com.sinrotic.rs.user.domain.dto.RegisterRequestDTO;
import com.sinrotic.rs.user.domain.vo.AuthTokenVO;
import com.sinrotic.rs.user.domain.vo.CurrentAccountVO;
import com.sinrotic.rs.user.service.AuthService;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class AuthControllerTest {

    @Test
    void registerCreatesAccountBindingAndSession() {
        AuthService authService = mock(AuthService.class);
        AuthController controller = new AuthController(authService);

        when(authService.register(any(RegisterRequestDTO.class))).thenReturn(new AuthTokenVO(
                "acc_001",
                "alice",
                "Alice",
                "review_user_001",
                null,
                "access-token",
                "refresh-token",
                1800
        ));

        RegisterRequestDTO request = new RegisterRequestDTO(
                "alice",
                "123456",
                "Alice",
                "random",
                "recent_2y",
                null
        );
        AuthTokenVO response = controller.register(request);

        assertThat(response.accountId()).isEqualTo("acc_001");
        assertThat(response.username()).isEqualTo("alice");
        assertThat(response.nickname()).isEqualTo("Alice");
        assertThat(response.profileUserId()).isEqualTo("review_user_001");
        assertThat(response.accessToken()).isEqualTo("access-token");
        assertThat(response.refreshToken()).isEqualTo("refresh-token");
        assertThat(response.expiresIn()).isEqualTo(1800);
        verify(authService).register(request);
    }

    @Test
    void loginIssuesTokensForExistingAccountBinding() {
        AuthService authService = mock(AuthService.class);
        AuthController controller = new AuthController(authService);

        when(authService.login(any(LoginRequestDTO.class))).thenReturn(new AuthTokenVO(
                "acc_001",
                "alice",
                "Alice",
                "review_user_001",
                null,
                "access-token",
                "refresh-token",
                1800
        ));

        LoginRequestDTO request = new LoginRequestDTO("alice", "123456");
        AuthTokenVO response = controller.login(request);

        assertThat(response.accountId()).isEqualTo("acc_001");
        assertThat(response.username()).isEqualTo("alice");
        assertThat(response.nickname()).isEqualTo("Alice");
        assertThat(response.profileUserId()).isEqualTo("review_user_001");
        assertThat(response.accessToken()).isEqualTo("access-token");
        assertThat(response.refreshToken()).isEqualTo("refresh-token");
        assertThat(response.expiresIn()).isEqualTo(1800);
        verify(authService).login(request);
    }

    @Test
    void refreshRotatesTokensFromRefreshToken() {
        AuthService authService = mock(AuthService.class);
        AuthController controller = new AuthController(authService);

        when(authService.refresh(any(RefreshTokenRequestDTO.class))).thenReturn(new AuthTokenVO(
                "acc_001",
                "alice",
                "Alice",
                "review_user_001",
                null,
                "new-access-token",
                "new-refresh-token",
                1800
        ));

        RefreshTokenRequestDTO request = new RefreshTokenRequestDTO("old-refresh-token");
        AuthTokenVO response = controller.refresh(request);

        assertThat(response.accountId()).isEqualTo("acc_001");
        assertThat(response.username()).isEqualTo("alice");
        assertThat(response.nickname()).isEqualTo("Alice");
        assertThat(response.profileUserId()).isEqualTo("review_user_001");
        assertThat(response.accessToken()).isEqualTo("new-access-token");
        assertThat(response.refreshToken()).isEqualTo("new-refresh-token");
        assertThat(response.expiresIn()).isEqualTo(1800);
        verify(authService).refresh(request);
    }

    @Test
    void meReturnsCurrentAccountFromBearerToken() {
        AuthService authService = mock(AuthService.class);
        AuthController controller = new AuthController(authService);

        when(authService.currentAccount("Bearer access-token")).thenReturn(new CurrentAccountVO(
                "acc_001",
                "alice",
                "Alice",
                "review_user_001",
                null
        ));

        CurrentAccountVO response = controller.me("Bearer access-token");

        assertThat(response.accountId()).isEqualTo("acc_001");
        assertThat(response.username()).isEqualTo("alice");
        assertThat(response.nickname()).isEqualTo("Alice");
        assertThat(response.profileUserId()).isEqualTo("review_user_001");
        assertThat(response.profile()).isNull();
        verify(authService).currentAccount("Bearer access-token");
    }

    @Test
    void logoutRevokesCurrentBearerSession() {
        AuthService authService = mock(AuthService.class);
        AuthController controller = new AuthController(authService);

        controller.logout("Bearer access-token");

        verify(authService).logout("Bearer access-token");
    }
}
