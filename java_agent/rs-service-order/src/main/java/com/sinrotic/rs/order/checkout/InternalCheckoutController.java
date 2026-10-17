package com.sinrotic.rs.order.checkout;

import org.springframework.web.bind.annotation.*;

@RestController
public class InternalCheckoutController {
    private final CheckoutService service;
    public InternalCheckoutController(CheckoutService service) { this.service = service; }
    @GetMapping("/internal/checkout/tasks")
    public java.util.List<CheckoutService.TaskView> tasks(@RequestParam(defaultValue="1200") int minimumAgeSeconds) {
        return service.stalledTasks(minimumAgeSeconds);
    }
    @GetMapping("/internal/checkout/tasks/summary")
    public java.util.Map<String,Long> summary() { return service.taskSummary(); }
    @PostMapping("/internal/checkout/tasks/{orderId}/retry")
    public void retry(@PathVariable long orderId,@RequestBody CheckoutService.OperatorAction action,jakarta.servlet.http.HttpServletRequest request) {
        service.retryTask(orderId,new CheckoutService.OperatorAction(com.sinrotic.rs.common.commerce.CommerceOperationsConfiguration.actor(request),action.reason()));
    }
    @GetMapping("/internal/checkout/requests/{requestId}")
    public CheckoutService.OrderView result(@PathVariable String requestId,@RequestParam String accountId) {
        return service.byRequest(accountId,requestId);
    }

    public record PaymentQuote(long orderId, String accountId, long amount) {}

    @GetMapping("/internal/checkout/orders/{orderId}/payment-quote")
    public PaymentQuote paymentQuote(@PathVariable long orderId, @RequestParam String accountId) {
        var order = service.payableOrder(accountId, orderId);
        return new PaymentQuote(order.orderId(), accountId, order.totalAmount());
    }
}
