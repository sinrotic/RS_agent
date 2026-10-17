package com.sinrotic.rs.user.service;

import com.sinrotic.rs.user.domain.dto.CreateUserSessionRequestDTO;
import com.sinrotic.rs.user.domain.dto.EndUserSessionRequestDTO;
import com.sinrotic.rs.user.domain.entity.UserSession;
import com.sinrotic.rs.user.domain.vo.EndUserSessionVO;
import com.sinrotic.rs.user.domain.vo.UserSessionVO;
import com.sinrotic.rs.user.mapper.UserSessionMapper;
import org.junit.jupiter.api.Test;
import org.springframework.web.server.ResponseStatusException;

import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.argThat;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class UserSessionServiceTest {

    @Test
    void activeChatRefreshesActivityWithBothOwnerKeysAndCutoff() {
        var now = java.time.LocalDateTime.of(2026, 8, 4, 12, 0);
        when(mapper.findBySessionId("sess_fixed")).thenReturn(session("ACTIVE", "acc_001", "profile_001"));
        when(mapper.admitSession("sess_fixed", "acc_001", "profile_001", now, now.minusHours(24), "新需求")).thenReturn(1);
        service.admit("acc_001", "profile_001", "sess_fixed", "新需求");
        verify(mapper).admitSession("sess_fixed", "acc_001", "profile_001", now, now.minusHours(24), "新需求");
    }

    @Test
    void endedOrConcurrentlyEndedSessionsCannotBeRevivedByChat() {
        when(mapper.findBySessionId("sess_fixed")).thenReturn(session("ENDED", "acc_001", "profile_001"));
        assertThatThrownBy(() -> service.admit("acc_001", "profile_001", "sess_fixed", "继续")).hasMessageContaining("410");
        when(mapper.findBySessionId("sess_fixed")).thenReturn(session("ACTIVE", "acc_001", "profile_001"));
        // The conditional update returns zero if another request ended the Session after the read.
        assertThatThrownBy(() -> service.admit("acc_001", "profile_001", "sess_fixed", "继续")).hasMessageContaining("410");
    }

    @Test
    void expirationDoesNotOverrideConcurrentActivityRefresh() {
        var old = session("ACTIVE", "acc_001", "profile_001");
        old.setLastActiveAt(java.time.LocalDateTime.of(2026, 8, 3, 12, 0));
        when(mapper.findBySessionId("sess_fixed")).thenReturn(old, session("ACTIVE", "acc_001", "profile_001"));
        assertThat(service.get("acc_001", "profile_001", "sess_fixed").status()).isEqualTo("ACTIVE");
    }

    @Test
    void chatAdmissionHidesAnotherAccountsSession() {
        when(mapper.findBySessionId("sess_fixed")).thenReturn(session("ACTIVE", "acc_001", "profile_001"));
        assertThatThrownBy(() -> service.admit("other", "profile_001", "sess_fixed", "继续")).hasMessageContaining("404");
        org.mockito.Mockito.verify(mapper, org.mockito.Mockito.never()).admitSession(
                org.mockito.ArgumentMatchers.anyString(), org.mockito.ArgumentMatchers.anyString(), org.mockito.ArgumentMatchers.anyString(),
                org.mockito.ArgumentMatchers.any(), org.mockito.ArgumentMatchers.any(), org.mockito.ArgumentMatchers.anyString());
    }

    @Test
    void inactiveSessionIsEndedAtTheTwentyFourHourBoundary() {
        var old = session("ACTIVE", "acc_001", "profile_001");
        old.setLastActiveAt(java.time.LocalDateTime.of(2026, 8, 3, 12, 0));
        when(mapper.findBySessionId("sess_fixed")).thenReturn(old);
        when(mapper.expireOwnedSession("sess_fixed", "acc_001", "profile_001", java.time.LocalDateTime.of(2026, 8, 3, 12, 0))).thenReturn(1);
        assertThat(service.get("acc_001", "profile_001", "sess_fixed").status()).isEqualTo("ENDED");
    }

    @Test
    void historyLookupRequiresBothAccountAndProfileAndListingIsBounded() {
        var own = session("ACTIVE", "acc_001", "profile_001");
        when(mapper.findBySessionId("sess_fixed")).thenReturn(own);
        assertThat(service.get("acc_001", "profile_001", "sess_fixed").sessionId()).isEqualTo("sess_fixed");
        assertThatThrownBy(() -> service.get("other", "profile_001", "sess_fixed")).hasMessageContaining("404");
        assertThatThrownBy(() -> service.get("acc_001", "other", "sess_fixed")).hasMessageContaining("404");
        when(mapper.findByOwner("acc_001", "profile_001", "agent_chat", 50)).thenReturn(java.util.List.of(own));
        assertThat(service.list("acc_001", "profile_001", "agent_chat", 50)).hasSize(1);
        assertThatThrownBy(() -> service.list("acc_001", "profile_001", null, 101)).hasMessageContaining("400");
    }

    private final UserSessionMapper mapper = mock(UserSessionMapper.class);

    private final UserSessionService service = new UserSessionService(
            mapper,
            Clock.fixed(Instant.parse("2026-08-04T12:00:00Z"), ZoneOffset.UTC),
            () -> "sess_fixed"
    );

    @Test
    void createsSessionFromTrustedIdentity() {
        UserSessionVO session = service.create(
                "acc_001",
                "profile_001",
                new CreateUserSessionRequestDTO("agent_chat")
        );

        assertThat(session.sessionId()).isEqualTo("sess_fixed");
        assertThat(session.accountId()).isEqualTo("acc_001");
        assertThat(session.profileUserId()).isEqualTo("profile_001");
        assertThat(session.status()).isEqualTo("ACTIVE");
        verify(mapper).insert(argThat(value ->
                "sess_fixed".equals(value.getSessionId())
                        && "acc_001".equals(value.getAccountId())
                        && "profile_001".equals(value.getProfileUserId())
        ));
    }

    @Test
    void endingSessionIsIdempotentForOwner() {
        UserSession existing = session("ACTIVE", "acc_001", "profile_001");
        when(mapper.findBySessionId("sess_fixed")).thenReturn(existing, session("ENDED", "acc_001", "profile_001"));

        EndUserSessionVO first = service.end(
                "acc_001",
                "profile_001",
                new EndUserSessionRequestDTO("sess_fixed", "manual")
        );
        EndUserSessionVO second = service.end(
                "acc_001",
                "profile_001",
                new EndUserSessionRequestDTO("sess_fixed", "manual")
        );

        assertThat(first.status()).isEqualTo("ENDED");
        assertThat(second.status()).isEqualTo("ENDED");
        verify(mapper).endSession("sess_fixed", "manual");
    }

    @Test
    void hidesSessionFromDifferentOwner() {
        when(mapper.findBySessionId("sess_fixed"))
                .thenReturn(session("ACTIVE", "acc_owner", "profile_owner"));

        assertThatThrownBy(() -> service.end(
                "acc_attacker",
                "profile_attacker",
                new EndUserSessionRequestDTO("sess_fixed", "manual")
        ))
                .isInstanceOf(ResponseStatusException.class)
                .hasMessageContaining("404");
    }

    private UserSession session(String status, String accountId, String profileUserId) {
        UserSession session = new UserSession();
        session.setSessionId("sess_fixed");
        session.setAccountId(accountId);
        session.setProfileUserId(profileUserId);
        session.setEntryScene("agent_chat");
        session.setStatus(status);
        session.setStartedAt(java.time.LocalDateTime.of(2026, 8, 4, 20, 0));
        session.setLastActiveAt(java.time.LocalDateTime.of(2026, 8, 4, 20, 0));
        return session;
    }
}
