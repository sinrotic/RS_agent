package com.sinrotic.rs.payment.service;

import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;
import java.nio.ByteBuffer;
import java.nio.charset.StandardCharsets;
import java.security.GeneralSecurityException;
import java.util.HexFormat;

/** 模拟回调协议：各字段的UTF-8字节前加4字节大端长度，再计算HMAC-SHA256。 */
public final class MockPaymentCallbackSignature {
    private MockPaymentCallbackSignature() { }

    public static String sign(String secret, String provider, String transactionId, long orderId, long amount, String rawPayload) {
        try {
            Mac mac = Mac.getInstance("HmacSHA256");
            mac.init(new SecretKeySpec(secret.getBytes(StandardCharsets.UTF_8), "HmacSHA256"));
            for (String field : new String[]{provider, transactionId, Long.toString(orderId), Long.toString(amount), rawPayload}) {
                byte[] bytes = field.getBytes(StandardCharsets.UTF_8);
                mac.update(ByteBuffer.allocate(Integer.BYTES).putInt(bytes.length).array());
                mac.update(bytes);
            }
            return HexFormat.of().formatHex(mac.doFinal());
        } catch (GeneralSecurityException failure) {
            throw new PaymentServiceException("模拟支付回调验签不可用", failure);
        }
    }
}
