package com.sinrotic.rs.user.controller.internal;

import com.sinrotic.rs.user.service.UserSessionService;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import org.springframework.web.server.ResponseStatusException;
import static org.mockito.Mockito.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

class InternalUserSessionControllerTest {
    @Test
    void internalActivityEndpointsPreserveOwnerBindingAndExposeUtcExpiry() throws Exception {
        var service = mock(UserSessionService.class);
        var activity = new com.sinrotic.rs.user.domain.vo.SessionActivityVO("session","account","profile","ACTIVE",
                java.time.Instant.parse("2026-10-12T00:00:00Z"));
        when(service.touch("account","profile","session")).thenReturn(activity);
        when(service.activity("account","profile","session")).thenReturn(activity);
        when(service.activeSessions("",50)).thenReturn(java.util.List.of(activity));
        var mvc = MockMvcBuilders.standaloneSetup(new InternalUserSessionController(service)).build();
        mvc.perform(post("/internal/sessions/session/touch").contentType(MediaType.APPLICATION_JSON)
                .content("{\"account_id\":\"account\",\"profile_user_id\":\"profile\"}"))
                .andExpect(status().isOk()).andExpect(jsonPath("$.expiresAt").value("2026-10-12T00:00:00Z"));
        verify(service).touch("account","profile","session");
        mvc.perform(get("/internal/sessions/session/activity").header("X-Account-Id","account").header("X-Profile-User-Id","profile"))
                .andExpect(status().isOk()).andExpect(jsonPath("$.sessionId").value("session"));
        verify(service).activity("account","profile","session");
        mvc.perform(get("/internal/sessions/active")).andExpect(status().isOk())
                .andExpect(jsonPath("$[0].accountId").value("account"));
        verify(service).activeSessions("",50);
        when(service.touch("account","profile","session")).thenThrow(new ResponseStatusException(HttpStatus.GONE));
        mvc.perform(post("/internal/sessions/session/touch").contentType(MediaType.APPLICATION_JSON)
                .content("{\"account_id\":\"account\",\"profile_user_id\":\"profile\"}"))
                .andExpect(status().isGone());
    }
    @Test
    void internalAdmissionBindsTrustedAccountProfileAndQueryAndPropagatesEndedStatus() throws Exception {
        var service = mock(UserSessionService.class);
        var mvc = MockMvcBuilders.standaloneSetup(new InternalUserSessionController(service)).build();
        String request = "{\"account_id\":\"account\",\"profile_user_id\":\"profile\",\"query\":\"预算五百\"}";
        mvc.perform(post("/internal/sessions/session/admit").contentType(MediaType.APPLICATION_JSON).content(request))
                .andExpect(status().isOk()).andExpect(jsonPath("$.accepted").value(true));
        verify(service).admit("account", "profile", "session", "预算五百");
        doThrow(new ResponseStatusException(HttpStatus.GONE)).when(service).admit("account", "profile", "session", "预算五百");
        mvc.perform(post("/internal/sessions/session/admit").contentType(MediaType.APPLICATION_JSON).content(request))
                .andExpect(status().isGone());
    }
}
