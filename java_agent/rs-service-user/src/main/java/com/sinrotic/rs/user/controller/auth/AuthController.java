package com.sinrotic.rs.user.controller.auth;

import com.sinrotic.rs.user.domain.dto.LoginRequestDTO;
import com.sinrotic.rs.user.domain.dto.RefreshTokenRequestDTO;
import com.sinrotic.rs.user.domain.dto.RegisterRequestDTO;
import com.sinrotic.rs.user.domain.vo.AuthTokenVO;
import com.sinrotic.rs.user.domain.vo.CurrentAccountVO;
import com.sinrotic.rs.user.service.AuthService;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.CookieValue;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import jakarta.servlet.http.HttpServletResponse;

/**
 * Handles account registration, login, token refresh, logout, and current-account queries.
 *
 * This controller should stay thin: receive HTTP requests, read authentication context,
 * call AuthService, and return response objects.
 */
@RestController
@RequestMapping("/api/auth")
public class AuthController {

    private final AuthService authService;

    private final AuthCookieService authCookieService;

    public AuthController(AuthService authService, AuthCookieService authCookieService) {
        this.authService = authService;
        this.authCookieService = authCookieService;
    }

    @PostMapping("/register")
    public AuthTokenVO register(@RequestBody RegisterRequestDTO request, HttpServletResponse response) {
        AuthTokenVO tokens = authService.register(request);
        authCookieService.write(response, tokens.refreshToken());
        return tokens;
    }

    @PostMapping("/login")
    public AuthTokenVO login(@RequestBody LoginRequestDTO request, HttpServletResponse response) {
        AuthTokenVO tokens = authService.login(request);
        authCookieService.write(response, tokens.refreshToken());
        return tokens;
    }

    @PostMapping("/refresh")
    public AuthTokenVO refresh(
            @RequestBody(required = false) RefreshTokenRequestDTO request,
            @CookieValue(name = AuthCookieService.REFRESH_COOKIE, required = false) String refreshCookie,
            @CookieValue(name = AuthCookieService.CSRF_COOKIE, required = false) String csrfCookie,
            @RequestHeader(name = AuthCookieService.CSRF_HEADER, required = false) String csrfHeader,
            HttpServletResponse response
    ) {
        String refreshToken = authCookieService.resolveRefreshToken(
                refreshCookie,
                csrfCookie,
                csrfHeader,
                request == null ? null : request.refreshToken()
        );
        AuthTokenVO tokens = authService.refresh(new RefreshTokenRequestDTO(refreshToken));
        authCookieService.write(response, tokens.refreshToken());
        return tokens;
    }

    @GetMapping("/me")
    public CurrentAccountVO me(@RequestHeader("Authorization") String authorizationHeader) {
        return authService.currentAccount(authorizationHeader);
    }

    @PostMapping("/logout")
    public void logout(
            @RequestHeader("Authorization") String authorizationHeader,
            HttpServletResponse response
    ) {
        try {
            authService.logout(authorizationHeader);
        } finally {
            authCookieService.clear(response);
        }
    }
}
