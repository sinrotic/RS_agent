package com.sinrotic.rs.order.checkout;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.web.bind.annotation.*;
import org.springframework.http.HttpStatus;
import org.springframework.web.server.ResponseStatusException;
import java.util.List;
import java.util.Map;

@RestController
@RequestMapping("/api/checkout")
public class CheckoutController {
    private final CheckoutService service;
    private final boolean mockPaymentEnabled;
    public CheckoutController(CheckoutService service, @Value("${rs.checkout.mock-payment-enabled:false}") boolean mockPaymentEnabled) {
        this.service = service; this.mockPaymentEnabled = mockPaymentEnabled;
    }
    @GetMapping("/offers")
    public List<CheckoutService.Offer> offers(@RequestParam String itemId) { return service.offers(itemId); }
    @GetMapping("/capabilities")
    public Map<String,Boolean> capabilities() { return Map.of("mockPaymentEnabled",mockPaymentEnabled); }
    @PostMapping("/orders")
    public CheckoutService.OrderView create(@RequestHeader("X-Account-Id") String accountId,
            @RequestHeader(value="X-Profile-User-Id",required=false) String profileId,
            @RequestBody CheckoutService.CreateRequest request) { return service.create(accountId,profileId,request); }
    @GetMapping("/orders")
    public List<CheckoutService.OrderView> list(@RequestHeader("X-Account-Id") String accountId) { return service.list(accountId); }
    @GetMapping("/orders/page")
    public com.sinrotic.rs.common.commerce.CommerceInput.Page<CheckoutService.OrderView> page(@RequestHeader("X-Account-Id") String accountId,
            @RequestParam(required=false) Long beforeId,@RequestParam(required=false) String itemId,@RequestParam(defaultValue="20") int limit) {
        return service.page(accountId,beforeId,itemId,limit);
    }
    @GetMapping("/orders/{orderId}")
    public CheckoutService.OrderView get(@RequestHeader("X-Account-Id") String accountId,@PathVariable long orderId) {
        return service.get(accountId,orderId);
    }
    @PostMapping("/orders/{orderId}/cancel")
    public CheckoutService.OrderView cancel(@RequestHeader("X-Account-Id") String accountId,@PathVariable long orderId) {
        return service.cancel(accountId,orderId);
    }
    @PostMapping("/orders/{orderId}/mock-pay")
    public CheckoutService.OrderView mockPay(@RequestHeader("X-Account-Id") String accountId,@PathVariable long orderId,
            @RequestBody(required=false) MockPaymentRequest request) {
        if (!mockPaymentEnabled) throw new ResponseStatusException(HttpStatus.NOT_FOUND);
        var order = service.get(accountId,orderId);
        var scenario = request == null || request.scenario() == null ? MockPaymentScenario.SUCCESS : request.scenario();
        // 已支付订单重试直接返回事实，不再次注入故障或推进资源。
        if ("PAID".equals(order.status())) return order;
        if (!"WAITING_PAYMENT".equals(order.status()))
            throw new ResponseStatusException(HttpStatus.CONFLICT,"订单当前状态不允许支付");
        if (scenario == MockPaymentScenario.DECLINED)
            throw new ResponseStatusException(HttpStatus.PAYMENT_REQUIRED,"模拟支付被拒，订单仍待支付");
        if (scenario == MockPaymentScenario.TIMEOUT_BEFORE_PAYMENT)
            throw new ResponseStatusException(HttpStatus.GATEWAY_TIMEOUT,"模拟支付前超时，请查询订单后重试");
        service.paidFromProvider(orderId,order.totalAmount(),"mock","mock-checkout-"+orderId);
        if (scenario == MockPaymentScenario.RESPONSE_LOST)
            throw new ResponseStatusException(HttpStatus.GATEWAY_TIMEOUT,"模拟支付响应丢失，请查询原订单");
        return service.get(accountId,orderId);
    }

    public CheckoutService.OrderView mockPay(String accountId,long orderId) { return mockPay(accountId,orderId,null); }

    public enum MockPaymentScenario { SUCCESS, DECLINED, TIMEOUT_BEFORE_PAYMENT, RESPONSE_LOST }
    public record MockPaymentRequest(MockPaymentScenario scenario) {}
}
