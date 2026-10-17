package com.sinrotic.rs.payment.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.sinrotic.rs.payment.client.OrderClient;
import com.sinrotic.rs.payment.controller.PaymentExceptionHandler;
import com.sinrotic.rs.payment.controller.app.AppPaymentController;
import com.sinrotic.rs.payment.controller.callback.PaymentCallbackController;
import com.sinrotic.rs.payment.domain.dto.CreatePaymentRequestDTO;
import com.sinrotic.rs.payment.domain.dto.PaymentCallbackDTO;
import com.sinrotic.rs.payment.mapper.PaymentOrderMapper;
import org.junit.jupiter.api.Test;
import org.springframework.boot.test.context.runner.ApplicationContextRunner;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

class PaymentCallbackSecurityTest {
    private static final String SECRET = "audit-only-secret-for-local-tests-20261011";
    private final PaymentOrderMapper payments = mock(PaymentOrderMapper.class);
    private final PaymentTransitionService transitions = mock(PaymentTransitionService.class);
    private final OrderClient orders = mock(OrderClient.class);
    private final PaymentNotificationService notifications = mock(PaymentNotificationService.class);

    private PaymentService service(boolean enabled, String secret) {
        return new PaymentService(payments,transitions,orders,()->1L,notifications,enabled,secret);
    }
    private PaymentCallbackDTO callback(long orderId, long amount, String transactionId, String payload, String signature) {
        return new PaymentCallbackDTO("mock",transactionId,orderId,amount,signature,payload);
    }
    private String signature() { return MockPaymentCallbackSignature.sign(SECRET,"mock","tx",42,100,"payload"); }

    @Test
    void disabledEndpointsReturn404BeforeAnyLedgerOrOrderInteraction() throws Exception {
        var service = new PaymentService(payments,transitions,orders,()->1L,notifications);
        var mvc = MockMvcBuilders.standaloneSetup(new PaymentCallbackController(service),new AppPaymentController(service))
                .setControllerAdvice(new PaymentExceptionHandler()).build();
        mvc.perform(post("/callback/payments/mock").contentType("application/json")
                .content(new ObjectMapper().writeValueAsString(callback(42,100,"tx","payload",signature()))))
                .andExpect(status().isNotFound()).andExpect(jsonPath("$.code").value("MOCK_PAYMENT_DISABLED"));
        mvc.perform(post("/api/payments/prepay").header("X-Account-Id","owner").contentType("application/json")
                .content("{\"orderId\":42,\"amount\":100,\"provider\":\"mock\"}"))
                .andExpect(status().isNotFound());
        verifyNoInteractions(payments,transitions,orders,notifications);
    }

    @Test
    void enablingMockWithoutASecretStillRejectsCallbacks() {
        assertThatThrownBy(()->service(true,"").handleCallback(callback(42,100,"tx","payload",signature())))
                .isInstanceOf(PaymentServiceException.class);
        verifyNoInteractions(payments,transitions,notifications);
    }

    @Test
    void oldFixedSignatureAndWrongKeyAreRejectedEvenWhenMockIsEnabled() {
        var enabled = service(true,SECRET);
        for (String signature : new String[]{"mock-signature",MockPaymentCallbackSignature.sign(SECRET+"other","mock","tx",42,100,"payload")})
            assertThatThrownBy(()->enabled.handleCallback(callback(42,100,"tx","payload",signature)))
                    .isInstanceOf(PaymentServiceException.class);
        verifyNoInteractions(payments,transitions,notifications);
    }

    @Test
    void signatureBindsOrderAmountTransactionAndExactPayloadIncludingWhitespace() {
        var enabled = service(true,SECRET);
        for (var altered : new PaymentCallbackDTO[]{callback(43,100,"tx","payload",signature()),
                callback(42,101,"tx","payload",signature()),callback(42,100,"other","payload",signature()),
                callback(42,100,"tx","payload ",signature())}) {
            assertThatThrownBy(()->enabled.handleCallback(altered)).isInstanceOf(PaymentServiceException.class);
        }
        verifyNoInteractions(payments,transitions,notifications);
    }

    @Test
    void validSignedCallbackReachesTransitionOnlyInExplicitMockMode() {
        when(transitions.recordPaidCallback(anyString(),anyString(),anyLong(),anyLong(),anyString()))
                .thenReturn(new OrderPaidMessage(42L,"mock","tx"));
        service(true,SECRET).handleCallback(callback(42,100,"tx","payload",signature()));
        verify(transitions).recordPaidCallback(eq("mock"),eq("tx"),eq(42L),eq(100L),anyString());
        verify(notifications).dispatch(42L);
    }

    @Test
    void springDefaultsClosedAndUsesTheSharedDeploymentFlag() {
        var context = new ApplicationContextRunner().withUserConfiguration(PaymentService.class)
                .withBean(PaymentOrderMapper.class,()->payments).withBean(PaymentTransitionService.class,()->transitions)
                .withBean(OrderClient.class,()->orders).withBean(IdGenerator.class,()->()->1L)
                .withBean(PaymentNotificationService.class,()->notifications);
        context.run(c -> assertThatThrownBy(()->c.getBean(PaymentService.class).handleCallback(callback(42,100,"tx","payload",signature())))
                .isInstanceOf(MockPaymentDisabledException.class));
        context.withPropertyValues("RS_CHECKOUT_MOCK_PAYMENT_ENABLED=true","RS_PAYMENT_MOCK_CALLBACK_SECRET="+SECRET)
                .run(c -> c.getBean(PaymentService.class).handleCallback(callback(42,100,"tx","payload",signature())));
        verify(transitions).recordPaidCallback(anyString(),anyString(),anyLong(),anyLong(),anyString());
    }
}
