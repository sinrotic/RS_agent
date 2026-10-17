package com.sinrotic.rs.gateway.filter;

import reactor.core.publisher.Mono;

@FunctionalInterface
public interface GatewayTokenValidator {

    Mono<GatewayUserContext> validate(String accessToken);
}
