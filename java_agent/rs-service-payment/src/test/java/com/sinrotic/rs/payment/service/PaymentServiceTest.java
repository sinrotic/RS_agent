package com.sinrotic.rs.payment.service;

import com.sinrotic.rs.payment.client.OrderClient;
import com.sinrotic.rs.payment.domain.dto.CreatePaymentRequestDTO;
import com.sinrotic.rs.payment.domain.dto.PaymentCallbackDTO;
import com.sinrotic.rs.payment.domain.entity.PaymentCallback;
import com.sinrotic.rs.payment.domain.entity.PaymentOrder;
import com.sinrotic.rs.payment.domain.vo.PaymentPrepayVO;
import com.sinrotic.rs.payment.mapper.PaymentCallbackMapper;
import com.sinrotic.rs.payment.mapper.PaymentOrderMapper;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.dao.DuplicateKeyException;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.HexFormat;
import java.util.concurrent.atomic.AtomicLong;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.Mockito.any;
import static org.mockito.Mockito.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class PaymentServiceTest {

    private PaymentOrderMapper paymentOrderMapper;
    private PaymentCallbackMapper paymentCallbackMapper;
    private OrderClient orderClient;
    private PaymentService paymentService;

    @BeforeEach
    void setUp() {
        paymentOrderMapper = mock(PaymentOrderMapper.class);
        paymentCallbackMapper = mock(PaymentCallbackMapper.class);
        orderClient = mock(OrderClient.class);
        AtomicLong idSequence = new AtomicLong(1000L);
        PaymentTransitionService transitionService =
                new PaymentTransitionService(paymentOrderMapper, paymentCallbackMapper);
        paymentService = new PaymentService(paymentOrderMapper, transitionService, orderClient, idSequence::incrementAndGet);
    }

    @Test
    void createPrepayInsertsWaitingPayAndReturnsPrepayView() {
        when(paymentOrderMapper.insertPayment(1001L, 10L, "mock", 500L, "WAITING_PAY")).thenReturn(1);

        PaymentPrepayVO response = paymentService.createPrepay(
                new CreatePaymentRequestDTO(10L, 20L, 500L, " MoCk ")
        );

        assertEquals(1001L, response.paymentId());
        assertEquals(10L, response.orderId());
        assertEquals("mock", response.provider());
        assertEquals("WAITING_PAY", response.status());
        verify(paymentOrderMapper).insertPayment(1001L, 10L, "mock", 500L, "WAITING_PAY");
    }

    @Test
    void createPrepayDuplicateSameOrderProviderAndAmountReturnsExistingPayment() {
        PaymentOrder existing = paymentOrder(9001L, 10L, "mock", null, "WAITING_PAY", 500L);
        when(paymentOrderMapper.insertPayment(1001L, 10L, "mock", 500L, "WAITING_PAY"))
                .thenThrow(new DuplicateKeyException("duplicate order"));
        when(paymentOrderMapper.findByOrderId(10L)).thenReturn(existing);

        PaymentPrepayVO response = paymentService.createPrepay(
                new CreatePaymentRequestDTO(10L, 20L, 500L, "mock")
        );

        assertEquals(9001L, response.paymentId());
        assertEquals(10L, response.orderId());
        assertEquals("mock", response.provider());
        assertEquals("WAITING_PAY", response.status());
        verify(paymentOrderMapper).findByOrderId(10L);
    }

    @Test
    void createPrepayDuplicateConflictingAmountThrows() {
        PaymentOrder existing = paymentOrder(9001L, 10L, "mock", null, "WAITING_PAY", 999L);
        when(paymentOrderMapper.insertPayment(1001L, 10L, "mock", 500L, "WAITING_PAY"))
                .thenThrow(new DuplicateKeyException("duplicate order"));
        when(paymentOrderMapper.findByOrderId(10L)).thenReturn(existing);

        assertThrows(
                PaymentServiceException.class,
                () -> paymentService.createPrepay(new CreatePaymentRequestDTO(10L, 20L, 500L, "mock"))
        );
    }

    @Test
    void createPrepayDuplicateConflictingProviderThrows() {
        PaymentOrder existing = paymentOrder(9001L, 10L, "other", null, "WAITING_PAY", 500L);
        when(paymentOrderMapper.insertPayment(1001L, 10L, "mock", 500L, "WAITING_PAY"))
                .thenThrow(new DuplicateKeyException("duplicate order"));
        when(paymentOrderMapper.findByOrderId(10L)).thenReturn(existing);

        assertThrows(
                PaymentServiceException.class,
                () -> paymentService.createPrepay(new CreatePaymentRequestDTO(10L, 20L, 500L, "mock"))
        );
    }

    @Test
    void createPrepayInvalidProviderThrows() {
        assertThrows(
                PaymentServiceException.class,
                () -> paymentService.createPrepay(new CreatePaymentRequestDTO(10L, 20L, 500L, "realpay"))
        );

        verify(paymentOrderMapper, never()).insertPayment(any(), any(), any(), any(), any());
    }

    @Test
    void handleCallbackFirstCallbackInsertsCallbackMarksPaidAndCallsOrderClient() {
        String rawPayload = "{\"orderId\":10,\"amount\":500}";
        String payloadHash = sha256Hex(rawPayload);
        when(paymentCallbackMapper.insertCallback("mock", "tx-1", 10L, 500L, "PAID", payloadHash)).thenReturn(1);
        when(paymentOrderMapper.markPaid(10L, "mock", 500L, "tx-1")).thenReturn(1);

        paymentService.handleCallback(new PaymentCallbackDTO(" MoCk ", "tx-1", 10L, 500L, "mock-signature", rawPayload));

        verify(paymentCallbackMapper).insertCallback("mock", "tx-1", 10L, 500L, "PAID", payloadHash);
        verify(paymentOrderMapper).markPaid(10L, "mock", 500L, "tx-1");
        verify(orderClient).markPaid(10L, "mock", "tx-1");
    }

    @Test
    void handleCallbackAmountMismatchDoesNotMarkPaidAndThrows() {
        String rawPayload = "{\"orderId\":10,\"amount\":500}";
        String payloadHash = sha256Hex(rawPayload);
        when(paymentCallbackMapper.insertCallback("mock", "tx-1", 10L, 500L, "PAID", payloadHash)).thenReturn(1);
        when(paymentOrderMapper.markPaid(10L, "mock", 500L, "tx-1")).thenReturn(0);
        when(paymentOrderMapper.findByOrderId(10L))
                .thenReturn(paymentOrder(9001L, 10L, "mock", null, "WAITING_PAY", 999L));

        assertThrows(
                PaymentServiceException.class,
                () -> paymentService.handleCallback(
                        new PaymentCallbackDTO("mock", "tx-1", 10L, 500L, "mock-signature", rawPayload)
                )
        );

        verify(paymentOrderMapper).markPaid(10L, "mock", 500L, "tx-1");
        verify(orderClient, never()).markPaid(any(), any(), any());
    }

    @Test
    void handleCallbackDuplicateIdenticalCallbackRetriesOrderNotificationWhenPaymentOrderAlreadyPaid() {
        String rawPayload = "{\"orderId\":10,\"amount\":500}";
        String payloadHash = sha256Hex(rawPayload);
        when(paymentCallbackMapper.insertCallback("mock", "tx-1", 10L, 500L, "PAID", payloadHash))
                .thenReturn(1)
                .thenThrow(new DuplicateKeyException("duplicate callback"));
        when(paymentOrderMapper.markPaid(10L, "mock", 500L, "tx-1"))
                .thenReturn(1)
                .thenReturn(0);
        when(paymentCallbackMapper.findByProviderTransaction("mock", "tx-1"))
                .thenReturn(callback("mock", "tx-1", 10L, 500L, "PAID", payloadHash));
        when(paymentOrderMapper.findByOrderId(10L))
                .thenReturn(paymentOrder(9001L, 10L, "mock", "tx-1", "PAID", 500L));

        PaymentCallbackDTO callback = new PaymentCallbackDTO("mock", "tx-1", 10L, 500L, "mock-signature", rawPayload);
        paymentService.handleCallback(callback);
        paymentService.handleCallback(callback);

        verify(orderClient, times(2)).markPaid(10L, "mock", "tx-1");
        verify(paymentCallbackMapper).findByProviderTransaction("mock", "tx-1");
        verify(paymentOrderMapper).findByOrderId(10L);
    }

    @Test
    void handleCallbackDuplicateIdenticalCallbackWithConflictingPaidOrderThrowsAndDoesNotNotifyAgain() {
        String rawPayload = "{\"orderId\":10,\"amount\":500}";
        String payloadHash = sha256Hex(rawPayload);
        when(paymentCallbackMapper.insertCallback("mock", "tx-1", 10L, 500L, "PAID", payloadHash))
                .thenReturn(1)
                .thenThrow(new DuplicateKeyException("duplicate callback"));
        when(paymentOrderMapper.markPaid(10L, "mock", 500L, "tx-1"))
                .thenReturn(1)
                .thenReturn(0);
        when(paymentCallbackMapper.findByProviderTransaction("mock", "tx-1"))
                .thenReturn(callback("mock", "tx-1", 10L, 500L, "PAID", payloadHash));
        when(paymentOrderMapper.findByOrderId(10L))
                .thenReturn(paymentOrder(9001L, 10L, "mock", "tx-other", "PAID", 500L));

        PaymentCallbackDTO callback = new PaymentCallbackDTO("mock", "tx-1", 10L, 500L, "mock-signature", rawPayload);
        paymentService.handleCallback(callback);
        assertThrows(PaymentServiceException.class, () -> paymentService.handleCallback(callback));

        verify(orderClient, times(1)).markPaid(10L, "mock", "tx-1");
        verify(paymentOrderMapper).findByOrderId(10L);
    }

    @Test
    void handleCallbackDuplicateConflictingCallbackThrows() {
        String rawPayload = "{\"orderId\":10,\"amount\":500}";
        String payloadHash = sha256Hex(rawPayload);
        when(paymentCallbackMapper.insertCallback("mock", "tx-1", 10L, 500L, "PAID", payloadHash))
                .thenThrow(new DuplicateKeyException("duplicate callback"));
        when(paymentCallbackMapper.findByProviderTransaction("mock", "tx-1"))
                .thenReturn(callback("mock", "tx-1", 10L, 999L, "PAID", payloadHash));

        assertThrows(
                PaymentServiceException.class,
                () -> paymentService.handleCallback(
                        new PaymentCallbackDTO("mock", "tx-1", 10L, 500L, "mock-signature", rawPayload)
                )
        );

        verify(paymentOrderMapper, never()).markPaid(any(), any(), any(), any());
        verify(orderClient, never()).markPaid(any(), any(), any());
    }

    @Test
    void handleCallbackMissingTransactionIdOrSignatureThrows() {
        assertThrows(
                PaymentServiceException.class,
                () -> paymentService.handleCallback(
                        new PaymentCallbackDTO("mock", " ", 10L, 500L, "mock-signature", "{}")
                )
        );
        assertThrows(
                PaymentServiceException.class,
                () -> paymentService.handleCallback(
                        new PaymentCallbackDTO("mock", "tx-1", 10L, 500L, " ", "{}")
                )
        );

        verify(paymentCallbackMapper, never()).insertCallback(any(), any(), any(), any(), eq("PAID"), any());
        verify(orderClient, never()).markPaid(any(), any(), any());
    }

    @Test
    void handleCallbackInvalidProviderThrows() {
        assertThrows(
                PaymentServiceException.class,
                () -> paymentService.handleCallback(
                        new PaymentCallbackDTO("realpay", "tx-1", 10L, 500L, "mock-signature", "{}")
                )
        );

        verify(paymentCallbackMapper, never()).insertCallback(any(), any(), any(), any(), eq("PAID"), any());
        verify(orderClient, never()).markPaid(any(), any(), any());
    }

    @Test
    void handleCallbackInvalidMockSignatureThrows() {
        assertThrows(
                PaymentServiceException.class,
                () -> paymentService.handleCallback(
                        new PaymentCallbackDTO("mock", "tx-1", 10L, 500L, "sig-1", "{}")
                )
        );

        verify(paymentCallbackMapper, never()).insertCallback(any(), any(), any(), any(), eq("PAID"), any());
        verify(orderClient, never()).markPaid(any(), any(), any());
    }

    private PaymentCallback callback(
            String provider,
            String providerTransactionId,
            Long orderId,
            Long amount,
            String status,
            String payloadHash
    ) {
        PaymentCallback callback = new PaymentCallback();
        callback.setProvider(provider);
        callback.setProviderTransactionId(providerTransactionId);
        callback.setOrderId(orderId);
        callback.setAmount(amount);
        callback.setStatus(status);
        callback.setPayloadHash(payloadHash);
        return callback;
    }

    private PaymentOrder paymentOrder(
            Long paymentId,
            Long orderId,
            String provider,
            String providerTransactionId,
            String status,
            Long amount
    ) {
        PaymentOrder paymentOrder = new PaymentOrder();
        paymentOrder.setPaymentId(paymentId);
        paymentOrder.setOrderId(orderId);
        paymentOrder.setProvider(provider);
        paymentOrder.setProviderTransactionId(providerTransactionId);
        paymentOrder.setStatus(status);
        paymentOrder.setAmount(amount);
        return paymentOrder;
    }

    private String sha256Hex(String value) {
        try {
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            byte[] hash = digest.digest(value.getBytes(StandardCharsets.UTF_8));
            return HexFormat.of().formatHex(hash);
        } catch (NoSuchAlgorithmException ex) {
            throw new IllegalStateException(ex);
        }
    }
}
