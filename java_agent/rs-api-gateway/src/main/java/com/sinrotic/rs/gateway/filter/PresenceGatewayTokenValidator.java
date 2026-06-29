package com.sinrotic.rs.gateway.filter;

import org.springframework.stereotype.Service;

import java.util.Optional;

@Service
public class PresenceGatewayTokenValidator implements GatewayTokenValidator {

    @Override
    public Optional<GatewayUserContext> validate(String accessToken) {
        if (accessToken == null || accessToken.isBlank()) {
            return Optional.empty();
        }
        return Optional.of(GatewayUserContext.anonymous());
    }
}
