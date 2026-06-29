package com.sinrotic.rs.gateway.filter;

import java.util.Optional;

@FunctionalInterface
public interface GatewayTokenValidator {

    Optional<GatewayUserContext> validate(String accessToken);
}
