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

    public RestInventoryClient(
            RestClient.Builder restClientBuilder,
            @Value("${rs.inventory.base-url:http://localhost:8092}") String inventoryBaseUrl
    ) {
        this.restClient = restClientBuilder.baseUrl(inventoryBaseUrl).build();
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
}
