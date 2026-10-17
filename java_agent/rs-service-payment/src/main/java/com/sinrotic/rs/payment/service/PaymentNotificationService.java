package com.sinrotic.rs.payment.service;

import com.sinrotic.rs.payment.client.OrderClient;
import com.sinrotic.rs.payment.mapper.PaymentNotificationMapper;
import org.springframework.stereotype.Service;
import org.springframework.web.client.HttpClientErrorException;
import java.util.UUID;

@Service
public class PaymentNotificationService {
    private static final org.slf4j.Logger log = org.slf4j.LoggerFactory.getLogger(PaymentNotificationService.class);
    private final PaymentNotificationMapper mapper;
    private final OrderClient orderClient;
    private final int maxAttempts;

    public PaymentNotificationService(PaymentNotificationMapper mapper, OrderClient orderClient) {
        this(mapper,orderClient,20);
    }
    @org.springframework.beans.factory.annotation.Autowired
    public PaymentNotificationService(PaymentNotificationMapper mapper, OrderClient orderClient,
            @org.springframework.beans.factory.annotation.Value("${rs.payment.notification.max-attempts:20}") int maxAttempts) {
        this.mapper = mapper;
        this.orderClient = orderClient;
        if(maxAttempts<1 || maxAttempts>1000) throw new IllegalArgumentException("通知重试上限须为 1 到 1000");
        this.maxAttempts=maxAttempts;
    }

    public void processPending() {
        for (Long orderId : mapper.dueOrderIds()) dispatch(orderId);
    }

    public void dispatch(Long orderId) {
        String token = UUID.randomUUID().toString();
        if (mapper.claim(orderId, token) != 1) return;
        var notification = mapper.findByOrderId(orderId);
        if (notification == null) throw new IllegalStateException("支付通知持久记录不存在");
        try {
            orderClient.markPaid(notification.orderId(), notification.provider(), notification.providerTransactionId());
            mapper.complete(orderId, token);
        } catch (RuntimeException failure) {
            // 订单已关闭/金额冲突不能自动重新扣款或强行修改订单，保存待人工核对状态。
            boolean review = failure instanceof HttpClientErrorException http
                    && (http.getStatusCode().value() == 404 || http.getStatusCode().value() == 409);
            review = review || notification.attempts() >= maxAttempts;
            String error = failure.getClass().getSimpleName();
            if (failure instanceof HttpClientErrorException http) error += ":" + http.getStatusCode().value();
            long delay = Math.min(300L, 1L << Math.min(9, notification.attempts()));
            mapper.retry(orderId, token, review ? "REVIEW" : "PENDING", delay, error);
            log.warn("订单 {} 支付通知暂未完成，状态 {}", orderId, review ? "REVIEW" : "PENDING");
        }
    }
}
