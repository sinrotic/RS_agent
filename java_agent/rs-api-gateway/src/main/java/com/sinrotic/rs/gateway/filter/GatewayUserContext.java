package com.sinrotic.rs.gateway.filter;

public record GatewayUserContext(
        String accountId,
        String profileUserId,
        String roles
) {
    public static GatewayUserContext anonymous() {
        return new GatewayUserContext(null, null, null);
    }
}
