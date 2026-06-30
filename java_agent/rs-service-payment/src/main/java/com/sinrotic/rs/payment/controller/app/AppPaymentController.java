package com.sinrotic.rs.payment.controller.app;

import com.sinrotic.rs.payment.domain.dto.CreatePaymentRequestDTO;
import com.sinrotic.rs.payment.domain.vo.PaymentPrepayVO;
import com.sinrotic.rs.payment.service.PaymentService;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/payments")
public class AppPaymentController {

    private final PaymentService paymentService;

    public AppPaymentController(PaymentService paymentService) {
        this.paymentService = paymentService;
    }

    @PostMapping("/prepay")
    public PaymentPrepayVO createPrepay(@RequestBody CreatePaymentRequestDTO request) {
        return paymentService.createPrepay(request);
    }
}
