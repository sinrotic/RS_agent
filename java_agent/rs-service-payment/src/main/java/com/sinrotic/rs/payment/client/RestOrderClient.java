package com.sinrotic.rs.payment.client;

import com.sinrotic.rs.payment.client.dto.OrderPaidRequestDTO;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestClient;

@Component
public class RestOrderClient implements OrderClient {

    private final RestClient restClient;

    public RestOrderClient(
            RestClient.Builder restClientBuilder,
            @Value("${rs.order.base-url:http://localhost:8091}") String orderBaseUrl
    ) {
        this.restClient = restClientBuilder.baseUrl(orderBaseUrl).build();
    }

    @Override
    public void markPaid(Long orderId, String provider, String providerTransactionId) {
        restClient.post()
                .uri("/internal/orders/{orderId}/paid", orderId)
                .body(new OrderPaidRequestDTO(
                        "payment:" + provider + ":" + providerTransactionId,
                        orderId,
                        provider,
                        providerTransactionId
                ))
                .retrieve()
                .toBodilessEntity();
    }
}
