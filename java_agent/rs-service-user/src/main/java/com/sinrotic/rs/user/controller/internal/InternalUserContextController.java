package com.sinrotic.rs.user.controller.internal;

import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * Provides user context to internal services such as rs-service-recommend and rs-service-agent.
 *
 * Internal endpoints should return stable service-to-service models, not frontend view models.
 */
@RestController
@RequestMapping("/internal")
public class InternalUserContextController {
    private final com.sinrotic.rs.user.mapper.ProfileUserMapper profiles;

    public InternalUserContextController(com.sinrotic.rs.user.mapper.ProfileUserMapper profiles) {
        this.profiles = profiles;
    }

    @org.springframework.web.bind.annotation.PostMapping("/users/context/positive-history")
    public java.util.List<String> positiveHistory(@org.springframework.web.bind.annotation.RequestBody HistoryRequest request) {
        if (request.profileUserId() == null || request.profileUserId().isBlank()) {
            throw new org.springframework.web.server.ResponseStatusException(org.springframework.http.HttpStatus.BAD_REQUEST);
        }
        return profiles.selectRecentPositiveItemIds(request.profileUserId(), Math.max(1, Math.min(100, request.limit())));
    }

    public record HistoryRequest(@com.fasterxml.jackson.annotation.JsonProperty("profile_user_id") String profileUserId, int limit) { }
}
