package com.sinrotic.rs.order.client;

import com.sinrotic.rs.order.client.dto.InventoryConfirmRequestDTO;
import com.sinrotic.rs.order.client.dto.InventoryLockRequestDTO;
import com.sinrotic.rs.order.client.dto.InventoryReleaseRequestDTO;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestClient;

@Component
public class RestInventoryClient implements InventoryClient {

    private final RestClient restClient;
    @Override public void refund(String requestId,Long orderId,String skuId,Integer quantity) {
        restClient.post().uri("/internal/inventory/refund").body(new InventoryReleaseRequestDTO(requestId,orderId,skuId,quantity)).retrieve().toBodilessEntity();
    }
    public record ActivityMovement(String activityId,long orderId,String skuId,int quantity) {}
    @Override
    public void activity(String action,String activityId,Long orderId,String skuId,Integer quantity) {
        restClient.post().uri("/internal/inventory/activities/movements/{action}",action)
                .body(new ActivityMovement(activityId,orderId,skuId,quantity)).retrieve().toBodilessEntity();
    }

    public RestInventoryClient(
            RestClient.Builder restClientBuilder,
            @Value("${rs.inventory.base-url:http://localhost:8092}") String inventoryBaseUrl
    ) {
        var factory = new org.springframework.http.client.SimpleClientHttpRequestFactory();
        factory.setConnectTimeout(2000);
        factory.setReadTimeout(3000);
        this.restClient = restClientBuilder.baseUrl(inventoryBaseUrl).requestFactory(factory).build();
    }

    @Override
    public void lock(String requestId, Long orderId, String skuId, Integer quantity) {
        restClient.post()
                .uri("/internal/inventory/lock")
                .body(new InventoryLockRequestDTO(requestId, orderId, skuId, quantity))
                .retrieve()
                .toBodilessEntity();
    }

    @Override
    public void confirm(String requestId, Long orderId, String skuId, Integer quantity) {
        restClient.post()
                .uri("/internal/inventory/confirm-deduct")
                .body(new InventoryConfirmRequestDTO(requestId, orderId, skuId, quantity))
                .retrieve()
                .toBodilessEntity();
    }

    @Override
    public void release(String requestId, Long orderId, String skuId, Integer quantity) {
        restClient.post()
                .uri("/internal/inventory/release")
                .body(new InventoryReleaseRequestDTO(requestId, orderId, skuId, quantity))
                .retrieve()
                .toBodilessEntity();
    }

    @Override
    public void cancel(String requestId, Long orderId, String skuId, Integer quantity) {
        restClient.post().uri("/internal/inventory/cancel")
                .body(new InventoryReleaseRequestDTO(requestId,orderId,skuId,quantity))
                .retrieve().toBodilessEntity();
    }
}
