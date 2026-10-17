package com.sinrotic.rs.user.service;

import com.sinrotic.rs.user.domain.dto.CreateUserSessionRequestDTO;
import com.sinrotic.rs.user.domain.dto.EndUserSessionRequestDTO;
import com.sinrotic.rs.user.domain.entity.UserSession;
import com.sinrotic.rs.user.domain.vo.EndUserSessionVO;
import com.sinrotic.rs.user.domain.vo.UserSessionVO;
import com.sinrotic.rs.user.domain.vo.SessionActivityVO;
import com.sinrotic.rs.user.mapper.UserSessionMapper;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.web.server.ResponseStatusException;

import java.time.Clock;
import java.time.Duration;
import java.time.LocalDateTime;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.function.Supplier;

/**
 * Creates user sessions and maintains temporary preferences for a single conversation.
 */
@Service
public class UserSessionService {

    private final UserSessionMapper mapper;

    private final Clock clock;

    private final Supplier<String> sessionIdSupplier;

    @Autowired
    public UserSessionService(UserSessionMapper mapper) {
        this(mapper, Clock.systemDefaultZone(), () -> "sess_" + UUID.randomUUID().toString().replace("-", ""));
    }

    UserSessionService(UserSessionMapper mapper, Clock clock, Supplier<String> sessionIdSupplier) {
        this.mapper = mapper;
        this.clock = clock;
        this.sessionIdSupplier = sessionIdSupplier;
    }

    public UserSessionVO create(
            String accountId,
            String profileUserId,
            CreateUserSessionRequestDTO request
    ) {
        requireIdentity(accountId, profileUserId);
        LocalDateTime now = LocalDateTime.now(clock);
        UserSession session = new UserSession();
        session.setSessionId(sessionIdSupplier.get());
        session.setAccountId(accountId);
        session.setProfileUserId(profileUserId);
        session.setEntryScene(resolveEntryScene(request));
        session.setActivePreferencesJson("{}");
        session.setLastUserQuery(null);
        session.setStartedAt(now);
        session.setLastActiveAt(now);
        session.setStatus("ACTIVE");
        mapper.insert(session);
        return toView(session);
    }

    public EndUserSessionVO end(
            String accountId,
            String profileUserId,
            EndUserSessionRequestDTO request
    ) {
        requireIdentity(accountId, profileUserId);
        if (request == null || request.sessionId() == null || request.sessionId().isBlank()) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "sessionId is required");
        }
        UserSession session = mapper.findBySessionId(request.sessionId());
        if (session == null
                || !accountId.equals(session.getAccountId())
                || !profileUserId.equals(session.getProfileUserId())) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "Session was not found");
        }
        if ("ACTIVE".equals(session.getStatus())) {
            mapper.endSession(session.getSessionId(), request.resolvedReason());
        }
        return new EndUserSessionVO(session.getSessionId(), "ENDED", 0, null);
    }

    public java.util.List<UserSessionVO> list(String accountId, String profileUserId, String entryScene, int limit) {
        requireIdentity(accountId, profileUserId);
        if (limit < 1 || limit > 100) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "limit must be between 1 and 100");
        }
        return mapper.findByOwner(accountId, profileUserId, entryScene, limit).stream()
                .map(this::expireIfInactive).map(this::toView).toList();
    }

    public UserSessionVO get(String accountId, String profileUserId, String sessionId) {
        requireIdentity(accountId, profileUserId);
        UserSession session = mapper.findBySessionId(sessionId);
        if (session == null || !accountId.equals(session.getAccountId()) || !profileUserId.equals(session.getProfileUserId())) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "Session was not found");
        }
        return toView(expireIfInactive(session));
    }

    public void admit(String accountId, String profileUserId, String sessionId, String query) {
        UserSessionVO owned = get(accountId, profileUserId, sessionId);
        if (!"ACTIVE".equals(owned.status())) {
            throw new ResponseStatusException(HttpStatus.GONE, "Session has ended");
        }
        LocalDateTime now = LocalDateTime.now(clock);
        if (mapper.admitSession(sessionId, accountId, profileUserId, now, now.minusHours(24), query) != 1) {
            throw new ResponseStatusException(HttpStatus.GONE, "Session has ended");
        }
    }

    public SessionActivityVO touch(
            String accountId, String profileUserId, String sessionId) {
        var owned = get(accountId, profileUserId, sessionId);
        if (!"ACTIVE".equals(owned.status())) {
            throw new ResponseStatusException(HttpStatus.GONE, "Session has ended");
        }
        LocalDateTime now = LocalDateTime.now(clock);
        if (mapper.touchSession(sessionId, accountId, profileUserId, now, now.minusHours(24)) != 1) {
            throw new ResponseStatusException(HttpStatus.GONE, "Session has ended");
        }
        return activity(accountId, profileUserId, sessionId);
    }

    public SessionActivityVO activity(
            String accountId, String profileUserId, String sessionId) {
        var session = get(accountId, profileUserId, sessionId);
        return new SessionActivityVO(session.sessionId(), session.accountId(),
                session.profileUserId(), session.status(), session.lastActiveAt() == null ? null
                : session.lastActiveAt().atZone(clock.getZone()).toInstant().plus(Duration.ofHours(24)));
    }

    public List<SessionActivityVO> activeSessions(String afterSessionId, int limit) {
        if (limit < 1 || limit > 100) throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "limit must be between 1 and 100");
        return mapper.findActiveSessions(afterSessionId,LocalDateTime.now(clock).minusHours(24),limit).stream()
                .map(session -> new SessionActivityVO(session.getSessionId(),session.getAccountId(),
                    session.getProfileUserId(),session.getStatus(),session.getLastActiveAt().atZone(clock.getZone()).toInstant()
                        .plus(Duration.ofHours(24)))).toList();
    }

    private UserSession expireIfInactive(UserSession session) {
        LocalDateTime cutoff = LocalDateTime.now(clock).minusHours(24);
        if ("ACTIVE".equals(session.getStatus()) && session.getLastActiveAt() != null
                && !session.getLastActiveAt().isAfter(cutoff)) {
            int expired = mapper.expireOwnedSession(session.getSessionId(), session.getAccountId(), session.getProfileUserId(), cutoff);
            if (expired == 0) {
                UserSession latest = mapper.findBySessionId(session.getSessionId());
                if (latest != null && latest.getLastActiveAt() != null && latest.getLastActiveAt().isAfter(cutoff)) return latest;
            }
            session.setStatus("ENDED");
        }
        return session;
    }

    private void requireIdentity(String accountId, String profileUserId) {
        if (accountId == null || accountId.isBlank() || profileUserId == null || profileUserId.isBlank()) {
            throw new ResponseStatusException(HttpStatus.UNAUTHORIZED, "Trusted user identity is required");
        }
    }

    private String resolveEntryScene(CreateUserSessionRequestDTO request) {
        if (request == null || request.entryScene() == null || request.entryScene().isBlank()) {
            return "web";
        }
        return request.entryScene().trim();
    }

    private UserSessionVO toView(UserSession session) {
        return new UserSessionVO(
                session.getSessionId(),
                session.getAccountId(),
                session.getProfileUserId(),
                session.getEntryScene(),
                session.getStatus(),
                Map.of(),
                session.getStartedAt(),
                session.getLastActiveAt()
        );
    }
}
