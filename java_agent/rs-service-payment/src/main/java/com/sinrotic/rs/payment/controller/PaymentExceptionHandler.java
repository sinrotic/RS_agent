package com.sinrotic.rs.payment.controller;

import com.sinrotic.rs.payment.service.PaymentServiceException;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import org.springframework.web.client.HttpClientErrorException;
import org.springframework.web.client.HttpServerErrorException;
import org.springframework.web.client.ResourceAccessException;
import java.util.Map;

@RestControllerAdvice
public class PaymentExceptionHandler {
    @ExceptionHandler(com.sinrotic.rs.payment.service.MockPaymentDisabledException.class)
    public ResponseEntity<Map<String,String>> disabled(com.sinrotic.rs.payment.service.MockPaymentDisabledException failure) {
        return ResponseEntity.status(404).body(Map.of("code","MOCK_PAYMENT_DISABLED","message",failure.getMessage()));
    }
    @ExceptionHandler(PaymentServiceException.class)
    public ResponseEntity<Map<String,String>> invalid(PaymentServiceException failure) {
        return ResponseEntity.badRequest().body(Map.of("code","INVALID_PAYMENT_REQUEST","message",failure.getMessage()));
    }
    @ExceptionHandler(HttpClientErrorException.class)
    public ResponseEntity<Map<String,String>> unavailableOrder(HttpClientErrorException failure) {
        int status = failure.getStatusCode().value();
        return ResponseEntity.status(status == 404 ? 404 : 409)
                .body(Map.of("code","ORDER_NOT_PAYABLE","message","订单不存在或当前不可支付"));
    }
    @ExceptionHandler({ResourceAccessException.class,HttpServerErrorException.class})
    public ResponseEntity<Map<String,String>> unavailable(RuntimeException failure) {
        return ResponseEntity.status(503).body(Map.of("code","ORDER_CHECK_UNAVAILABLE","message","订单支付核验暂时不可用，请稍后重试"));
    }
}
