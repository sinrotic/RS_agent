package com.sinrotic.rs.payment.controller;

import com.sinrotic.rs.payment.service.PaymentOperationsService;
import org.springframework.web.bind.annotation.*;
import java.util.List;
import java.util.Map;

@RestController
@RequestMapping("/internal/payment/notifications")
public class PaymentOperationsController {
    private final PaymentOperationsService service;
    public PaymentOperationsController(PaymentOperationsService service) { this.service=service; }
    @GetMapping
    public List<PaymentOperationsService.TaskView> tasks(@RequestParam(defaultValue="1200") int minimumAgeSeconds) {
        return service.tasks(minimumAgeSeconds);
    }
    @GetMapping("/summary")
    public Map<String,Long> summary() { return service.summary(); }
    @PostMapping("/{orderId}/retry")
    public void retry(@PathVariable long orderId,@RequestBody PaymentOperationsService.OperatorAction action,jakarta.servlet.http.HttpServletRequest request) {
        service.retry(orderId,authenticated(action,request));
    }
    @PostMapping("/{orderId}/mock-refund")
    public PaymentOperationsService.MockRefundResult mockRefund(@PathVariable long orderId,@RequestBody PaymentOperationsService.OperatorAction action,jakarta.servlet.http.HttpServletRequest request) {
        return service.mockRefund(orderId,authenticated(action,request));
    }
    private PaymentOperationsService.OperatorAction authenticated(PaymentOperationsService.OperatorAction action,jakarta.servlet.http.HttpServletRequest request) {
        return new PaymentOperationsService.OperatorAction(com.sinrotic.rs.common.commerce.CommerceOperationsConfiguration.actor(request),action.reason());
    }
}
