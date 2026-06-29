package com.sinrotic.rs.user.controller.auth;

import com.sinrotic.rs.user.domain.dto.LoginRequestDTO;
import com.sinrotic.rs.user.domain.dto.RefreshTokenRequestDTO;
import com.sinrotic.rs.user.domain.dto.RegisterRequestDTO;
import com.sinrotic.rs.user.domain.vo.AuthTokenVO;
import com.sinrotic.rs.user.domain.vo.CurrentAccountVO;
import com.sinrotic.rs.user.service.AuthService;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

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

    public AuthController(AuthService authService) {
        this.authService = authService;
    }

    @PostMapping("/register")
    public AuthTokenVO register(@RequestBody RegisterRequestDTO request) {
        return authService.register(request);
    }

    @PostMapping("/login")
    public AuthTokenVO login(@RequestBody LoginRequestDTO request) {
        return authService.login(request);
    }

    @PostMapping("/refresh")
    public AuthTokenVO refresh(@RequestBody RefreshTokenRequestDTO request) {
        return authService.refresh(request);
    }

    @GetMapping("/me")
    public CurrentAccountVO me(@RequestHeader("Authorization") String authorizationHeader) {
        return authService.currentAccount(authorizationHeader);
    }

    @PostMapping("/logout")
    public void logout(@RequestHeader("Authorization") String authorizationHeader) {
        authService.logout(authorizationHeader);
    }
}
