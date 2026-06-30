package com.sinrotic.rs.seckill.service;

import com.sinrotic.rs.seckill.domain.dto.SeckillSubmitRequestDTO;
import com.sinrotic.rs.seckill.domain.vo.SeckillSubmitVO;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.boot.autoconfigure.AutoConfigurations;
import org.springframework.boot.jackson.autoconfigure.JacksonAutoConfiguration;
import org.springframework.boot.test.context.runner.ApplicationContextRunner;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.ValueOperations;
import org.springframework.data.redis.core.script.DefaultRedisScript;
import org.springframework.kafka.core.KafkaTemplate;
import org.springframework.kafka.support.SendResult;
import tools.jackson.databind.json.JsonMapper;

import java.util.concurrent.CompletableFuture;
import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyList;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class SeckillServiceTest {

    private StringRedisTemplate redisTemplate;
    private KafkaTemplate<String, String> kafkaTemplate;
    private DefaultRedisScript<Long> preDeductScript;
    private JsonMapper jsonMapper;
    private SeckillService seckillService;

    @BeforeEach
    void setUp() {
        redisTemplate = mock(StringRedisTemplate.class);
        kafkaTemplate = mock(KafkaTemplate.class);
        preDeductScript = mock(DefaultRedisScript.class);
        jsonMapper = new JsonMapper();
        seckillService = new SeckillService(redisTemplate, kafkaTemplate, preDeductScript, jsonMapper);
    }

    @Test
    void serviceBeanLoadsWithBoot4JsonMapperBean() {
        new ApplicationContextRunner()
                .withConfiguration(AutoConfigurations.of(JacksonAutoConfiguration.class))
                .withBean(StringRedisTemplate.class, () -> redisTemplate)
                .withBean(KafkaTemplate.class, () -> kafkaTemplate)
                .withBean(DefaultRedisScript.class, () -> preDeductScript)
                .withUserConfiguration(SeckillService.class)
                .run(context -> assertThat(context)
                        .hasSingleBean(JsonMapper.class)
                        .hasSingleBean(SeckillService.class));
    }

    @Test
    void submitReturnsStockNotEnoughAndDoesNotSendKafkaWhenLuaReturnsNull() {
        when(redisTemplate.execute(any(DefaultRedisScript.class), anyList(), anyString(), anyString()))
                .thenReturn(null);

        SeckillSubmitVO response = seckillService.submit(request());

        assertEquals("req-1", response.requestId());
        assertEquals("STOCK_NOT_ENOUGH", response.status());
        verify(kafkaTemplate, never()).send(anyString(), anyString(), anyString());
    }

    @Test
    void submitReturnsStockNotEnoughAndDoesNotSendKafkaWhenLuaReturnsZero() {
        when(redisTemplate.execute(any(DefaultRedisScript.class), anyList(), anyString(), anyString()))
                .thenReturn(0L);

        SeckillSubmitVO response = seckillService.submit(request());

        assertEquals("STOCK_NOT_ENOUGH", response.status());
        verify(kafkaTemplate, never()).send(anyString(), anyString(), anyString());
    }

    @Test
    void submitReturnsDuplicateAndDoesNotSendKafkaWhenLuaReturnsTwo() {
        when(redisTemplate.execute(any(DefaultRedisScript.class), anyList(), anyString(), anyString()))
                .thenReturn(2L);

        SeckillSubmitVO response = seckillService.submit(request());

        assertEquals("DUPLICATE", response.status());
        verify(kafkaTemplate, never()).send(anyString(), anyString(), anyString());
    }

    @Test
    void submitSendsKafkaAndReturnsProcessingWhenLuaReturnsOne() throws Exception {
        SeckillSubmitRequestDTO request = request();
        when(redisTemplate.execute(any(DefaultRedisScript.class), eq(List.of(
                "seckill:stock:act-1:sku-1",
                "seckill:user:act-1:100"
        )), eq("2"), eq("req-1"))).thenReturn(1L);
        when(kafkaTemplate.send(anyString(), anyString(), anyString()))
                .thenReturn(CompletableFuture.completedFuture(mock(SendResult.class)));

        SeckillSubmitVO response = seckillService.submit(request);

        assertEquals("PROCESSING", response.status());
        verify(kafkaTemplate).send(
                eq("seckill-order-create"),
                eq("req-1"),
                eq(jsonMapper.writeValueAsString(request))
        );
    }

    @Test
    void submitRestoresRedisPreDeductAndRethrowsWhenKafkaSendThrows() {
        ValueOperations<String, String> valueOperations = mock(ValueOperations.class);
        RuntimeException kafkaFailure = new RuntimeException("kafka down");
        when(redisTemplate.execute(any(DefaultRedisScript.class), anyList(), anyString(), anyString()))
                .thenReturn(1L);
        when(redisTemplate.opsForValue()).thenReturn(valueOperations);
        when(kafkaTemplate.send(anyString(), anyString(), anyString())).thenThrow(kafkaFailure);

        RuntimeException thrown = assertThrows(RuntimeException.class, () -> seckillService.submit(request()));

        assertEquals(kafkaFailure, thrown);
        verify(valueOperations).increment("seckill:stock:act-1:sku-1", 2L);
        verify(redisTemplate).delete("seckill:user:act-1:100");
    }

    @Test
    void submitRestoresRedisPreDeductAndRethrowsWhenKafkaFutureAlreadyFailed() {
        ValueOperations<String, String> valueOperations = mock(ValueOperations.class);
        RuntimeException kafkaFailure = new RuntimeException("kafka rejected");
        CompletableFuture<SendResult<String, String>> failed = new CompletableFuture<>();
        failed.completeExceptionally(kafkaFailure);
        when(redisTemplate.execute(any(DefaultRedisScript.class), anyList(), anyString(), anyString()))
                .thenReturn(1L);
        when(redisTemplate.opsForValue()).thenReturn(valueOperations);
        when(kafkaTemplate.send(anyString(), anyString(), anyString())).thenReturn(failed);

        RuntimeException thrown = assertThrows(RuntimeException.class, () -> seckillService.submit(request()));

        assertEquals(kafkaFailure, thrown);
        verify(valueOperations).increment("seckill:stock:act-1:sku-1", 2L);
        verify(redisTemplate).delete("seckill:user:act-1:100");
    }

    @Test
    void submitRestoresRedisPreDeductWhenKafkaFutureFailsLater() {
        ValueOperations<String, String> valueOperations = mock(ValueOperations.class);
        RuntimeException kafkaFailure = new RuntimeException("broker failed later");
        CompletableFuture<SendResult<String, String>> future = new CompletableFuture<>();
        when(redisTemplate.execute(any(DefaultRedisScript.class), anyList(), anyString(), anyString()))
                .thenReturn(1L);
        when(redisTemplate.opsForValue()).thenReturn(valueOperations);
        when(kafkaTemplate.send(anyString(), anyString(), anyString())).thenReturn(future);

        SeckillSubmitVO response = seckillService.submit(request());
        future.completeExceptionally(kafkaFailure);

        assertEquals("PROCESSING", response.status());
        verify(valueOperations).increment("seckill:stock:act-1:sku-1", 2L);
        verify(redisTemplate).delete("seckill:user:act-1:100");
    }

    @Test
    void submitRejectsInvalidQuantityBeforeRedisOrKafka() {
        SeckillSubmitRequestDTO invalid = new SeckillSubmitRequestDTO(
                "req-1",
                100L,
                "act-1",
                "item-1",
                "sku-1",
                0
        );

        assertThrows(IllegalArgumentException.class, () -> seckillService.submit(invalid));

        verify(redisTemplate, never()).execute(any(DefaultRedisScript.class), anyList(), anyString(), anyString());
        verify(kafkaTemplate, never()).send(anyString(), anyString(), anyString());
    }

    @Test
    void submitRejectsBlankItemIdBeforeRedisOrKafka() {
        SeckillSubmitRequestDTO invalid = new SeckillSubmitRequestDTO(
                "req-1",
                100L,
                "act-1",
                " ",
                "sku-1",
                2
        );

        assertThrows(IllegalArgumentException.class, () -> seckillService.submit(invalid));

        verify(redisTemplate, never()).execute(any(DefaultRedisScript.class), anyList(), anyString(), anyString());
        verify(kafkaTemplate, never()).send(anyString(), anyString(), anyString());
    }

    private SeckillSubmitRequestDTO request() {
        return new SeckillSubmitRequestDTO(
                "req-1",
                100L,
                "act-1",
                "item-1",
                "sku-1",
                2
        );
    }
}
