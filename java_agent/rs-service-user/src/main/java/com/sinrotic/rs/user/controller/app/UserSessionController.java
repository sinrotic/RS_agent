package com.sinrotic.rs.user.controller.app;

import com.sinrotic.rs.user.domain.dto.CreateUserSessionRequestDTO;
import com.sinrotic.rs.user.domain.dto.EndUserSessionRequestDTO;
import com.sinrotic.rs.user.domain.vo.EndUserSessionVO;
import com.sinrotic.rs.user.domain.vo.UserSessionVO;
import com.sinrotic.rs.user.service.UserSessionService;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestParam;

/**
 * Manages user sessions for frontend and Agent interactions.
 *
 * A user session binds accountId, profileUserId, entry scene, and temporary preferences
 * generated during a conversation.
 */
@RestController
@RequestMapping("/api/sessions")
public class UserSessionController {

    private final UserSessionService service;

    public UserSessionController(UserSessionService service) {
        this.service = service;
    }

    @GetMapping
    public java.util.List<UserSessionVO> list(
            @RequestHeader("X-Account-Id") String accountId,
            @RequestHeader("X-Profile-User-Id") String profileUserId,
            @RequestParam(required = false) String entryScene,
            @RequestParam(defaultValue = "50") int limit) {
        return service.list(accountId, profileUserId, entryScene, limit);
    }

    @GetMapping("/{sessionId}")
    public UserSessionVO get(@RequestHeader("X-Account-Id") String accountId,
            @RequestHeader("X-Profile-User-Id") String profileUserId, @PathVariable String sessionId) {
        return service.get(accountId, profileUserId, sessionId);
    }

    @PostMapping
    public UserSessionVO create(
            @RequestHeader("X-Account-Id") String accountId,
            @RequestHeader("X-Profile-User-Id") String profileUserId,
            @RequestBody(required = false) CreateUserSessionRequestDTO request
    ) {
        return service.create(accountId, profileUserId, request);
    }

    @PostMapping("/end")
    public EndUserSessionVO end(
            @RequestHeader("X-Account-Id") String accountId,
            @RequestHeader("X-Profile-User-Id") String profileUserId,
            @RequestBody EndUserSessionRequestDTO request
    ) {
        return service.end(accountId, profileUserId, request);
    }
}
