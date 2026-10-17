package com.sinrotic.rs.user.controller.internal;

import com.fasterxml.jackson.annotation.JsonProperty;
import com.sinrotic.rs.user.service.UserSessionService;
import com.sinrotic.rs.user.domain.vo.SessionActivityVO;
import org.springframework.web.bind.annotation.*;
import java.util.Map;
import java.util.List;

@RestController
@RequestMapping("/internal/sessions")
public class InternalUserSessionController {
    private final UserSessionService service;
    public InternalUserSessionController(UserSessionService service) { this.service = service; }

    @PostMapping("/{sessionId}/admit")
    public Map<String, Boolean> admit(@PathVariable String sessionId, @RequestBody Admission request) {
        service.admit(request.accountId(), request.profileUserId(), sessionId, request.query());
        return Map.of("accepted", true);
    }

    public record Admission(@JsonProperty("account_id") String accountId,
            @JsonProperty("profile_user_id") String profileUserId, String query) {}

    @PostMapping("/{sessionId}/touch")
    public SessionActivityVO touch(
            @PathVariable String sessionId, @RequestBody Admission request) {
        return service.touch(request.accountId(), request.profileUserId(), sessionId);
    }

    @GetMapping("/{sessionId}/activity")
    public SessionActivityVO activity(@PathVariable String sessionId,
            @RequestHeader("X-Account-Id") String accountId,
            @RequestHeader("X-Profile-User-Id") String profileUserId) {
        return service.activity(accountId, profileUserId, sessionId);
    }

    @GetMapping("/active")
    public List<SessionActivityVO> active(
            @RequestParam(defaultValue = "", name = "after_session_id") String afterSessionId,
            @RequestParam(defaultValue = "50") int limit) {
        return service.activeSessions(afterSessionId,limit);
    }
}
