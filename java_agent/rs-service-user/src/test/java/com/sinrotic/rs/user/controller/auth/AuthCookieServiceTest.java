package com.sinrotic.rs.user.controller.auth;

import jakarta.servlet.http.HttpServletResponse;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;

class AuthCookieServiceTest {

    @Test
    void writesHttpOnlyStrictRefreshCookieAndReadableCsrfCookie() {
        AuthCookieService service = new AuthCookieService(true);
        HttpServletResponse response = mock(HttpServletResponse.class);

        service.write(response, "refresh-token");

        verify(response).addHeader(eq("Set-Cookie"), org.mockito.ArgumentMatchers.argThat(value ->
                value.contains("rs_refresh_token=refresh-token")
                        && value.contains("HttpOnly")
                        && value.contains("Secure")
                        && value.contains("SameSite=Strict")
        ));
        verify(response).addHeader(eq("Set-Cookie"), org.mockito.ArgumentMatchers.argThat(value ->
                value.startsWith("rs_refresh_csrf=") && !value.contains("HttpOnly")
        ));
    }

    @Test
    void cookieRefreshRequiresMatchingCsrfHeader() {
        AuthCookieService service = new AuthCookieService(false);

        assertThat(service.resolveRefreshToken("cookie-token", "csrf-token", "csrf-token", null))
                .isEqualTo("cookie-token");
        assertThatThrownBy(() -> service.resolveRefreshToken("cookie-token", "csrf-token", "wrong", null))
                .isInstanceOf(org.springframework.web.server.ResponseStatusException.class)
                .hasMessageContaining("CSRF");
    }

    @Test
    void bodyRefreshTokenRemainsAvailableForNonBrowserClients() {
        AuthCookieService service = new AuthCookieService(false);

        assertThat(service.resolveRefreshToken(null, null, null, "body-token"))
                .isEqualTo("body-token");
    }
}
