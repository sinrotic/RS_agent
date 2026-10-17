package com.sinrotic.rs.seckill.service;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestClient;
import org.springframework.web.client.HttpClientErrorException;
import java.util.Arrays;

@Component
public class SeckillOrderClient {
    public record Offer(String skuId,String itemId,String itemTitle,long unitPrice) {}
    public record Result(long orderId,String status,String phase) {}
    private final RestClient client;
    public SeckillOrderClient(RestClient.Builder builder,@Value("${rs.order.base-url:http://localhost:8091}") String baseUrl) {
        var factory = new SimpleClientHttpRequestFactory(); factory.setConnectTimeout(2000); factory.setReadTimeout(3000);
        client = builder.baseUrl(baseUrl).requestFactory(factory).build();
    }
    public Offer offer(String itemId,String skuId) {
        Offer[] offers = client.get().uri(builder -> builder.path("/api/checkout/offers").queryParam("itemId",itemId).build())
                .retrieve().body(Offer[].class);
        return offers == null ? null : Arrays.stream(offers).filter(o -> o.skuId().equals(skuId)).findFirst().orElse(null);
    }
    public Result result(String eventId,String accountId) {
        try {
            return client.get().uri(builder -> builder.path("/internal/checkout/requests/{eventId}")
                    .queryParam("accountId",accountId).build(eventId)).retrieve().body(Result.class);
        } catch(HttpClientErrorException.NotFound absent) { return null; }
    }
}
