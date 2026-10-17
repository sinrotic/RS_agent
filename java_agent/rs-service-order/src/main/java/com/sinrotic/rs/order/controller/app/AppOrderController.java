package com.sinrotic.rs.order.controller.app;

import com.sinrotic.rs.order.domain.dto.CancelOrderRequestDTO;
import com.sinrotic.rs.order.domain.dto.CreateOrderRequestDTO;
import com.sinrotic.rs.order.domain.vo.OrderCreateVO;
import com.sinrotic.rs.order.checkout.CheckoutService;
import org.springframework.web.bind.annotation.*;
import java.util.List;

@RestController
@RequestMapping("/api/orders")
public class AppOrderController {
    private final CheckoutService checkout;
    public AppOrderController(CheckoutService checkout) { this.checkout=checkout; }

    @PostMapping
    public OrderCreateVO createOrder(@RequestHeader("X-Account-Id") String accountId,
            @RequestHeader(value="X-Profile-User-Id",required=false) String profileUserId,
            @RequestBody CreateOrderRequestDTO request) {
        // 兼容既有下单入口，但不信任客户端的标题和单价。
        var order=checkout.create(accountId,profileUserId,new CheckoutService.CreateRequest(request.requestId(),
                request.itemId(),request.skuId(),request.quantity(),request.couponId(),request.sessionId(),request.recommendRequestId()));
        return new OrderCreateVO(order.orderId(),order.status());
    }
    @GetMapping
    public List<CheckoutService.OrderView> list(@RequestHeader("X-Account-Id") String accountId) { return checkout.list(accountId); }
    @GetMapping("/{orderId}")
    public CheckoutService.OrderView get(@RequestHeader("X-Account-Id") String accountId,@PathVariable long orderId) {
        return checkout.get(accountId,orderId);
    }
    @PostMapping("/{orderId}/cancel")
    public void cancel(@RequestHeader("X-Account-Id") String accountId,@PathVariable long orderId,
                       @RequestBody(required=false) CancelOrderRequestDTO request) { checkout.cancel(accountId,orderId); }
}
