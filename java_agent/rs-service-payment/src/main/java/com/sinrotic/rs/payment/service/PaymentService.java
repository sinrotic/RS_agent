package com.sinrotic.rs.payment.service;

import com.sinrotic.rs.payment.client.OrderClient;
import com.sinrotic.rs.payment.domain.dto.CreatePaymentRequestDTO;
import com.sinrotic.rs.payment.domain.dto.PaymentCallbackDTO;
import com.sinrotic.rs.payment.domain.entity.PaymentOrder;
import com.sinrotic.rs.payment.domain.vo.PaymentPrepayVO;
import com.sinrotic.rs.payment.mapper.PaymentOrderMapper;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.stereotype.Service;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.HexFormat;
import java.util.Objects;

@Service
public class PaymentService {

    public static final String STATUS_WAITING_PAY = "WAITING_PAY";
    public static final String STATUS_PAID = "PAID";
    private static final String MOCK_PROVIDER = "mock";
    private static final String MOCK_SIGNATURE = "mock-signature";

    private final PaymentOrderMapper paymentOrderMapper;
    private final PaymentTransitionService paymentTransitionService;
    private final OrderClient orderClient;
    private final IdGenerator idGenerator;

    public PaymentService(
            PaymentOrderMapper paymentOrderMapper,
            PaymentTransitionService paymentTransitionService,
            OrderClient orderClient,
            IdGenerator idGenerator
    ) {
        this.paymentOrderMapper = paymentOrderMapper;
        this.paymentTransitionService = paymentTransitionService;
        this.orderClient = orderClient;
        this.idGenerator = idGenerator;
    }

    public PaymentPrepayVO createPrepay(CreatePaymentRequestDTO request) {
        CreatePaymentRequestDTO normalized = validatePrepayRequest(request);
        long paymentId = idGenerator.nextId();
        int inserted;
        try {
            inserted = paymentOrderMapper.insertPayment(
                    paymentId,
                    normalized.orderId(),
                    normalized.provider(),
                    normalized.amount(),
                    STATUS_WAITING_PAY
            );
        } catch (DuplicateKeyException duplicate) {
            return resolveDuplicatePrepay(normalized, duplicate);
        }
        if (inserted != 1) {
            throw new PaymentServiceException("payment insert failed");
        }
        return new PaymentPrepayVO(paymentId, normalized.orderId(), normalized.provider(), STATUS_WAITING_PAY);
    }

    public void handleCallback(PaymentCallbackDTO request) {
        PaymentCallbackDTO normalized = validateCallbackRequest(request);
        String payloadHash = sha256Hex(normalized.rawPayload());
        OrderPaidMessage orderPaidMessage = paymentTransitionService.recordPaidCallback(
                normalized.provider(),
                normalized.providerTransactionId(),
                normalized.orderId(),
                normalized.amount(),
                payloadHash
        );
        if (orderPaidMessage != null) {
            orderClient.markPaid(
                    orderPaidMessage.orderId(),
                    orderPaidMessage.provider(),
                    orderPaidMessage.providerTransactionId()
            );
        }
    }

    private CreatePaymentRequestDTO validatePrepayRequest(CreatePaymentRequestDTO request) {
        if (request == null) {
            throw new PaymentServiceException("request is required");
        }
        if (request.orderId() == null) {
            throw new PaymentServiceException("orderId is required");
        }
        if (request.accountId() == null) {
            throw new PaymentServiceException("accountId is required");
        }
        if (request.amount() == null || request.amount() <= 0) {
            throw new PaymentServiceException("amount must be positive");
        }
        String provider = validateMockProvider(request.provider());
        return new CreatePaymentRequestDTO(request.orderId(), request.accountId(), request.amount(), provider);
    }

    private PaymentPrepayVO resolveDuplicatePrepay(
            CreatePaymentRequestDTO normalized,
            DuplicateKeyException duplicate
    ) {
        PaymentOrder existing = paymentOrderMapper.findByOrderId(normalized.orderId());
        if (existing == null
                || !Objects.equals(normalized.provider(), existing.getProvider())
                || !Objects.equals(normalized.amount(), existing.getAmount())) {
            throw new PaymentServiceException("conflicting payment order", duplicate);
        }
        return new PaymentPrepayVO(
                existing.getPaymentId(),
                existing.getOrderId(),
                existing.getProvider(),
                existing.getStatus()
        );
    }

    private PaymentCallbackDTO validateCallbackRequest(PaymentCallbackDTO request) {
        if (request == null) {
            throw new PaymentServiceException("request is required");
        }
        String provider = validateMockProvider(request.provider());
        String providerTransactionId = requireText(request.providerTransactionId(), "providerTransactionId");
        if (request.orderId() == null) {
            throw new PaymentServiceException("orderId is required");
        }
        if (request.amount() == null || request.amount() <= 0) {
            throw new PaymentServiceException("amount must be positive");
        }
        String signature = requireText(request.signature(), "signature");
        if (!MOCK_SIGNATURE.equals(signature)) {
            throw new PaymentServiceException("signature is invalid");
        }
        String rawPayload = requireText(request.rawPayload(), "rawPayload");
        return new PaymentCallbackDTO(
                provider,
                providerTransactionId,
                request.orderId(),
                request.amount(),
                signature,
                rawPayload
        );
    }

    private String validateMockProvider(String value) {
        String provider = requireText(value, "provider");
        if (!MOCK_PROVIDER.equalsIgnoreCase(provider)) {
            throw new PaymentServiceException("provider is invalid");
        }
        return MOCK_PROVIDER;
    }

    private String requireText(String value, String fieldName) {
        String normalized = trimToNull(value);
        if (normalized == null) {
            throw new PaymentServiceException(fieldName + " is required");
        }
        return normalized;
    }

    private String trimToNull(String value) {
        if (value == null || value.isBlank()) {
            return null;
        }
        return value.trim();
    }

    private String sha256Hex(String value) {
        try {
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            byte[] hash = digest.digest(value.getBytes(StandardCharsets.UTF_8));
            return HexFormat.of().formatHex(hash);
        } catch (NoSuchAlgorithmException ex) {
            throw new PaymentServiceException("SHA-256 is not available", ex);
        }
    }
}
