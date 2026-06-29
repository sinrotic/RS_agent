package com.sinrotic.rs.user.controller.app;

import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * Manages user sessions for frontend and Agent interactions.
 *
 * A user session binds accountId, profileUserId, entry scene, and temporary preferences
 * generated during a conversation.
 */
@RestController
@RequestMapping("/api/sessions")
public class UserSessionController {
}
