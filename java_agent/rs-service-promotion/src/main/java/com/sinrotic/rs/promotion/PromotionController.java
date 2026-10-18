package com.sinrotic.rs.promotion;

import org.springframework.web.bind.annotation.*;
import java.util.List;

@RestController
public class PromotionController {
    private final PromotionService service;
    private final PromotionAdmission admission;
    private PromotionManagement management;
    @org.springframework.beans.factory.annotation.Autowired public void setManagement(PromotionManagement management) {this.management=management;}
    public PromotionController(PromotionService service, PromotionAdmission admission) { this.service = service; this.admission = admission; }
    public record ClaimRequest(String requestId) {}
    public record FinishRequest(String couponId) {}

    @GetMapping("/api/promotions/campaigns")
    public List<PromotionService.Campaign> campaigns(@RequestParam String itemId) { return service.campaigns(itemId); }

    @GetMapping("/api/promotions/coupons")
    public List<PromotionService.Coupon> wallet(@RequestHeader("X-Account-Id") String accountId) { return service.wallet(accountId); }
    @GetMapping("/api/promotions/coupons/page")
    public com.sinrotic.rs.common.commerce.CommerceInput.Page<PromotionService.Coupon> walletPage(@RequestHeader("X-Account-Id") String accountId,
            @RequestParam(required=false) String afterId,@RequestParam(defaultValue="20") int limit) {return service.walletPage(accountId,afterId,limit);}

    @PostMapping("/api/promotions/campaigns/{campaignId}/claim")
    public PromotionService.Coupon claim(@RequestHeader("X-Account-Id") String accountId,
                                        @PathVariable String campaignId, @RequestBody ClaimRequest request) {
        admission.check(campaignId);
        return service.claim(accountId, campaignId, request.requestId());
    }

    @PostMapping("/internal/promotions/campaigns")
    public void create(@RequestBody PromotionService.Campaign input,jakarta.servlet.http.HttpServletRequest request) {
        management.create(input,com.sinrotic.rs.common.commerce.CommerceOperationsConfiguration.actor(request));
    }
    @GetMapping("/internal/promotions/campaigns")
    public com.sinrotic.rs.common.commerce.CommerceInput.Page<java.util.Map<String,Object>> management(@RequestParam(required=false) String afterId,@RequestParam(defaultValue="20") int limit) {return management.list(afterId,limit);}

    @PostMapping("/internal/promotions/reservations")
    public PromotionService.Reservation lock(@RequestBody PromotionService.LockRequest request) { return service.lock(request); }

    @PostMapping("/internal/promotions/reservations/cancel")
    public void cancel(@RequestBody PromotionService.LockRequest request) { service.cancel(request); }

    @PostMapping("/internal/promotions/reservations/{orderId}/confirm")
    public void confirm(@PathVariable long orderId, @RequestBody FinishRequest request) { service.finish(orderId, request.couponId(), true); }

    @PostMapping("/internal/promotions/reservations/{orderId}/release")
    public void release(@PathVariable long orderId, @RequestBody FinishRequest request) { service.finish(orderId, request.couponId(), false); }
    @PostMapping("/internal/promotions/reservations/{orderId}/refund")
    public void refund(@PathVariable long orderId,@RequestBody FinishRequest request) {service.refund(orderId,request.couponId());}
}
