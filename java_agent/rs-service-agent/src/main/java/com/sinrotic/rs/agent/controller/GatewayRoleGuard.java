package com.sinrotic.rs.agent.controller;

import org.springframework.http.HttpStatus;
import org.springframework.web.server.ResponseStatusException;

import java.util.Arrays;
import java.util.Set;
import java.util.stream.Collectors;

public final class GatewayRoleGuard {

    private GatewayRoleGuard() {
    }

    public static void requireAny(String roleHeader, String... allowedRoles) {
        Set<String> roles = parseRoles(roleHeader);
        boolean allowed = Arrays.stream(allowedRoles).anyMatch(roles::contains);
        if (!allowed) {
            throw new ResponseStatusException(HttpStatus.FORBIDDEN, "Insufficient platform role");
        }
    }

    private static Set<String> parseRoles(String roleHeader) {
        if (roleHeader == null || roleHeader.isBlank()) {
            return Set.of();
        }
        return Arrays.stream(roleHeader.split("[,\\s]+"))
                .map(String::trim)
                .map(String::toUpperCase)
                .filter(value -> !value.isEmpty())
                .collect(Collectors.toUnmodifiableSet());
    }
}
