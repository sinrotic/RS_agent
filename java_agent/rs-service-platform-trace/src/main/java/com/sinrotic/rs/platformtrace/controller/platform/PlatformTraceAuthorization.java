package com.sinrotic.rs.platformtrace.controller.platform;

import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.ModelAttribute;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import org.springframework.web.server.ResponseStatusException;

import java.util.Arrays;
import java.util.Locale;

/** Gateway strips client-supplied roles; only platform readers can invoke the internal observer client. */
@RestControllerAdvice(basePackages = "com.sinrotic.rs.platformtrace.controller.platform")
public class PlatformTraceAuthorization {
    @ModelAttribute
    public void requireReader(@RequestHeader(value = "X-User-Roles", required = false) String roles) {
        if (roles == null || Arrays.stream(roles.split("[,\\s]+"))
                .map(role -> role.toUpperCase(Locale.ROOT))
                .noneMatch(role -> role.equals("ADMIN") || role.equals("OBSERVER"))) {
            throw new ResponseStatusException(HttpStatus.FORBIDDEN, "Insufficient platform role");
        }
    }
}
