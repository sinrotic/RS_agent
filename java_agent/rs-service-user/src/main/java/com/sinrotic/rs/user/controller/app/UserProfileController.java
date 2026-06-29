package com.sinrotic.rs.user.controller.app;

import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * Exposes profile-user summaries, profiles, and behavior endpoints for the frontend.
 *
 * Frontend-facing recommendation flows may display profile users here, but authenticated
 * recommendation flows should use the profileUserId bound to the current account.
 */
@RestController
@RequestMapping("/api/users")
public class UserProfileController {
}
