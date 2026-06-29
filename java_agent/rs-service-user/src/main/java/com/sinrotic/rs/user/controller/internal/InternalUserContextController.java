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
}
