package com.sinrotic.rs.order.controller.app;

import com.sinrotic.rs.order.checkout.CheckoutService;
import com.sinrotic.rs.order.domain.dto.CreateOrderRequestDTO;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

class AppOrderControllerTest {
    @Test
    void createOrderUsesTrustedGatewayIdentityAndIgnoresClientPrice() {
        CheckoutService service=mock(CheckoutService.class);
        var controller=new AppOrderController(service);
        var body=new CreateOrderRequestDTO("req","spoofed","spoofed-profile","session","delivery",
                "item","sku","untrusted title",1,1L,"coupon");
        when(service.create(anyString(),anyString(),any())).thenReturn(new CheckoutService.OrderView(1L,"CREATING","LOCK_COUPON",
                "item","sku","server title",1,3000,0,3000,"coupon",null,null));
        controller.createOrder("account","profile",body);
        var request=ArgumentCaptor.forClass(CheckoutService.CreateRequest.class);
        verify(service).create(eq("account"),eq("profile"),request.capture());
        assertThat(request.getValue().couponId()).isEqualTo("coupon");
        assertThat(request.getValue().recommendRequestId()).isEqualTo("delivery");
        assertThat(request.getValue().itemId()).isEqualTo("item");
    }

    @Test
    void cancellationAlwaysCarriesAuthenticatedAccount() {
        var service=mock(CheckoutService.class);
        new AppOrderController(service).cancel("account",123L,null);
        verify(service).cancel("account",123L);
    }
}
