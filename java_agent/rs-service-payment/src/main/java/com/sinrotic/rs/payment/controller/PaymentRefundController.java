package com.sinrotic.rs.payment.controller;
import com.sinrotic.rs.payment.service.PaymentRefundService;
import com.sinrotic.rs.common.commerce.CommerceServiceAuthorization;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.web.bind.annotation.*;
@RestController
public class PaymentRefundController {
    private final PaymentRefundService service;private final String token;
    public PaymentRefundController(PaymentRefundService service,@Value("${rs.commerce.service-token:}") String token) {this.service=service;this.token=token;}
    @PostMapping("/internal/payment/refunds") public PaymentRefundService.Result refund(@RequestBody PaymentRefundService.Request input,@RequestHeader(value="Authorization",required=false) String auth) {
        CommerceServiceAuthorization.require(auth,token);return service.refund(input);
    }
    @PostMapping("/callback/payments/refunds") public void callback(@RequestBody PaymentRefundService.Callback input) {service.callback(input);}
}
