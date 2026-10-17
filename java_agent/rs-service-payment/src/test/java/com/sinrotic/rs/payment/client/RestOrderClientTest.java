package com.sinrotic.rs.payment.client;

import com.sinrotic.rs.payment.domain.entity.PaymentOrder;
import com.sinrotic.rs.payment.mapper.PaymentOrderMapper;
import com.sun.net.httpserver.HttpServer;
import org.junit.jupiter.api.Test;
import org.springframework.web.client.RestClient;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.atomic.AtomicReference;
import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.*;

class RestOrderClientTest {
    @Test
    void quoteChecksTrustedIdentityAndPaidNotificationUsesPersistedAmount() throws Exception {
        var query = new AtomicReference<String>();
        var paidBody = new AtomicReference<String>();
        var server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/internal/checkout/orders/10/payment-quote", exchange -> {
            query.set(exchange.getRequestURI().getQuery());
            byte[] body = "{\"orderId\":10,\"accountId\":\"trusted\",\"amount\":500}".getBytes(StandardCharsets.UTF_8);
            exchange.getResponseHeaders().set("Content-Type", "application/json");
            exchange.sendResponseHeaders(200,body.length);
            exchange.getResponseBody().write(body);
            exchange.close();
        });
        server.createContext("/internal/orders/10/paid", exchange -> {
            paidBody.set(new String(exchange.getRequestBody().readAllBytes(),StandardCharsets.UTF_8));
            exchange.sendResponseHeaders(200,-1);
            exchange.close();
        });
        server.start();
        try {
            var mapper = mock(PaymentOrderMapper.class);
            var payment = new PaymentOrder();
            payment.setStatus("PAID"); payment.setProvider("mock"); payment.setProviderTransactionId("tx"); payment.setAmount(500L);
            when(mapper.findByOrderId(10L)).thenReturn(payment);
            var client = new RestOrderClient(RestClient.builder(),mapper,"http://127.0.0.1:"+server.getAddress().getPort());
            assertThat(client.paymentQuote(10L,"trusted")).isEqualTo(new OrderClient.PaymentQuote(10L,"trusted",500));
            assertThat(query.get()).isEqualTo("accountId=trusted");
            client.markPaid(10L,"mock","tx");
            var payload = new com.fasterxml.jackson.databind.ObjectMapper().readTree(paidBody.get());
            assertThat(payload.get("amount").asLong()).isEqualTo(500);
            assertThat(payload.get("providerTransactionId").asText()).isEqualTo("tx");
        } finally { server.stop(0); }
    }
}
