package com.sinrotic.rs.gateway.filter;

import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.stereotype.Service;
import reactor.core.publisher.Mono;

@Service
@ConditionalOnProperty(prefix = "rs.gateway.auth", name = "token-validation", havingValue = "presence")
public class PresenceGatewayTokenValidator implements GatewayTokenValidator {

    @Override
    public Mono<GatewayUserContext> validate(String accessToken) {
        if (accessToken == null || accessToken.isBlank()) {
            return Mono.empty();
        }
        return Mono.just(GatewayUserContext.anonymous());
    }
}
