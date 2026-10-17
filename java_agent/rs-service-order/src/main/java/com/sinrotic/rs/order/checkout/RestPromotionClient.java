package com.sinrotic.rs.order.checkout;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestClient;
import java.util.Map;

@Component
public class RestPromotionClient implements PromotionClient {
    private final RestClient client;
    public record LockResult(long discountAmount) {}
    public RestPromotionClient(RestClient.Builder builder, @Value("${rs.promotion.base-url:http://localhost:8095}") String baseUrl) {
        var factory = new SimpleClientHttpRequestFactory();
        factory.setConnectTimeout(2000);
        factory.setReadTimeout(3000);
        client = builder.baseUrl(baseUrl).requestFactory(factory).build();
    }
    public long lock(long orderId, String couponId, String accountId, String itemId, long originalAmount) {
        var result = client.post().uri("/internal/promotions/reservations")
                .body(Map.of("orderId",orderId,"couponId",couponId,"accountId",accountId,"itemId",itemId,"originalAmount",originalAmount))
                .retrieve().body(LockResult.class);
        if (result == null) throw new IllegalStateException("锁券结果为空，保持未知结果并重试");
        return result.discountAmount();
    }
    public void confirm(long orderId, String couponId) { finish(orderId, couponId, "confirm"); }
    public void release(long orderId, String couponId) { finish(orderId, couponId, "release"); }
    public void cancel(long orderId, String couponId, String accountId, String itemId, long originalAmount) {
        client.post().uri("/internal/promotions/reservations/cancel")
                .body(Map.of("orderId",orderId,"couponId",couponId,"accountId",accountId,"itemId",itemId,"originalAmount",originalAmount))
                .retrieve().toBodilessEntity();
    }
    private void finish(long orderId, String couponId, String action) {
        client.post().uri("/internal/promotions/reservations/{orderId}/{action}",orderId,action)
                .body(Map.of("couponId",couponId)).retrieve().toBodilessEntity();
    }
}
