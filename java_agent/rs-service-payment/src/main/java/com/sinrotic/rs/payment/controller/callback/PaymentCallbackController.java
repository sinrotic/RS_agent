package com.sinrotic.rs.payment.controller.callback;

import com.sinrotic.rs.payment.domain.dto.PaymentCallbackDTO;
import com.sinrotic.rs.payment.service.PaymentService;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/callback/payments")
public class PaymentCallbackController {

    private final PaymentService paymentService;

    public PaymentCallbackController(PaymentService paymentService) {
        this.paymentService = paymentService;
    }

    @PostMapping("/{provider}")
    public void handleCallback(
            @PathVariable String provider,
            @RequestBody(required = false) PaymentCallbackDTO request
    ) {
        PaymentCallbackDTO body = request == null
                ? new PaymentCallbackDTO(null, null, null, null, null, null)
                : request;
        paymentService.handleCallback(new PaymentCallbackDTO(
                provider,
                body.providerTransactionId(),
                body.orderId(),
                body.amount(),
                body.signature(),
                body.rawPayload()
        ));
    }
}
