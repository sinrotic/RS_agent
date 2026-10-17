package com.sinrotic.rs.payment.client;

import com.sinrotic.rs.payment.client.dto.OrderPaidRequestDTO;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestClient;

@Component
public class RestOrderClient implements OrderClient {

    private final RestClient restClient;
    private final com.sinrotic.rs.payment.mapper.PaymentOrderMapper paymentOrderMapper;

    public RestOrderClient(
            RestClient.Builder restClientBuilder,
            com.sinrotic.rs.payment.mapper.PaymentOrderMapper paymentOrderMapper,
            @Value("${rs.order.base-url:http://localhost:8091}") String orderBaseUrl
    ) {
        var factory = new org.springframework.http.client.SimpleClientHttpRequestFactory();
        factory.setConnectTimeout(2000);
        factory.setReadTimeout(3000);
        this.restClient = restClientBuilder.baseUrl(orderBaseUrl).requestFactory(factory).build();
        this.paymentOrderMapper = paymentOrderMapper;
    }

    @Override
    public PaymentQuote paymentQuote(Long orderId, String accountId) {
        return restClient.get().uri(builder -> builder.path("/internal/checkout/orders/{orderId}/payment-quote")
                .queryParam("accountId", accountId).build(orderId)).retrieve().body(PaymentQuote.class);
    }

    @Override
    public void markPaid(Long orderId, String provider, String providerTransactionId) {
        var payment = paymentOrderMapper.findByOrderId(orderId);
        if (payment == null || !"PAID".equals(payment.getStatus()) || !provider.equals(payment.getProvider())
                || !providerTransactionId.equals(payment.getProviderTransactionId())) {
            throw new IllegalStateException("支付持久记录与通知不匹配");
        }
        restClient.post()
                .uri("/internal/orders/{orderId}/paid", orderId)
                .body(new OrderPaidRequestDTO(
                        "payment:" + provider + ":" + providerTransactionId,
                        orderId,
                        provider,
                        providerTransactionId,
                        payment.getAmount()
                ))
                .retrieve()
                .toBodilessEntity();
    }
}
