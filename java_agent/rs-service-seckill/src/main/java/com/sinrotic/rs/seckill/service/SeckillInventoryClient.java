package com.sinrotic.rs.seckill.service;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestClient;

@Component
public class SeckillInventoryClient {
    private final RestClient client;
    public record Allocation(String activityId,String skuId,int quantity) {}
    public SeckillInventoryClient(RestClient.Builder builder,@Value("${rs.inventory.base-url:http://localhost:8092}") String url) {
        var factory=new org.springframework.http.client.SimpleClientHttpRequestFactory();factory.setConnectTimeout(2000);factory.setReadTimeout(3000);
        client=builder.baseUrl(url).requestFactory(factory).build();
    }
    public void allocate(String id,String sku,int quantity) {
        client.post().uri("/internal/inventory/activities/allocate").body(new Allocation(id,sku,quantity)).retrieve().toBodilessEntity();
    }
    public void close(String id) {client.post().uri("/internal/inventory/activities/{id}/close",id).retrieve().toBodilessEntity();}
}
