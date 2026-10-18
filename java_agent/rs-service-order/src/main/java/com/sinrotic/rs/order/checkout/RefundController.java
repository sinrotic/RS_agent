package com.sinrotic.rs.order.checkout;
import com.sinrotic.rs.common.commerce.*;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.web.bind.annotation.*;
import jakarta.servlet.http.HttpServletRequest;
@RestController
public class RefundController {
    private final RefundService service;private final String token;
    public RefundController(RefundService service,@Value("${rs.commerce.service-token:}") String token) {this.service=service;this.token=token;}
    @PostMapping("/api/checkout/orders/{orderId}/refunds")
    public RefundService.View request(@RequestHeader("X-Account-Id") String account,@PathVariable long orderId,@RequestBody RefundService.Request request) {return service.request(account,orderId,request);}
    @GetMapping("/api/checkout/orders/{orderId}/refund")
    public RefundService.View get(@RequestHeader("X-Account-Id") String account,@PathVariable long orderId) {return service.get(account,orderId);}
    @GetMapping("/internal/checkout/orders/{orderId}/refund-quote")
    public RefundService.Quote quote(@PathVariable long orderId,@RequestHeader(value="Authorization",required=false) String authorization) {
        CommerceServiceAuthorization.require(authorization,token);return service.quote(orderId);
    }
    @GetMapping("/internal/checkout/refunds") public java.util.List<java.util.Map<String,Object>> tasks() {return service.tasks();}
    public record Retry(String reason) {}
    @PostMapping("/internal/checkout/refunds/{id}/retry") public void retry(@PathVariable String id,@RequestBody Retry input,HttpServletRequest request) {
        service.retry(id,CommerceOperationsConfiguration.actor(request),input.reason());
    }
}
