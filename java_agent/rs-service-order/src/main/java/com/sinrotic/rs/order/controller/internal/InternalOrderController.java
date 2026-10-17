package com.sinrotic.rs.order.controller.internal;

import com.sinrotic.rs.order.domain.dto.CloseTimeoutOrderRequestDTO;
import com.sinrotic.rs.order.domain.dto.OrderPaidRequestDTO;
import com.sinrotic.rs.order.checkout.CheckoutService;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/internal/orders")
public class InternalOrderController {

    private final CheckoutService checkoutService;
    private final boolean mockPaymentEnabled;

    public InternalOrderController(CheckoutService checkoutService,
            @org.springframework.beans.factory.annotation.Value("${rs.checkout.mock-payment-enabled:false}") boolean mockPaymentEnabled) {
        this.checkoutService = checkoutService;
        this.mockPaymentEnabled = mockPaymentEnabled;
    }

    @PostMapping("/{orderId}/paid")
    public void markPaid(@PathVariable Long orderId, @RequestBody OrderPaidRequestDTO request) {
        if (checkoutService.owns(orderId)) {
            if ("mock".equals(request.provider()) && !mockPaymentEnabled)
                throw new org.springframework.web.server.ResponseStatusException(org.springframework.http.HttpStatus.CONFLICT,"模拟支付未启用");
            checkoutService.paidFromProvider(orderId,request.amount(),request.provider(),request.providerTransactionId());
            return;
        }
        throw new org.springframework.web.server.ResponseStatusException(org.springframework.http.HttpStatus.CONFLICT,
                "旧订单未接入持久工作流，请先核对和迁移；支付通知保留待核对");
    }

    @PostMapping("/{orderId}/close-timeout")
    public void closeTimeout(
            @PathVariable Long orderId,
            @RequestBody(required = false) CloseTimeoutOrderRequestDTO request
    ) {
        if (checkoutService.owns(orderId)) {
            checkoutService.closeTimeout(orderId);
            return;
        }
        throw new org.springframework.web.server.ResponseStatusException(org.springframework.http.HttpStatus.CONFLICT,
                "旧订单未接入持久工作流，请先核对和迁移");
    }
}
