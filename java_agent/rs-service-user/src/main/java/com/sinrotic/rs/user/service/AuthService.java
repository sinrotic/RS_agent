package com.sinrotic.rs.user.service;

import com.sinrotic.rs.user.domain.dto.LoginRequestDTO;
import com.sinrotic.rs.user.domain.dto.RefreshTokenRequestDTO;
import com.sinrotic.rs.user.domain.dto.RegisterRequestDTO;
import com.sinrotic.rs.user.domain.entity.AuthAccountLoginRecord;
import com.sinrotic.rs.user.domain.entity.AuthSessionCurrentAccountRecord;
import com.sinrotic.rs.user.domain.entity.AuthSessionRefreshRecord;
import com.sinrotic.rs.user.domain.vo.AuthTokenVO;
import com.sinrotic.rs.user.domain.vo.CurrentAccountVO;
import com.sinrotic.rs.user.exception.UserServiceException;
import com.sinrotic.rs.user.mapper.AccountProfileBindingMapper;
import com.sinrotic.rs.user.mapper.AuthAccountMapper;
import com.sinrotic.rs.user.mapper.AuthSessionMapper;
import com.sinrotic.rs.user.mapper.ProfileUserMapper;
import com.sinrotic.rs.user.service.token.InMemoryTokenSessionStore;
import com.sinrotic.rs.user.service.token.TokenSession;
import com.sinrotic.rs.user.service.token.TokenSessionStore;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.security.SecureRandom;
import java.time.LocalDateTime;
import java.util.Base64;
import java.util.HexFormat;
import java.util.Locale;
import java.util.UUID;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.security.crypto.password.PasswordEncoder;

/**
 * Orchestrates account registration, login, token issuing, token refresh, and logout.
 */
@Service
public class AuthService {

    private static final long ACCESS_TOKEN_TTL_SECONDS = 1800;
    private static final long REFRESH_TOKEN_TTL_SECONDS = 30L * 24 * 60 * 60;
    private static final String DEFAULT_BIND_STRATEGY = "random";

    private final AuthAccountMapper authAccountMapper;
    private final AccountProfileBindingMapper accountProfileBindingMapper;
    private final AuthSessionMapper authSessionMapper;
    private final ProfileUserMapper profileUserMapper;
    private final TokenSessionStore tokenSessionStore;
    private final PasswordEncoder passwordEncoder;
    private final SecureRandom secureRandom;

    @Autowired
    public AuthService(
            AuthAccountMapper authAccountMapper,
            AccountProfileBindingMapper accountProfileBindingMapper,
            AuthSessionMapper authSessionMapper,
            ProfileUserMapper profileUserMapper
    ) {
        this(
                authAccountMapper,
                accountProfileBindingMapper,
                authSessionMapper,
                profileUserMapper,
                new InMemoryTokenSessionStore()
        );
    }

    public AuthService(
            AuthAccountMapper authAccountMapper,
            AccountProfileBindingMapper accountProfileBindingMapper,
            AuthSessionMapper authSessionMapper,
            ProfileUserMapper profileUserMapper,
            TokenSessionStore tokenSessionStore
    ) {
        this.authAccountMapper = authAccountMapper;
        this.accountProfileBindingMapper = accountProfileBindingMapper;
        this.authSessionMapper = authSessionMapper;
        this.profileUserMapper = profileUserMapper;
        this.tokenSessionStore = tokenSessionStore;
        this.passwordEncoder = new BCryptPasswordEncoder();
        this.secureRandom = new SecureRandom();
    }

    @Transactional
    public AuthTokenVO register(RegisterRequestDTO request) {
        String username = requiredTrim(request.username(), "username");
        String password = requiredTrim(request.password(), "password");
        String nickname = optionalTrim(request.nickname());
        String bindStrategy = normalizedStrategy(request.bindStrategy());
        String segment = optionalTrim(request.segment());

        if (authAccountMapper.countByUsername(username) > 0) {
            throw new UserServiceException("username already exists");
        }

        String profileUserId = resolveProfileUserId(bindStrategy, request.profileUserId());
        String accountId = prefixedId("acc");
        String bindingId = prefixedId("bind");

        authAccountMapper.insertAccount(
                accountId,
                username,
                passwordEncoder.encode(password),
                nickname == null ? username : nickname,
                null
        );
        accountProfileBindingMapper.insertBinding(
                bindingId,
                accountId,
                profileUserId,
                bindStrategy,
                segment
        );

        return issueToken(
                accountId,
                username,
                nickname == null ? username : nickname,
                profileUserId
        );
    }

    @Transactional
    public AuthTokenVO login(LoginRequestDTO request) {
        String username = requiredTrim(request.username(), "username");
        String password = requiredTrim(request.password(), "password");
        AuthAccountLoginRecord account = authAccountMapper.findLoginAccountByUsername(username);

        if (account == null || !passwordEncoder.matches(password, account.passwordHash())) {
            throw new UserServiceException("invalid username or password");
        }
        if (!"active".equals(account.status())) {
            throw new UserServiceException("account is not active");
        }

        String profileUserId = accountProfileBindingMapper.findActiveProfileUserIdByAccountId(account.accountId());
        if (profileUserId == null || profileUserId.isBlank()) {
            throw new UserServiceException("active profile binding does not exist");
        }

        return issueToken(
                account.accountId(),
                account.username(),
                account.nickname() == null ? account.username() : account.nickname(),
                profileUserId
        );
    }

    @Transactional
    public AuthTokenVO refresh(RefreshTokenRequestDTO request) {
        String refreshToken = requiredTrim(request.refreshToken(), "refreshToken");
        AuthSessionRefreshRecord session = authSessionMapper.findRefreshSessionByRefreshTokenHash(
                sha256Hex(refreshToken)
        );

        if (session == null || session.revokedAt() != null) {
            throw new UserServiceException("invalid refresh token");
        }
        if (session.refreshExpiresAt().isBefore(LocalDateTime.now())) {
            throw new UserServiceException("refresh token expired");
        }
        if (!"active".equals(session.accountStatus())) {
            throw new UserServiceException("account is not active");
        }

        authSessionMapper.revokeSession(session.sessionId(), "refresh");
        tokenSessionStore.revokeSession(session.sessionId());
        return issueToken(
                session.accountId(),
                session.username(),
                session.nickname() == null ? session.username() : session.nickname(),
                session.profileUserId()
        );
    }

    public CurrentAccountVO currentAccount(String authorizationHeader) {
        AuthSessionCurrentAccountRecord session = validCurrentSession(authorizationHeader);

        return new CurrentAccountVO(
                session.accountId(),
                session.username(),
                session.nickname() == null ? session.username() : session.nickname(),
                session.profileUserId(),
                null
        );
    }

    @Transactional
    public void logout(String authorizationHeader) {
        AuthSessionCurrentAccountRecord session = validCurrentSession(authorizationHeader);
        authSessionMapper.revokeSession(session.sessionId(), "logout");
        tokenSessionStore.revokeSession(session.sessionId());
    }

    private AuthTokenVO issueToken(String accountId, String username, String nickname, String profileUserId) {
        String sessionId = prefixedId("authsess");
        String accessToken = randomToken();
        String refreshToken = randomToken();
        String accessTokenHash = sha256Hex(accessToken);
        String refreshTokenHash = sha256Hex(refreshToken);
        LocalDateTime now = LocalDateTime.now();
        LocalDateTime accessExpiresAt = now.plusSeconds(ACCESS_TOKEN_TTL_SECONDS);
        LocalDateTime refreshExpiresAt = now.plusSeconds(REFRESH_TOKEN_TTL_SECONDS);

        authSessionMapper.insertSession(
                sessionId,
                accountId,
                profileUserId,
                accessTokenHash,
                refreshTokenHash,
                accessExpiresAt,
                refreshExpiresAt,
                null,
                null
        );
        tokenSessionStore.save(new TokenSession(
                sessionId,
                accountId,
                username,
                nickname,
                profileUserId,
                accessTokenHash,
                refreshTokenHash,
                accessExpiresAt,
                refreshExpiresAt,
                "active"
        ));

        return new AuthTokenVO(
                accountId,
                username,
                nickname,
                profileUserId,
                null,
                accessToken,
                refreshToken,
                ACCESS_TOKEN_TTL_SECONDS
        );
    }

    private AuthSessionCurrentAccountRecord validCurrentSession(String authorizationHeader) {
        String accessToken = bearerToken(authorizationHeader);
        String accessTokenHash = sha256Hex(accessToken);
        TokenSession onlineSession = tokenSessionStore.findByAccessTokenHash(accessTokenHash)
                .orElse(null);
        if (onlineSession != null) {
            return validCurrentSession(onlineSession);
        }
        AuthSessionCurrentAccountRecord session = authSessionMapper.findCurrentAccountByAccessTokenHash(
                accessTokenHash
        );

        if (session == null || session.revokedAt() != null) {
            throw new UserServiceException("invalid access token");
        }
        if (session.accessExpiresAt().isBefore(LocalDateTime.now())) {
            throw new UserServiceException("access token expired");
        }
        if (!"active".equals(session.accountStatus())) {
            throw new UserServiceException("account is not active");
        }
        return session;
    }

    private AuthSessionCurrentAccountRecord validCurrentSession(TokenSession session) {
        if (session.accessExpiresAt().isBefore(LocalDateTime.now())) {
            throw new UserServiceException("access token expired");
        }
        if (!"active".equals(session.accountStatus())) {
            throw new UserServiceException("account is not active");
        }
        return new AuthSessionCurrentAccountRecord(
                session.sessionId(),
                session.accountId(),
                session.profileUserId(),
                session.accessExpiresAt(),
                null,
                session.username(),
                session.nickname(),
                session.accountStatus()
        );
    }

    private String bearerToken(String authorizationHeader) {
        String header = requiredTrim(authorizationHeader, "Authorization");
        if (!header.regionMatches(true, 0, "Bearer ", 0, 7)) {
            throw new UserServiceException("Authorization bearer token is required");
        }
        return requiredTrim(header.substring(7), "accessToken");
    }

    private String resolveProfileUserId(String bindStrategy, String requestedProfileUserId) {
        if ("selected".equals(bindStrategy)) {
            String profileUserId = requiredTrim(requestedProfileUserId, "profileUserId");
            if (!profileUserMapper.existsReviewUser(profileUserId)) {
                throw new UserServiceException("selected profile user does not exist");
            }
            return profileUserId;
        }

        String profileUserId = profileUserMapper.selectRandomReviewUserId();
        if (profileUserId == null || profileUserId.isBlank()) {
            throw new UserServiceException("no review users available for binding");
        }
        return profileUserId;
    }

    private String normalizedStrategy(String value) {
        String strategy = optionalTrim(value);
        if (strategy == null) {
            return DEFAULT_BIND_STRATEGY;
        }
        strategy = strategy.toLowerCase(Locale.ROOT);
        if (!"random".equals(strategy) && !"selected".equals(strategy)) {
            throw new UserServiceException("unsupported bind strategy");
        }
        return strategy;
    }

    private String requiredTrim(String value, String fieldName) {
        String trimmed = optionalTrim(value);
        if (trimmed == null) {
            throw new UserServiceException(fieldName + " is required");
        }
        return trimmed;
    }

    private String optionalTrim(String value) {
        if (value == null) {
            return null;
        }
        String trimmed = value.trim();
        return trimmed.isEmpty() ? null : trimmed;
    }

    private String prefixedId(String prefix) {
        return prefix + "_" + UUID.randomUUID().toString().replace("-", "");
    }

    private String randomToken() {
        byte[] bytes = new byte[32];
        secureRandom.nextBytes(bytes);
        return Base64.getUrlEncoder().withoutPadding().encodeToString(bytes);
    }

    private String sha256Hex(String value) {
        try {
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            return HexFormat.of().formatHex(digest.digest(value.getBytes(StandardCharsets.UTF_8)));
        } catch (NoSuchAlgorithmException exception) {
            throw new IllegalStateException("SHA-256 is not available", exception);
        }
    }
}
