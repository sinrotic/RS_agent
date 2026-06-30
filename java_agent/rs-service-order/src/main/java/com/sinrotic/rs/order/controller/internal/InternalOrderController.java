package com.sinrotic.rs.order.controller.internal;

import com.sinrotic.rs.order.domain.dto.CloseTimeoutOrderRequestDTO;
import com.sinrotic.rs.order.domain.dto.OrderPaidRequestDTO;
import com.sinrotic.rs.order.service.OrderService;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/internal/orders")
public class InternalOrderController {

    private final OrderService orderService;

    public InternalOrderController(OrderService orderService) {
        this.orderService = orderService;
    }

    @PostMapping("/{orderId}/paid")
    public void markPaid(@PathVariable Long orderId, @RequestBody OrderPaidRequestDTO request) {
        orderService.markPaid(new OrderPaidRequestDTO(
                request.requestId(),
                orderId,
                request.provider(),
                request.providerTransactionId()
        ));
    }

    @PostMapping("/{orderId}/close-timeout")
    public void closeTimeout(
            @PathVariable Long orderId,
            @RequestBody(required = false) CloseTimeoutOrderRequestDTO request
    ) {
        orderService.closeTimeout(orderId, request == null ? null : request.requestId());
    }
}
