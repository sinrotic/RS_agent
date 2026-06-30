package com.sinrotic.rs.order.controller.app;

import com.sinrotic.rs.order.domain.dto.CancelOrderRequestDTO;
import com.sinrotic.rs.order.domain.dto.CreateOrderRequestDTO;
import com.sinrotic.rs.order.domain.vo.OrderCreateVO;
import com.sinrotic.rs.order.service.OrderService;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/orders")
public class AppOrderController {

    private final OrderService orderService;

    public AppOrderController(OrderService orderService) {
        this.orderService = orderService;
    }

    @PostMapping
    public OrderCreateVO createOrder(@RequestBody CreateOrderRequestDTO request) {
        return orderService.createOrder(request);
    }

    @PostMapping("/{orderId}/cancel")
    public void cancel(@PathVariable Long orderId, @RequestBody(required = false) CancelOrderRequestDTO request) {
        orderService.cancel(orderId, request == null ? null : request.requestId());
    }
}
