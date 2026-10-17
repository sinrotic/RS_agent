package com.sinrotic.rs.payment.controller.app;

import com.sinrotic.rs.payment.client.OrderClient;
import com.sinrotic.rs.payment.domain.dto.CreatePaymentRequestDTO;
import com.sinrotic.rs.payment.mapper.PaymentOrderMapper;
import com.sinrotic.rs.payment.service.*;
import org.junit.jupiter.api.Test;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import org.springframework.http.MediaType;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

class PaymentPrepayOwnershipTest {
    @Test
    void headerIdentityAndOrderQuoteOverrideClientAccountAndRejectIncorrectAmount() throws Exception {
        var mapper = mock(PaymentOrderMapper.class);
        var order = mock(OrderClient.class);
        when(order.paymentQuote(10L, "trusted-owner")).thenReturn(new OrderClient.PaymentQuote(10L, "trusted-owner", 500));
        when(mapper.insertPayment(1L,10L,"mock",500L,"WAITING_PAY")).thenReturn(1);
        var service = new PaymentService(mapper, mock(PaymentTransitionService.class), order, () -> 1L,
                mock(PaymentNotificationService.class),true,"");
        var mvc = MockMvcBuilders.standaloneSetup(new AppPaymentController(service))
                .setControllerAdvice(new com.sinrotic.rs.payment.controller.PaymentExceptionHandler()).build();
        mvc.perform(post("/api/payments/prepay").contentType(MediaType.APPLICATION_JSON)
                .content("{\"orderId\":10,\"accountId\":999,\"amount\":500,\"provider\":\"mock\"}"))
                .andExpect(status().isBadRequest());
        mvc.perform(post("/api/payments/prepay").header("X-Account-Id","trusted-owner").contentType(MediaType.APPLICATION_JSON)
                .content("{\"orderId\":10,\"accountId\":999,\"amount\":500,\"provider\":\"mock\"}"))
                .andExpect(status().isOk());
        assertThatThrownBy(() -> service.createPrepay("trusted-owner",new CreatePaymentRequestDTO(10L,999L,1L,"mock")))
                .isInstanceOf(PaymentServiceException.class);
        mvc.perform(post("/api/payments/prepay").header("X-Account-Id","trusted-owner").contentType(MediaType.APPLICATION_JSON)
                .content("{\"orderId\":10,\"amount\":1,\"provider\":\"mock\"}"))
                .andExpect(status().isBadRequest());
        when(order.paymentQuote(10L,"other-account")).thenReturn(new OrderClient.PaymentQuote(10L,"trusted-owner",500));
        assertThatThrownBy(() -> service.createPrepay("other-account",new CreatePaymentRequestDTO(10L,999L,500L,"mock")))
                .isInstanceOf(PaymentServiceException.class);
        verify(mapper,times(1)).insertPayment(any(),any(),any(),any(),any());
    }
}
