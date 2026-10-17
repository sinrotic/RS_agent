package com.sinrotic.rs.user.controller.auth;

import jakarta.servlet.http.HttpServletResponse;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseCookie;
import org.springframework.stereotype.Component;
import org.springframework.web.server.ResponseStatusException;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.SecureRandom;
import java.time.Duration;
import java.util.Base64;

@Component
public class AuthCookieService {

    public static final String REFRESH_COOKIE = "rs_refresh_token";

    public static final String CSRF_COOKIE = "rs_refresh_csrf";

    public static final String CSRF_HEADER = "X-CSRF-Token";

    private static final Duration REFRESH_MAX_AGE = Duration.ofDays(30);

    private final boolean secure;

    private final SecureRandom secureRandom = new SecureRandom();

    public AuthCookieService(@Value("${rs.auth.refresh-cookie.secure:false}") boolean secure) {
        this.secure = secure;
    }

    public void write(HttpServletResponse response, String refreshToken) {
        response.addHeader(HttpHeaders.SET_COOKIE, refreshCookie(refreshToken, REFRESH_MAX_AGE).toString());
        response.addHeader(HttpHeaders.SET_COOKIE, csrfCookie(randomCsrfToken(), REFRESH_MAX_AGE).toString());
    }

    public void clear(HttpServletResponse response) {
        response.addHeader(HttpHeaders.SET_COOKIE, refreshCookie("", Duration.ZERO).toString());
        response.addHeader(HttpHeaders.SET_COOKIE, csrfCookie("", Duration.ZERO).toString());
    }

    public String resolveRefreshToken(
            String cookieToken,
            String csrfCookie,
            String csrfHeader,
            String bodyToken
    ) {
        if (cookieToken != null && !cookieToken.isBlank()) {
            if (!constantTimeEquals(csrfCookie, csrfHeader)) {
                throw new ResponseStatusException(HttpStatus.FORBIDDEN, "Refresh token CSRF validation failed");
            }
            return cookieToken;
        }
        if (bodyToken != null && !bodyToken.isBlank()) {
            return bodyToken.trim();
        }
        throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "refreshToken is required");
    }

    private ResponseCookie refreshCookie(String value, Duration maxAge) {
        return ResponseCookie.from(REFRESH_COOKIE, value)
                .httpOnly(true)
                .secure(secure)
                .sameSite("Strict")
                .path("/api/auth")
                .maxAge(maxAge)
                .build();
    }

    private ResponseCookie csrfCookie(String value, Duration maxAge) {
        return ResponseCookie.from(CSRF_COOKIE, value)
                .httpOnly(false)
                .secure(secure)
                .sameSite("Strict")
                .path("/")
                .maxAge(maxAge)
                .build();
    }

    private String randomCsrfToken() {
        byte[] bytes = new byte[24];
        secureRandom.nextBytes(bytes);
        return Base64.getUrlEncoder().withoutPadding().encodeToString(bytes);
    }

    private boolean constantTimeEquals(String left, String right) {
        if (left == null || right == null) {
            return false;
        }
        return MessageDigest.isEqual(
                left.getBytes(StandardCharsets.UTF_8),
                right.getBytes(StandardCharsets.UTF_8)
        );
    }
}
