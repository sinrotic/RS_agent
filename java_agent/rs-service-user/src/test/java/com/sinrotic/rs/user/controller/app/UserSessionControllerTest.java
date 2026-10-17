package com.sinrotic.rs.user.controller.app;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.sinrotic.rs.user.domain.dto.CreateUserSessionRequestDTO;
import com.sinrotic.rs.user.domain.dto.EndUserSessionRequestDTO;
import com.sinrotic.rs.user.domain.vo.EndUserSessionVO;
import com.sinrotic.rs.user.domain.vo.UserSessionVO;
import com.sinrotic.rs.user.service.UserSessionService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import java.time.LocalDateTime;
import java.util.Map;

import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

class UserSessionControllerTest {

    private final ObjectMapper objectMapper = new ObjectMapper();

    private UserSessionService service;

    private MockMvc mockMvc;

    @BeforeEach
    void setUp() {
        service = mock(UserSessionService.class);
        mockMvc = MockMvcBuilders.standaloneSetup(new UserSessionController(service)).build();
    }

    @Test
    void createsSessionUsingGatewayIdentity() throws Exception {
        when(service.create("acc_001", "profile_001", new CreateUserSessionRequestDTO("mall")))
                .thenReturn(new UserSessionVO(
                        "sess_001", "acc_001", "profile_001", "mall", "ACTIVE", Map.of(),
                        LocalDateTime.of(2026, 8, 4, 20, 0),
                        LocalDateTime.of(2026, 8, 4, 20, 0)
                ));

        mockMvc.perform(post("/api/sessions")
                        .header("X-Account-Id", "acc_001")
                        .header("X-Profile-User-Id", "profile_001")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(Map.of(
                                "entryScene", "mall",
                                "profileUserId", "spoofed"
                        ))))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.sessionId").value("sess_001"))
                .andExpect(jsonPath("$.profileUserId").value("profile_001"));
    }

    @Test
    void endsSessionUsingGatewayIdentity() throws Exception {
        EndUserSessionRequestDTO request = new EndUserSessionRequestDTO("sess_001", "manual");
        when(service.end("acc_001", "profile_001", request))
                .thenReturn(new EndUserSessionVO("sess_001", "ENDED", 0, null));

        mockMvc.perform(post("/api/sessions/end")
                        .header("X-Account-Id", "acc_001")
                        .header("X-Profile-User-Id", "profile_001")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(request)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.sessionId").value("sess_001"))
                .andExpect(jsonPath("$.status").value("ENDED"));

        verify(service).end("acc_001", "profile_001", request);
    }

    @Test
    void rejectsMissingGatewayIdentity() throws Exception {
        mockMvc.perform(post("/api/sessions")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{}"))
                .andExpect(status().isBadRequest());
    }
}
