package com.sinrotic.rs.seckill.service;

import com.sinrotic.rs.seckill.domain.dto.SeckillSubmitRequestDTO;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.jdbc.datasource.init.ResourceDatabasePopulator;
import org.springframework.core.io.FileSystemResource;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.script.DefaultRedisScript;
import org.springframework.kafka.core.KafkaTemplate;
import tools.jackson.databind.json.JsonMapper;

import java.time.*;
import java.util.*;
import java.util.concurrent.*;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;
import static org.mockito.ArgumentMatchers.*;

class SeckillServiceTest {
    JdbcTemplate jdbc;
    DataSourceTransactionManager manager;
    StringRedisTemplate redis;
    KafkaTemplate<String,String> kafka;
    SeckillOrderClient orders;
    SeckillInventoryClient inventory;
    SeckillService service;
    Clock clock=Clock.fixed(Instant.parse("2026-09-13T00:00:00Z"),ZoneOffset.UTC);

    @BeforeEach
    @SuppressWarnings("unchecked")
    void setup() {
        var ds=new DriverManagerDataSource("jdbc:h2:mem:"+UUID.randomUUID()+";MODE=MySQL;DB_CLOSE_DELAY=-1;LOCK_TIMEOUT=10000","sa","");
        new ResourceDatabasePopulator(new FileSystemResource("../sql/rs_service_trade_schema.sql"),
                new FileSystemResource("../sql/rs_service_commerce_v1_schema.sql")).execute(ds);
        jdbc=new JdbcTemplate(ds);manager=new DataSourceTransactionManager(ds);
        redis=mock(StringRedisTemplate.class);kafka=mock(KafkaTemplate.class);orders=mock(SeckillOrderClient.class);inventory=mock(SeckillInventoryClient.class);
        when(redis.execute(any(DefaultRedisScript.class),anyList(),anyString())).thenReturn(1L);
        when(orders.offer("item","sku")).thenReturn(new SeckillOrderClient.Offer("sku","item","活动商品",3000L));
        service=new SeckillService(jdbc,manager,redis,kafka,new JsonMapper(),orders,inventory,clock,200);
        service.createActivity(new SeckillService.Activity("activity","item","sku",5,LocalDateTime.now(clock).minusHours(1),LocalDateTime.now(clock).plusHours(1)));
    }
    SeckillSubmitRequestDTO request(String account,String requestId) {
        return new SeckillSubmitRequestDTO(requestId,account,"activity","item","sku",1);
    }
    SeckillService restart() {
        return new SeckillService(jdbc,manager,redis,kafka,new JsonMapper(),orders,inventory,Clock.offset(clock,Duration.ofSeconds(6)),200);
    }
    @Test
    void replayWithNanosecondInputUsesDatabasePrecisionAndDoesNotRequireLiveQuotation() {
        var activity=new SeckillService.Activity("precision","item","sku",3,LocalDateTime.now(clock).minusMinutes(1).withNano(123456789),LocalDateTime.now(clock).plusHours(1).withNano(123456789));
        service.createActivity(activity);
        when(orders.offer("item","sku")).thenThrow(new IllegalStateException("报价服务暂不可用"));
        service.createActivity(activity);
        verify(inventory,times(1)).allocate("precision","sku",3);
        assertThat(service.activity("account","precision").startsAt().getNano()).isEqualTo(123456000);
    }

    @Test
    void unknownAllocationIsRetriedWithSameActivityAndActivityCannotAcceptBeforeReady() {
        doThrow(new org.springframework.web.client.ResourceAccessException("划拨已成功但响应丢失"))
                .doNothing().when(inventory).allocate("pending","sku",3);
        var activity=new SeckillService.Activity("pending","item","sku",3,LocalDateTime.now(clock).minusMinutes(1),LocalDateTime.now(clock).plusHours(1));
        service.createActivity(activity);
        assertThat(service.activity("account","pending").status()).isEqualTo("PREPARING");
        assertThatThrownBy(()->service.submit(new SeckillSubmitRequestDTO("req","account","pending","item","sku",1)))
                .isInstanceOf(org.springframework.web.server.ResponseStatusException.class);
        var later=new SeckillService(jdbc,manager,redis,kafka,new JsonMapper(),orders,inventory,Clock.offset(clock,Duration.ofSeconds(11)),200);
        try { later.maintainAllocations(); } finally { later.close(); }
        assertThat(service.activity("account","pending").inventoryMode()).isEqualTo("ALLOCATED");
        assertThat(service.activity("account","pending").status()).isEqualTo("ACTIVE");
        verify(inventory,times(2)).allocate("pending","sku",3);
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM seckill_activity_v1 WHERE activity_id='pending'",Integer.class)).isOne();
        assertThatThrownBy(()->service.createActivity(new SeckillService.Activity("pending","item","sku",4,activity.startsAt(),activity.endsAt())))
                .isInstanceOf(org.springframework.web.server.ResponseStatusException.class);
    }

    @Test
    void rejectedAllocationRequiresAuditedRecoveryAndEndedActivityWaitsForAcceptedRequests() {
        doThrow(new org.springframework.web.client.HttpClientErrorException(org.springframework.http.HttpStatus.CONFLICT))
                .when(inventory).allocate("failed","sku",3);
        service.createActivity(new SeckillService.Activity("failed","item","sku",3,LocalDateTime.now(clock).minusMinutes(1),LocalDateTime.now(clock).plusHours(1)));
        assertThat(service.taskSummary()).containsEntry("reviewRequired",1L);
        service.retryAllocation("failed",new SeckillService.OperatorAction("operator","补货已完成"));
        doNothing().when(inventory).allocate("failed","sku",3);service.maintainAllocations();
        assertThat(service.activity("account","failed").status()).isEqualTo("ACTIVE");
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM commerce_operation_audit",Integer.class)).isOne();
        service.submit(request("account","req"));
        var later=new SeckillService(jdbc,manager,redis,kafka,new JsonMapper(),orders,inventory,Clock.offset(clock,Duration.ofHours(2)),200);
        try {
            later.maintainAllocations();verify(inventory,never()).close("activity");
            String id=jdbc.queryForObject("SELECT event_id FROM seckill_request_v1",String.class);
            when(orders.result(id,"account")).thenReturn(new SeckillOrderClient.Result(10,"CANCELED","DONE"));later.reconcile();
            jdbc.update("UPDATE seckill_activity_allocation SET next_attempt_at=?",LocalDateTime.now(clock));
            later.maintainAllocations();later.maintainAllocations();verify(inventory,times(1)).close("activity");
            assertThat(jdbc.queryForObject("SELECT status FROM seckill_activity_allocation WHERE activity_id='activity'",String.class)).isEqualTo("CLOSED");
        } finally { later.close(); }
    }

    @Test
    void activePublishLeasePreventsDuplicateSendAndExpiredOwnersCannotCommitLateAcknowledgments() throws Exception {
        service.submit(request("account","req"));
        var entered=new CountDownLatch(1);var resume=new CountDownLatch(1);var calls=new java.util.concurrent.atomic.AtomicInteger();
        when(kafka.send(anyString(),anyString(),anyString())).thenAnswer(invocation -> {
            if(calls.getAndIncrement()==0) {entered.countDown();resume.await(5,TimeUnit.SECONDS);return CompletableFuture.completedFuture(null);}
            return CompletableFuture.failedFuture(new IllegalStateException("新实例发送未确认"));
        });
        var other=restart();
        try(var executor=Executors.newSingleThreadExecutor()) {
            var first=executor.submit(service::dispatch);
            try {
                assertThat(entered.await(2,TimeUnit.SECONDS)).isTrue();other.dispatch();assertThat(calls.get()).isOne();
                jdbc.update("UPDATE commerce_worker_lease SET lease_until=TIMESTAMPADD(SECOND,-1,CURRENT_TIMESTAMP(6)) WHERE worker_type='seckill-publish'");
                other.dispatch();assertThat(calls.get()).isEqualTo(2);
            } finally {resume.countDown();}
            first.get(5,TimeUnit.SECONDS);
        } finally {other.close();}
        assertThat(jdbc.queryForObject("SELECT dispatched FROM seckill_request_v1",Boolean.class)).isFalse();
        assertThat(jdbc.queryForObject("SELECT attempts FROM seckill_request_v1",Integer.class)).isOne();
    }

    @Test
    void oneFailedPublishDoesNotBlockOtherEventsAndRetryKeepsItsId() {
        for(int i=0;i<3;i++) service.submit(request("account-"+i,"req-"+i));
        var first=new java.util.concurrent.atomic.AtomicBoolean(true);
        var failedId=new java.util.concurrent.atomic.AtomicReference<String>();
        when(kafka.send(anyString(),anyString(),anyString())).thenAnswer(invocation -> {
            if(first.getAndSet(false)) {
                failedId.set(invocation.getArgument(1));return CompletableFuture.failedFuture(new IllegalStateException("一次发布未确认"));
            }
            return CompletableFuture.completedFuture(null);
        });
        service.dispatch();
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM seckill_request_v1 WHERE dispatched=TRUE",Integer.class)).isEqualTo(2);
        var restarted=restart();try { restarted.dispatch(); } finally { restarted.close(); }
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM seckill_request_v1 WHERE dispatched=TRUE",Integer.class)).isEqualTo(3);
        assertThat(jdbc.queryForObject("SELECT remaining_quantity FROM seckill_activity_v1",Integer.class)).isEqualTo(2);
        verify(kafka,times(2)).send(eq("checkout-seckill-accepted"),eq(failedId.get()),anyString());
    }

    @Test
    void slowReconciliationDoesNotBlockBoundedPublishingAndBatchCanExceed25() throws Exception {
        jdbc.update("UPDATE seckill_activity_v1 SET total_quantity=40,remaining_quantity=40");
        var concurrent=new SeckillService(jdbc,manager,redis,kafka,new JsonMapper(),orders,inventory,clock,200,10,100,2,2);
        for(int i=0;i<30;i++) concurrent.submit(request("account-"+i,"request-"+i));
        var checking=new CountDownLatch(2);var releaseQueries=new CountDownLatch(1);
        when(orders.result(anyString(),anyString())).thenAnswer(invocation -> {
            checking.countDown();if(!releaseQueries.await(5,TimeUnit.SECONDS)) throw new IllegalStateException("test timeout");return null;
        });
        var sending=new CountDownLatch(2);var releaseSends=new CountDownLatch(1);
        var inFlight=new java.util.concurrent.atomic.AtomicInteger();var maximum=new java.util.concurrent.atomic.AtomicInteger();
        when(kafka.send(anyString(),anyString(),anyString())).thenAnswer(invocation -> {
            int count=inFlight.incrementAndGet();maximum.accumulateAndGet(count,Math::max);sending.countDown();
            try { if(!releaseSends.await(5,TimeUnit.SECONDS)) throw new IllegalStateException("test timeout"); }
            finally { inFlight.decrementAndGet(); }
            return CompletableFuture.completedFuture(null);
        });
        try(var pool=Executors.newFixedThreadPool(2)) {
            var check=pool.submit(concurrent::reconcile);
            try {
                assertThat(checking.await(5,TimeUnit.SECONDS)).isTrue();
                var send=pool.submit(concurrent::dispatch);
                try { assertThat(sending.await(5,TimeUnit.SECONDS)).isTrue();concurrent.dispatch(); }
                finally { releaseSends.countDown(); }
                send.get(5,TimeUnit.SECONDS);
                assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM seckill_request_v1 WHERE dispatched=TRUE",Integer.class)).isEqualTo(30);
            } finally { releaseSends.countDown();releaseQueries.countDown(); }
            check.get(5,TimeUnit.SECONDS);
        } finally { concurrent.close(); }
        assertThat(maximum.get()).isEqualTo(2);
        verify(kafka,times(30)).send(anyString(),anyString(),anyString());
        assertThat(jdbc.queryForObject("SELECT remaining_quantity FROM seckill_activity_v1",Integer.class)).isEqualTo(10);
    }

    @Test
    void acceptanceAndQuotaCommitBeforeAnyKafkaSendAndSurviveRestart() {
        assertThat(service.submit(request("account","req")).status()).isEqualTo("PROCESSING");
        verifyNoInteractions(kafka);
        assertThat(jdbc.queryForObject("SELECT remaining_quantity FROM seckill_activity_v1",Integer.class)).isEqualTo(4);
        when(kafka.send(anyString(),anyString(),anyString())).thenReturn(CompletableFuture.completedFuture(null));
        restart().dispatch();
        assertThat(jdbc.queryForObject("SELECT dispatched FROM seckill_request_v1",Boolean.class)).isTrue();
        verify(kafka).send(eq("checkout-seckill-accepted"),anyString(),contains("\"accountId\":\"account\""));
    }

    @Test
    void uncertainSendRetriesSameEventWithoutRefundingQuota() {
        service.submit(request("account","req"));
        when(kafka.send(anyString(),anyString(),anyString())).thenReturn(CompletableFuture.failedFuture(new IllegalStateException("broker response lost")));
        service.dispatch();
        assertThat(jdbc.queryForObject("SELECT remaining_quantity FROM seckill_activity_v1",Integer.class)).isEqualTo(4);
        String eventId=jdbc.queryForObject("SELECT event_id FROM seckill_request_v1",String.class);
        when(kafka.send(anyString(),anyString(),anyString())).thenReturn(CompletableFuture.completedFuture(null));
        restart().dispatch();
        verify(kafka,times(2)).send(eq("checkout-seckill-accepted"),eq(eventId),anyString());
    }

    @Test
    void concurrentAcceptancesDoNotExceedQuotaAndBusinessUniquenessSurvivesRedisLoss() throws Exception {
        try(var pool=Executors.newFixedThreadPool(8)) {
            var tasks=new ArrayList<Callable<String>>();
            for(int i=0;i<40;i++) { String account="account-"+i; tasks.add(() -> service.submit(request(account,"req")).status()); }
            int accepted=0;
            for(var result:pool.invokeAll(tasks)) if("PROCESSING".equals(result.get())) accepted++;
            assertThat(accepted).isEqualTo(5);
        }
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM seckill_request_v1",Integer.class)).isEqualTo(5);
        String account=jdbc.queryForObject("SELECT account_id FROM seckill_request_v1 LIMIT 1",String.class);
        assertThat(restart().submit(request(account,"different")).status()).isEqualTo("DUPLICATE");
        assertThat(jdbc.queryForObject("SELECT remaining_quantity FROM seckill_activity_v1",Integer.class)).isZero();
    }

    @Test
    void compensationWaitsForResourceReleaseAndRefundsOnlyOnce() {
        service.submit(request("account","req"));
        String eventId=jdbc.queryForObject("SELECT event_id FROM seckill_request_v1",String.class);
        when(orders.result(eventId,"account")).thenReturn(new SeckillOrderClient.Result(10L,"CANCELED","RELEASE_STOCK"));
        service.reconcile();
        assertThat(jdbc.queryForObject("SELECT remaining_quantity FROM seckill_activity_v1",Integer.class)).isEqualTo(4);
        when(orders.result(eventId,"account")).thenReturn(new SeckillOrderClient.Result(10L,"CANCELED","DONE"));
        var restarted=restart();restarted.reconcile();restarted.reconcile();
        assertThat(jdbc.queryForObject("SELECT remaining_quantity FROM seckill_activity_v1",Integer.class)).isEqualTo(5);
        assertThat(restarted.result("account","req").status()).isEqualTo("CANCELED");
        assertThatThrownBy(() -> restarted.result("another","req")).isInstanceOf(org.springframework.web.server.ResponseStatusException.class);
    }

    @Test
    void requestReplayReturnsOriginalAndCannotChangeActivityOrQuantity() {
        service.submit(request("account","req"));
        assertThat(service.submit(request("account","req")).status()).isEqualTo("PROCESSING");
        assertThatThrownBy(() -> service.submit(new SeckillSubmitRequestDTO("req","account","other","item","sku",1)))
                .isInstanceOf(org.springframework.web.server.ResponseStatusException.class);
        assertThatThrownBy(() -> service.submit(new SeckillSubmitRequestDTO("req","account","activity","item","sku",2)))
                .isInstanceOf(org.springframework.web.server.ResponseStatusException.class);
    }

    @Test
    void delayedReconcilerCannotOverwriteTerminalOrWaitingState() throws Exception {
        service.submit(request("account","req"));
        String id=jdbc.queryForObject("SELECT event_id FROM seckill_request_v1",String.class);
        var reading=new CountDownLatch(1);var resume=new CountDownLatch(1);
        var calls=new java.util.concurrent.atomic.AtomicInteger();
        when(orders.result(id,"account")).thenAnswer(invocation -> {
            if(calls.getAndIncrement()==0) {
                reading.countDown();
                if(!resume.await(10,TimeUnit.SECONDS)) throw new IllegalStateException("test timeout");
                return new SeckillOrderClient.Result(10L,"WAITING_PAYMENT","READY");
            }
            return new SeckillOrderClient.Result(10L,"CANCELED","DONE");
        });
        try(var pool=Executors.newSingleThreadExecutor()) {
            var slow=pool.submit(service::reconcile);
            try {
                assertThat(reading.await(5,TimeUnit.SECONDS)).isTrue();
                // 另一个实例先看到取消结果；同一实例现在避免重复调度同一批任务。
                // 模拟实例暂停超过租约；旧查询返回时必须被领取标识隔离。
                jdbc.update("UPDATE commerce_worker_lease SET lease_until=TIMESTAMPADD(SECOND,-1,CURRENT_TIMESTAMP(6)) WHERE worker_type='seckill-reconcile'");
                var secondInstance=new SeckillService(jdbc,manager,redis,kafka,new JsonMapper(),orders,inventory,clock,200);
                try { secondInstance.reconcile(); } finally { secondInstance.close(); }
            } finally { resume.countDown(); }
            slow.get(5,TimeUnit.SECONDS);
        }
        assertThat(service.result("account","req").status()).isEqualTo("CANCELED");
        assertThat(jdbc.queryForObject("SELECT remaining_quantity FROM seckill_activity_v1",Integer.class)).isEqualTo(5);
        jdbc.update("UPDATE seckill_request_v1 SET status='WAITING_PAYMENT',next_attempt_at=?",LocalDateTime.now(clock));
        when(orders.result(id,"account")).thenReturn(new SeckillOrderClient.Result(10L,"CREATING","LOCK_STOCK"));
        service.reconcile();
        assertThat(service.result("account","req").status()).isEqualTo("WAITING_PAYMENT");
    }

    @Test
    void activityViewsHaveUtcTimesAndAccountScopedParticipation() {
        service.submit(request("account","req"));
        var activity=service.activity("account","activity");
        assertThat(activity.status()).isEqualTo("ACTIVE");
        assertThat(activity.remainingQuantity()).isEqualTo(4);
        assertThat(activity.unitPrice()).isEqualTo(3000);
        assertThat(activity.serverTime()).isEqualTo(clock.instant());
        assertThat(activity.participation().requestId()).isEqualTo("req");
        assertThat(service.activity("other","activity").participation()).isNull();
        assertThat(service.activities("account","item")).hasSize(1);
        assertThat(service.activities("account","other-item")).isEmpty();
        jdbc.update("UPDATE seckill_activity_v1 SET starts_at=?",LocalDateTime.now(clock).plusMinutes(10));
        assertThat(service.activity("other","activity").status()).isEqualTo("NOT_STARTED");
        assertThat(service.submit(request("other","early")).status()).isEqualTo("NOT_STARTED");
        jdbc.update("UPDATE seckill_activity_v1 SET starts_at=?,ends_at=?",LocalDateTime.now(clock).minusHours(2),LocalDateTime.now(clock).minusHours(1));
        assertThat(service.activity("other","activity").status()).isEqualTo("ENDED");
        assertThat(service.submit(request("other","late")).status()).isEqualTo("ENDED");
        assertThat(service.activities("account","item").getFirst().status()).isEqualTo("ENDED");
        assertThat(jdbc.queryForObject("SELECT remaining_quantity FROM seckill_activity_v1",Integer.class)).isEqualTo(4);
    }

    @Test
    void missingOrdersRedriveWithOriginalEventThenParkAndCanBeResumed() {
        service.submit(request("account","req"));
        String id=jdbc.queryForObject("SELECT event_id FROM seckill_request_v1",String.class);
        when(kafka.send(anyString(),anyString(),anyString())).thenReturn(CompletableFuture.completedFuture(null));
        service.dispatch();
        var later=new SeckillService(jdbc,manager,redis,kafka,new JsonMapper(),orders,inventory,Clock.offset(clock,Duration.ofSeconds(65)),200,1);
        later.reconcile();
        assertThat(jdbc.queryForObject("SELECT dispatched FROM seckill_request_v1",Boolean.class)).isFalse();
        var again=new SeckillService(jdbc,manager,redis,kafka,new JsonMapper(),orders,inventory,Clock.offset(clock,Duration.ofSeconds(71)),200,1);
        again.dispatch();
        verify(kafka,times(2)).send(eq("checkout-seckill-accepted"),eq(id),anyString());
        var parked=new SeckillService(jdbc,manager,redis,kafka,new JsonMapper(),orders,inventory,Clock.offset(clock,Duration.ofSeconds(140)),200,1);
        parked.reconcile();
        assertThat(parked.result("account","req").status()).isEqualTo("REVIEW_REQUIRED");
        assertThat(parked.taskSummary()).containsEntry("reviewRequired",1L);
        assertThat(parked.stalledTasks(60)).hasSize(1);
        parked.dispatch();
        verify(kafka,times(2)).send(anyString(),anyString(),anyString());
        var action=new SeckillService.OperatorAction("operator","下游故障已排除，按原事件恢复");
        parked.retryTask(id,action);parked.dispatch();
        verify(kafka,times(3)).send(eq("checkout-seckill-accepted"),eq(id),anyString());
        assertThat(jdbc.queryForObject("SELECT remaining_quantity FROM seckill_activity_v1",Integer.class)).isEqualTo(4);
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM commerce_operation_audit",Integer.class)).isOne();
        assertThatThrownBy(() -> parked.retryTask(id,action)).isInstanceOf(org.springframework.web.server.ResponseStatusException.class);
    }

    @Test
    void lateOrderCanResolveReviewWithoutRefundAndRedisFailureDoesNotLoseReplay() {
        service.submit(request("account","req"));
        String id=jdbc.queryForObject("SELECT event_id FROM seckill_request_v1",String.class);
        jdbc.update("UPDATE seckill_request_v1 SET status='REVIEW_REQUIRED' WHERE event_id=?",id);
        when(orders.result(id,"account")).thenReturn(new SeckillOrderClient.Result(10L,"PAID","DONE"));
        service.reconcile();
        assertThat(service.result("account","req").status()).isEqualTo("PAID");
        assertThat(jdbc.queryForObject("SELECT remaining_quantity FROM seckill_activity_v1",Integer.class)).isEqualTo(4);
        when(redis.execute(any(DefaultRedisScript.class),anyList(),anyString())).thenThrow(new org.springframework.dao.DataAccessResourceFailureException("offline"));
        assertThat(service.submit(request("account","req")).status()).isEqualTo("PAID");
        assertThatThrownBy(() -> service.submit(request("other","req"))).isInstanceOf(org.springframework.web.server.ResponseStatusException.class);
        assertThatThrownBy(() -> service.retryTask(id,new SeckillService.OperatorAction("operator","核对"))).isInstanceOf(org.springframework.web.server.ResponseStatusException.class);
    }

    @Test
    void knownTerminalOrderStopsRepublishingAfterUnknownKafkaAcknowledgment() {
        service.submit(request("account","req"));
        String id=jdbc.queryForObject("SELECT event_id FROM seckill_request_v1",String.class);
        when(kafka.send(anyString(),anyString(),anyString())).thenReturn(CompletableFuture.failedFuture(new IllegalStateException("ack lost")));
        service.dispatch();
        when(orders.result(id,"account")).thenReturn(new SeckillOrderClient.Result(10L,"PAID","DONE"));
        var later=restart();later.reconcile();later.dispatch();
        assertThat(later.result("account","req").status()).isEqualTo("PAID");
        verify(kafka,times(1)).send(anyString(),anyString(),anyString());
        assertThat(later.taskSummary()).containsEntry("unpublished",0L);
    }
}
