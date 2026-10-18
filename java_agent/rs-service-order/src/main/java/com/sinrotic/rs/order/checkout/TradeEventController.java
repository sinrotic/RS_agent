package com.sinrotic.rs.order.checkout;
import com.sinrotic.rs.common.commerce.CommerceOperationsConfiguration;
import org.springframework.web.bind.annotation.*;
import jakarta.servlet.http.HttpServletRequest;
@RestController
public class TradeEventController {
    private final TradeEventDispatcher service;
    public TradeEventController(TradeEventDispatcher service) {this.service=service;}
    @GetMapping("/internal/checkout/events") public java.util.List<java.util.Map<String,Object>> tasks() {return service.tasks();}
    public record Retry(String reason) {}
    @PostMapping("/internal/checkout/events/{id}/{target}/retry") public void retry(@PathVariable String id,@PathVariable String target,@RequestBody Retry input,HttpServletRequest request) {
        service.retry(id,target,CommerceOperationsConfiguration.actor(request),input.reason());
    }
}
