package com.sinrotic.rs.payment.controller.app;

import com.sinrotic.rs.payment.domain.dto.CreatePaymentRequestDTO;
import com.sinrotic.rs.payment.domain.vo.PaymentPrepayVO;
import com.sinrotic.rs.payment.service.PaymentService;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.bind.annotation.RequestHeader;

@RestController
@RequestMapping("/api/payments")
public class AppPaymentController {

    private final PaymentService paymentService;

    public AppPaymentController(PaymentService paymentService) {
        this.paymentService = paymentService;
    }

    @PostMapping("/prepay")
    public PaymentPrepayVO createPrepay(@RequestHeader("X-Account-Id") String accountId, @RequestBody CreatePaymentRequestDTO request) {
        return paymentService.createPrepay(accountId, request);
    }
}
