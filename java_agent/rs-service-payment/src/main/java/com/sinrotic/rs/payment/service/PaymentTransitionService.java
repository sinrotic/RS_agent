package com.sinrotic.rs.payment.service;

import com.sinrotic.rs.payment.domain.entity.PaymentCallback;
import com.sinrotic.rs.payment.domain.entity.PaymentOrder;
import com.sinrotic.rs.payment.mapper.PaymentCallbackMapper;
import com.sinrotic.rs.payment.mapper.PaymentOrderMapper;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.Objects;

@Service
public class PaymentTransitionService {

    private final PaymentOrderMapper paymentOrderMapper;
    private final PaymentCallbackMapper paymentCallbackMapper;

    public PaymentTransitionService(PaymentOrderMapper paymentOrderMapper, PaymentCallbackMapper paymentCallbackMapper) {
        this.paymentOrderMapper = paymentOrderMapper;
        this.paymentCallbackMapper = paymentCallbackMapper;
    }

    @Transactional(rollbackFor = Exception.class)
    public OrderPaidMessage recordPaidCallback(
            String provider,
            String providerTransactionId,
            Long orderId,
            Long amount,
            String payloadHash
    ) {
        insertOrValidateDuplicateCallback(provider, providerTransactionId, orderId, amount, payloadHash);
        int updated = paymentOrderMapper.markPaid(orderId, provider, amount, providerTransactionId);
        if (updated == 0) {
            return resolveUnchangedPaymentOrder(provider, providerTransactionId, orderId, amount);
        }
        return new OrderPaidMessage(orderId, provider, providerTransactionId);
    }

    private OrderPaidMessage resolveUnchangedPaymentOrder(
            String provider,
            String providerTransactionId,
            Long orderId,
            Long amount
    ) {
        PaymentOrder paymentOrder = paymentOrderMapper.findByOrderId(orderId);
        if (paymentOrder == null) {
            throw new PaymentServiceException("conflicting payment state");
        }

        if (Objects.equals(PaymentService.STATUS_PAID, paymentOrder.getStatus())) {
            if (Objects.equals(provider, paymentOrder.getProvider())
                    && Objects.equals(providerTransactionId, paymentOrder.getProviderTransactionId())
                    && Objects.equals(amount, paymentOrder.getAmount())) {
                return new OrderPaidMessage(orderId, provider, providerTransactionId);
            }
            throw new PaymentServiceException("conflicting paid payment order");
        }

        if (Objects.equals(PaymentService.STATUS_WAITING_PAY, paymentOrder.getStatus())
                && (!Objects.equals(provider, paymentOrder.getProvider())
                || !Objects.equals(amount, paymentOrder.getAmount()))) {
            throw new PaymentServiceException("payment callback does not match waiting payment order");
        }

        throw new PaymentServiceException("conflicting payment state");
    }

    private void insertOrValidateDuplicateCallback(
            String provider,
            String providerTransactionId,
            Long orderId,
            Long amount,
            String payloadHash
    ) {
        try {
            paymentCallbackMapper.insertCallback(
                    provider,
                    providerTransactionId,
                    orderId,
                    amount,
                    PaymentService.STATUS_PAID,
                    payloadHash
            );
        } catch (DuplicateKeyException duplicate) {
            PaymentCallback existing =
                    paymentCallbackMapper.findByProviderTransaction(provider, providerTransactionId);
            if (!matchesPaidCallback(existing, provider, providerTransactionId, orderId, amount, payloadHash)) {
                throw new PaymentServiceException("conflicting duplicate payment callback", duplicate);
            }
        }
    }

    private boolean matchesPaidCallback(
            PaymentCallback existing,
            String provider,
            String providerTransactionId,
            Long orderId,
            Long amount,
            String payloadHash
    ) {
        return existing != null
                && Objects.equals(provider, existing.getProvider())
                && Objects.equals(providerTransactionId, existing.getProviderTransactionId())
                && Objects.equals(orderId, existing.getOrderId())
                && Objects.equals(amount, existing.getAmount())
                && Objects.equals(PaymentService.STATUS_PAID, existing.getStatus())
                && Objects.equals(payloadHash, existing.getPayloadHash());
    }
}
