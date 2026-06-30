package com.sinrotic.rs.seckill.service;

import com.sinrotic.rs.seckill.domain.dto.SeckillSubmitRequestDTO;
import com.sinrotic.rs.seckill.domain.vo.SeckillSubmitVO;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.script.DefaultRedisScript;
import org.springframework.kafka.core.KafkaTemplate;
import org.springframework.kafka.support.SendResult;
import org.springframework.stereotype.Service;
import tools.jackson.core.JacksonException;
import tools.jackson.databind.json.JsonMapper;

import java.util.concurrent.CancellationException;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.CompletionException;
import java.util.List;

@Service
public class SeckillService {

    private static final String STOCK_NOT_ENOUGH = "STOCK_NOT_ENOUGH";
    private static final String DUPLICATE = "DUPLICATE";
    private static final String PROCESSING = "PROCESSING";
    private static final String ORDER_CREATE_TOPIC = "seckill-order-create";

    private final StringRedisTemplate redisTemplate;
    private final KafkaTemplate<String, String> kafkaTemplate;
    private final DefaultRedisScript<Long> preDeductScript;
    private final JsonMapper jsonMapper;

    public SeckillService(
            StringRedisTemplate redisTemplate,
            KafkaTemplate<String, String> kafkaTemplate,
            DefaultRedisScript<Long> preDeductScript,
            JsonMapper jsonMapper
    ) {
        this.redisTemplate = redisTemplate;
        this.kafkaTemplate = kafkaTemplate;
        this.preDeductScript = preDeductScript;
        this.jsonMapper = jsonMapper;
    }

    public SeckillSubmitVO submit(SeckillSubmitRequestDTO request) {
        validate(request);
        String stockKey = stockKey(request.activityId(), request.skuId());
        String userKey = userKey(request.activityId(), request.accountId());
        String payload = toJson(request);

        Long result = redisTemplate.execute(
                preDeductScript,
                List.of(stockKey, userKey),
                String.valueOf(request.quantity()),
                request.requestId()
        );
        if (result == null || result == 0L) {
            return new SeckillSubmitVO(request.requestId(), STOCK_NOT_ENOUGH);
        }
        if (result == 2L) {
            return new SeckillSubmitVO(request.requestId(), DUPLICATE);
        }
        if (result != 1L) {
            throw new IllegalStateException("Unexpected seckill pre-deduct result: " + result);
        }

        CompletableFuture<SendResult<String, String>> sendFuture = sendOrderCreateEvent(
                request,
                payload,
                stockKey,
                userKey
        );
        if (sendFuture.isCompletedExceptionally()) {
            throw compensateAndUnwrapFailedSend(sendFuture, stockKey, userKey, request.quantity());
        }
        sendFuture.whenComplete((resultValue, failure) -> {
            if (failure != null) {
                compensatePreDeduct(stockKey, userKey, request.quantity());
            }
        });
        return new SeckillSubmitVO(request.requestId(), PROCESSING);
    }

    private CompletableFuture<SendResult<String, String>> sendOrderCreateEvent(
            SeckillSubmitRequestDTO request,
            String payload,
            String stockKey,
            String userKey
    ) {
        try {
            return kafkaTemplate.send(ORDER_CREATE_TOPIC, request.requestId(), payload);
        } catch (RuntimeException ex) {
            compensatePreDeduct(stockKey, userKey, request.quantity());
            throw ex;
        }
    }

    private RuntimeException compensateAndUnwrapFailedSend(
            CompletableFuture<SendResult<String, String>> sendFuture,
            String stockKey,
            String userKey,
            Integer quantity
    ) {
        try {
            sendFuture.join();
            return new IllegalStateException("Kafka send failed without failure cause");
        } catch (CompletionException ex) {
            compensatePreDeduct(stockKey, userKey, quantity);
            Throwable cause = ex.getCause();
            if (cause instanceof RuntimeException runtimeException) {
                return runtimeException;
            }
            return new IllegalStateException("Kafka send failed", cause);
        } catch (CancellationException ex) {
            compensatePreDeduct(stockKey, userKey, quantity);
            return ex;
        }
    }

    private void compensatePreDeduct(String stockKey, String userKey, Integer quantity) {
        redisTemplate.opsForValue().increment(stockKey, quantity.longValue());
        redisTemplate.delete(userKey);
    }

    private void validate(SeckillSubmitRequestDTO request) {
        if (request == null) {
            throw new IllegalArgumentException("request is required");
        }
        if (isBlank(request.requestId())) {
            throw new IllegalArgumentException("requestId is required");
        }
        if (request.accountId() == null || request.accountId() <= 0) {
            throw new IllegalArgumentException("accountId is required");
        }
        if (isBlank(request.activityId())) {
            throw new IllegalArgumentException("activityId is required");
        }
        if (isBlank(request.itemId())) {
            throw new IllegalArgumentException("itemId is required");
        }
        if (isBlank(request.skuId())) {
            throw new IllegalArgumentException("skuId is required");
        }
        if (request.quantity() == null || request.quantity() <= 0) {
            throw new IllegalArgumentException("quantity must be greater than 0");
        }
    }

    private boolean isBlank(String value) {
        return value == null || value.isBlank();
    }

    private String stockKey(String activityId, String skuId) {
        return "seckill:stock:" + activityId + ":" + skuId;
    }

    private String userKey(String activityId, Long accountId) {
        return "seckill:user:" + activityId + ":" + accountId;
    }

    private String toJson(SeckillSubmitRequestDTO request) {
        try {
            return jsonMapper.writeValueAsString(request);
        } catch (JacksonException ex) {
            throw new IllegalStateException("Failed to serialize seckill submit request", ex);
        }
    }
}
