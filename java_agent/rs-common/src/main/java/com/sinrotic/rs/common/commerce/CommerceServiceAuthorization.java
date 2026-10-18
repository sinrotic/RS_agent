package com.sinrotic.rs.common.commerce;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import org.springframework.http.HttpStatus;
import org.springframework.web.server.ResponseStatusException;
public final class CommerceServiceAuthorization {
    public static void require(String header,String secret) {
        if(secret==null || secret.length()<32 || header==null || !header.startsWith("Bearer ")
                || !MessageDigest.isEqual(secret.getBytes(StandardCharsets.UTF_8),header.substring(7).getBytes(StandardCharsets.UTF_8)))
            throw new ResponseStatusException(HttpStatus.UNAUTHORIZED,"需要有效的交易服务凭证");
    }
    private CommerceServiceAuthorization() {}
}
