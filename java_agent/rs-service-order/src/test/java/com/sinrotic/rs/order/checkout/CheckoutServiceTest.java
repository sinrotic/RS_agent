package com.sinrotic.rs.order.checkout;

import com.sinrotic.rs.order.client.InventoryClient;
import com.sinrotic.rs.promotion.PromotionService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.jdbc.datasource.init.ResourceDatabasePopulator;
import org.springframework.core.io.FileSystemResource;
import org.springframework.http.HttpStatus;
import org.springframework.web.client.HttpClientErrorException;
import org.springframework.web.server.ResponseStatusException;

import java.time.*;
import java.util.*;
import java.util.concurrent.*;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;

class CheckoutServiceTest {
    JdbcTemplate jdbc;
    DataSourceTransactionManager manager;
    InventoryClient inventory;
    PromotionService coupons;
    PromotionClient promotion;
    CheckoutService service;
    Clock clock = Clock.fixed(Instant.parse("2026-09-13T00:00:00Z"),ZoneOffset.UTC);
    String couponId;

    @BeforeEach
    void setup() {
        var ds = new DriverManagerDataSource("jdbc:h2:mem:"+UUID.randomUUID()+";MODE=MySQL;DB_CLOSE_DELAY=-1;LOCK_TIMEOUT=10000","sa","");
        new ResourceDatabasePopulator(new FileSystemResource("../sql/rs_service_trade_schema.sql"),
                new FileSystemResource("../sql/rs_service_commerce_v1_schema.sql")).execute(ds);
        jdbc = new JdbcTemplate(ds); manager = new DataSourceTransactionManager(ds);
        jdbc.update("INSERT INTO checkout_offer(sku_id,item_id,item_title,unit_price) VALUES ('sku','item','测试商品',3000)");
        coupons = new PromotionService(jdbc,manager,clock);
        var now = LocalDateTime.now(clock);
        coupons.createCampaign(new PromotionService.Campaign("campaign","满 20 减 5",null,10,10,2000,500,
                now.minusHours(1),now.plusHours(1),now.plusDays(1)));
        couponId = coupons.claim("account","campaign","claim").couponId();
        promotion = spy(new PromotionClient() {
            public long lock(long orderId,String id,String account,String item,long amount) {
                try { return coupons.lock(new PromotionService.LockRequest(orderId,id,account,item,amount)).discountAmount(); }
                catch(ResponseStatusException ex) { throw new HttpClientErrorException(ex.getStatusCode(),ex.getReason()); }
            }
            public void confirm(long orderId,String id) { coupons.finish(orderId,id,true); }
            public void release(long orderId,String id) { coupons.finish(orderId,id,false); }
            public void cancel(long orderId,String id,String account,String item,long amount) {
                coupons.cancel(new PromotionService.LockRequest(orderId,id,account,item,amount));
            }
        });
        inventory = mock(InventoryClient.class);
        service = new CheckoutService(jdbc,manager,inventory,promotion,clock);
    }
    CheckoutService.CreateRequest request(String requestId,String coupon) {
        return new CheckoutService.CreateRequest(requestId,"item","sku",1,coupon,"session","delivery");
    }
    long create() { return service.create("account","profile",request("request",couponId)).orderId(); }

    @Test
    void acceptedOrdersUseFrozenActivityPoolForEveryInventoryOperation() {
        var request=request("event",null);
        long id=service.createAccepted("account",request,new CheckoutService.Offer("sku","item","活动价",3000),"activity").orderId();
        service.process(id);verify(inventory).activity("LOCK","activity",id,"sku",1);
        verify(inventory,never()).lock(anyString(),anyLong(),anyString(),anyInt());
        assertThatThrownBy(()->service.createAccepted("account",request,new CheckoutService.Offer("sku","item","活动价",3000),"other"))
                .isInstanceOf(ResponseStatusException.class);
        service.cancel("account",id);service.process(id);verify(inventory).activity("RELEASE","activity",id,"sku",1);
        assertThat(service.get("account",id).phase()).isEqualTo("DONE");
    }

    @Test
    void otherInstanceCannotRunClaimedOrderAndCanReclaimAnExpiredLease() throws Exception {
        long id=service.create("account",null,request("lease",null)).orderId();
        var entered=new CountDownLatch(1);var resume=new CountDownLatch(1);var calls=new java.util.concurrent.atomic.AtomicInteger();
        doAnswer(invocation -> {if(calls.getAndIncrement()==0) {entered.countDown();resume.await(5,TimeUnit.SECONDS);}return null;})
                .when(inventory).lock(anyString(),anyLong(),anyString(),anyInt());
        var other=new CheckoutService(jdbc,manager,inventory,promotion,clock);
        try(var executor=Executors.newSingleThreadExecutor()) {
            var first=executor.submit(()->service.process(id));
            try {
                assertThat(entered.await(2,TimeUnit.SECONDS)).isTrue();other.process(id);assertThat(calls.get()).isOne();
                jdbc.update("UPDATE commerce_worker_lease SET lease_until=TIMESTAMPADD(SECOND,-1,CURRENT_TIMESTAMP(6)) WHERE worker_type='checkout'");
                other.process(id);assertThat(calls.get()).isEqualTo(2);
                service.cancel("account",id);other.process(id);
            } finally {resume.countDown();}
            first.get(5,TimeUnit.SECONDS);
        } finally {other.close();}
        assertThat(service.get("account",id).status()).isEqualTo("CANCELED");
        assertThat(service.get("account",id).phase()).isEqualTo("DONE");
    }

    @Test
    void paidStockConflictPausesAndAuditedResumeUsesOriginalKey() {
        long id=create();service.process(id);service.paid(id);
        doThrow(new HttpClientErrorException(HttpStatus.CONFLICT)).when(inventory).confirm("checkout:"+id+":confirm",id,"sku",1);
        service.process(id);
        assertThat(service.get("account",id).status()).isEqualTo("PAID");
        assertThat(service.get("account",id).phase()).isEqualTo("REVIEW_CONFIRM_STOCK");
        assertThat(service.taskSummary()).containsEntry("reviewRequired",1L);
        assertThat(service.stalledTasks(1200)).hasSize(1);
        service.processPending();service.process(id);
        verify(inventory,times(1)).confirm("checkout:"+id+":confirm",id,"sku",1);
        service.retryTask(id,new CheckoutService.OperatorAction("operator","库存预留已核对"));
        doNothing().when(inventory).confirm("checkout:"+id+":confirm",id,"sku",1);
        service.process(id);
        assertThat(service.get("account",id).phase()).isEqualTo("DONE");
        assertThat(coupons.wallet("account").getFirst().status()).isEqualTo("USED");
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM commerce_operation_audit",Integer.class)).isOne();
        assertThatThrownBy(()->service.retryTask(id,new CheckoutService.OperatorAction("operator","再重试"))).isInstanceOf(ResponseStatusException.class);
        assertThat(service.taskSummary()).containsEntry("pending",0L);
    }

    @Test
    void pausedCreatingOrderStillExpiresAndReleasesItsResources() {
        service=new CheckoutService(jdbc,manager,inventory,promotion,clock,2);
        long id=create();
        doThrow(new IllegalStateException("网络结果未知")).when(inventory).lock("checkout:"+id+":lock",id,"sku",1);
        service.process(id);service.process(id);
        assertThat(service.get("account",id).phase()).isEqualTo("REVIEW_LOCK_STOCK");
        var later=new CheckoutService(jdbc,manager,inventory,promotion,Clock.offset(clock,Duration.ofMinutes(20)));
        try { later.processPending(); } finally { later.close(); }
        assertThat(service.get("account",id).status()).isEqualTo("TIMEOUT_CLOSED");
        assertThat(service.get("account",id).phase()).isEqualTo("DONE");
        assertThat(coupons.wallet("account").getFirst().status()).isEqualTo("AVAILABLE");
    }

    @Test
    void failedAuditWriteRollsBackTaskResume() {
        long id=create();service.process(id);service.paid(id);
        doThrow(new HttpClientErrorException(HttpStatus.CONFLICT)).when(inventory).confirm(anyString(),eq(id),anyString(),anyInt());
        service.process(id);
        jdbc.execute("DROP TABLE commerce_operation_audit");
        assertThatThrownBy(()->service.retryTask(id,new CheckoutService.OperatorAction("operator","故障已修复"))).isInstanceOf(RuntimeException.class);
        assertThat(service.get("account",id).phase()).isEqualTo("REVIEW_CONFIRM_STOCK");
    }

    @Test
    void workerUsesBoundedConcurrencyAndProcessesMoreThanOldBatchLimit() throws Exception {
        var concurrent=new CheckoutService(jdbc,manager,inventory,promotion,clock,20,100,2);
        var entered=new CountDownLatch(2);var release=new CountDownLatch(1);
        var inFlight=new java.util.concurrent.atomic.AtomicInteger();var maximum=new java.util.concurrent.atomic.AtomicInteger();
        doAnswer(invocation -> {
            int count=inFlight.incrementAndGet();maximum.accumulateAndGet(count,Math::max);entered.countDown();
            try { if(!release.await(5,TimeUnit.SECONDS)) throw new IllegalStateException("test timeout");return null; }
            finally { inFlight.decrementAndGet(); }
        }).when(inventory).lock(anyString(),anyLong(),anyString(),anyInt());
        for(int i=0;i<30;i++) concurrent.create("account",null,request("batch-"+i,null));
        try(var pool=Executors.newSingleThreadExecutor()) {
            var run=pool.submit(concurrent::processPending);
            try { assertThat(entered.await(5,TimeUnit.SECONDS)).isTrue();concurrent.processPending(); }
            finally { release.countDown(); }
            run.get(10,TimeUnit.SECONDS);
        } finally { concurrent.close(); }
        assertThat(maximum.get()).isEqualTo(2);
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM orders WHERE status='WAITING_PAYMENT'",Integer.class)).isEqualTo(30);
        verify(inventory,times(30)).lock(anyString(),anyLong(),anyString(),anyInt());
    }

    @Test
    void creatingOrderExpiresAndReleasesCouponAfterStockLockResponseTimeout() {
        long id = create();
        doThrow(new IllegalStateException("库存响应超时"))
                .when(inventory).lock("checkout:"+id+":lock",id,"sku",1);
        service.process(id);
        var later = new CheckoutService(jdbc,manager,inventory,promotion,Clock.offset(clock,Duration.ofMinutes(20)));
        later.processPending();
        assertThat(later.get("account",id).status()).isEqualTo("TIMEOUT_CLOSED");
        assertThat(coupons.wallet("account").getFirst().status()).isEqualTo("AVAILABLE");
        later.processPending();
        assertThat(later.get("account",id).phase()).isEqualTo("DONE");
    }

    @Test
    void creatingOrderCanBeCanceledBeforeAnyRemoteResourceWasLocked() {
        long id = create();
        assertThat(service.cancel("account",id).status()).isEqualTo("CANCELED");
        service.process(id);
        assertThat(service.get("account",id).phase()).isEqualTo("DONE");
        assertThat(coupons.wallet("account").getFirst().status()).isEqualTo("AVAILABLE");
        verify(inventory,never()).lock(anyString(),anyLong(),anyString(),anyInt());
    }

    @Test
    void paymentQuoteRejectsAnotherAccountAndExpiredOrUnreadyOrders() {
        long id = create();
        assertThatThrownBy(() -> service.payableOrder("account",id)).isInstanceOf(ResponseStatusException.class);
        service.process(id);
        assertThat(service.payableOrder("account",id).totalAmount()).isEqualTo(2500);
        assertThatThrownBy(() -> service.payableOrder("other",id)).isInstanceOf(ResponseStatusException.class);
        jdbc.update("UPDATE checkout_workflow SET expires_at = ? WHERE order_id = ?",LocalDateTime.now(clock),id);
        assertThatThrownBy(() -> service.payableOrder("account",id)).isInstanceOf(ResponseStatusException.class);
    }

    @Test
    void durableCreateUsesServerPriceAndPreservesAttributionThenPays() {
        long orderId = create();
        assertThat(service.get("account",orderId).status()).isEqualTo("CREATING");
        verifyNoInteractions(inventory);
        service.process(orderId);
        var order = service.get("account",orderId);
        assertThat(order.status()).isEqualTo("WAITING_PAYMENT");
        assertThat(order.originalAmount()).isEqualTo(3000);
        assertThat(order.discountAmount()).isEqualTo(500);
        assertThat(order.totalAmount()).isEqualTo(2500);
        assertThat(jdbc.queryForObject("SELECT recommend_request_id FROM orders WHERE order_id = ?",String.class,orderId)).isEqualTo("delivery");
        service.paid(orderId);
        assertThat(service.get("account",orderId).phase()).isEqualTo("CONFIRM_STOCK");
        service.process(orderId);
        service.paid(orderId);
        assertThat(service.get("account",orderId).phase()).isEqualTo("DONE");
        assertThat(coupons.wallet("account").getFirst().status()).isEqualTo("USED");
        verify(inventory,times(1)).confirm("checkout:"+orderId+":confirm",orderId,"sku",1);
    }

    @Test
    void retryAfterRemoteLockSucceededButResponseWasLostUsesSameReservation() {
        long orderId = create();
        doAnswer(invocation -> {
            coupons.lock(new PromotionService.LockRequest(orderId,couponId,"account","item",3000L));
            throw new IllegalStateException("模拟响应丢失");
        }).doCallRealMethod().when(promotion).lock(orderId,couponId,"account","item",3000L);
        service.process(orderId);
        assertThat(service.get("account",orderId).phase()).isEqualTo("LOCK_COUPON");
        var restarted = new CheckoutService(jdbc,manager,inventory,promotion,clock);
        restarted.process(orderId);
        assertThat(restarted.get("account",orderId).status()).isEqualTo("WAITING_PAYMENT");
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM promotion_reservation",Integer.class)).isOne();
    }

    @Test
    void unavailableInventoryIsRetriedButDefinitiveRejectionReturnsCoupon() {
        long id = create();
        doThrow(new IllegalStateException("网络超时")).doThrow(new HttpClientErrorException(HttpStatus.CONFLICT))
                .when(inventory).lock("checkout:"+id+":lock",id,"sku",1);
        service.process(id);
        assertThat(service.get("account",id).phase()).isEqualTo("LOCK_STOCK");
        assertThat(coupons.wallet("account").getFirst().status()).isEqualTo("LOCKED");
        service.process(id);
        assertThat(service.get("account",id).phase()).isEqualTo("ABORT_COUPON");
        service.process(id);
        assertThat(service.get("account",id).status()).isEqualTo("CREATION_FAILED");
        assertThat(coupons.wallet("account").getFirst().status()).isEqualTo("AVAILABLE");
        verify(inventory,never()).release(anyString(),anyLong(),anyString(),anyInt());
    }

    @Test
    void canceledOrderContinuesReleaseAfterRestartAndDuplicateCancelDoesNotSkipWork() {
        long id = create(); service.process(id);
        service.cancel("account",id);
        doThrow(new IllegalStateException("库存离线")).doNothing()
                .when(inventory).release("checkout:"+id+":release",id,"sku",1);
        service.process(id);
        service.cancel("account",id);
        var restarted = new CheckoutService(jdbc,manager,inventory,promotion,clock);
        restarted.process(id);
        assertThat(restarted.get("account",id).phase()).isEqualTo("DONE");
        assertThat(coupons.wallet("account").getFirst().status()).isEqualTo("AVAILABLE");
    }

    @Test
    void concurrentIdempotentCreateIsAccountScopedAndRejectsParameterChanges() throws Exception {
        try(var pool = Executors.newFixedThreadPool(6)) {
            var tasks = new ArrayList<Callable<Long>>();
            for(int i=0;i<12;i++) tasks.add(this::create);
            Set<Long> ids = new HashSet<>();
            for(var future : pool.invokeAll(tasks)) ids.add(future.get());
            assertThat(ids).hasSize(1);
        }
        assertThatThrownBy(() -> service.create("account","profile",request("request",null))).isInstanceOf(ResponseStatusException.class);
        long other = service.create("other","profile",request("request",null)).orderId();
        assertThatThrownBy(() -> service.get("account",other)).isInstanceOf(ResponseStatusException.class);
        assertThatThrownBy(() -> service.cancel("account",other)).isInstanceOf(ResponseStatusException.class);
    }

    @Test
    void paymentAndCancelRaceHasOneWinnerAndOneResourceOutcome() throws Exception {
        long id = create(); service.process(id);
        try(var pool = Executors.newFixedThreadPool(2)) {
            var tasks = List.<Callable<Boolean>>of(
                    () -> { try { service.paid(id); return true; } catch(ResponseStatusException ex) { return false; } },
                    () -> { try { service.cancel("account",id); return true; } catch(ResponseStatusException ex) { return false; } });
            int success = 0;
            for(var result : pool.invokeAll(tasks)) if(result.get()) success++;
            assertThat(success).isOne();
        }
        service.process(id);
        var state = service.get("account",id).status();
        assertThat(coupons.wallet("account").getFirst().status()).isEqualTo(state.equals("PAID") ? "USED" : "AVAILABLE");
    }

    @Test
    void workerClosesExpiredOrdersAndRestoresResources() {
        long id = create(); service.process(id);
        var later = new CheckoutService(jdbc,manager,inventory,promotion,Clock.offset(clock,Duration.ofMinutes(16)));
        assertThatThrownBy(() -> later.paid(id)).isInstanceOf(ResponseStatusException.class);
        later.processPending();
        later.processPending();
        assertThat(later.get("account",id).status()).isEqualTo("TIMEOUT_CLOSED");
        assertThat(later.get("account",id).phase()).isEqualTo("DONE");
        assertThat(coupons.wallet("account").getFirst().status()).isEqualTo("AVAILABLE");
    }

    @Test
    void mockPaymentIsUnavailableByDefaultAndCannotPayAnotherAccountOrder() {
        long id = create(); service.process(id);
        assertThatThrownBy(() -> new CheckoutController(service,false).mockPay("account",id)).isInstanceOf(ResponseStatusException.class);
        assertThatThrownBy(() -> new CheckoutController(service,true).mockPay("other",id)).isInstanceOf(ResponseStatusException.class);
        assertThat(service.get("account",id).status()).isEqualTo("WAITING_PAYMENT");
    }

    @Test
    void paymentCallbackMustMatchTheServerDiscountedAmount() {
        long id = create(); service.process(id);
        assertThatThrownBy(() -> service.paidFromProvider(id,1L,"provider","transaction")).isInstanceOf(ResponseStatusException.class);
        assertThatThrownBy(() -> service.paidFromProvider(id,null,"provider","transaction")).isInstanceOf(ResponseStatusException.class);
        assertThat(service.get("account",id).status()).isEqualTo("WAITING_PAYMENT");
        service.paidFromProvider(id,2500L,"provider","transaction");
        assertThat(service.get("account",id).status()).isEqualTo("PAID");
    }

    @Test
    void mockDeclineAndTimeoutKeepReservationThenAllowCancel() {
        long id = create(); service.process(id);
        var controller = new CheckoutController(service,true);
        for (var scenario : List.of(CheckoutController.MockPaymentScenario.DECLINED,
                CheckoutController.MockPaymentScenario.TIMEOUT_BEFORE_PAYMENT)) {
            assertThatThrownBy(() -> controller.mockPay("account",id,new CheckoutController.MockPaymentRequest(scenario)))
                    .isInstanceOfSatisfying(ResponseStatusException.class, ex -> assertThat(ex.getStatusCode().value())
                            .isEqualTo(scenario == CheckoutController.MockPaymentScenario.DECLINED ? 402 : 504));
            assertThat(service.get("account",id).status()).isEqualTo("WAITING_PAYMENT");
            assertThat(coupons.wallet("account").getFirst().status()).isEqualTo("LOCKED");
        }
        service.cancel("account",id); service.process(id);
        assertThat(coupons.wallet("account").getFirst().status()).isEqualTo("AVAILABLE");
        verify(inventory,never()).confirm(anyString(),anyLong(),anyString(),anyInt());
        verify(inventory).release("checkout:"+id+":release",id,"sku",1);
    }

    @Test
    void mockLostResponsePersistsPaymentAndRetryAfterRestartConfirmsOnlyOnce() {
        long id = create(); service.process(id);
        var request = new CheckoutController.MockPaymentRequest(CheckoutController.MockPaymentScenario.RESPONSE_LOST);
        assertThatThrownBy(() -> new CheckoutController(service,true).mockPay("account",id,request))
                .isInstanceOfSatisfying(ResponseStatusException.class, ex -> assertThat(ex.getStatusCode().value()).isEqualTo(504));
        var restarted = new CheckoutService(jdbc,manager,inventory,promotion,clock);
        var controller = new CheckoutController(restarted,true);
        assertThat(controller.mockPay("account",id,request).status()).isEqualTo("PAID");
        restarted.process(id);
        assertThat(controller.mockPay("account",id,request).phase()).isEqualTo("DONE");
        restarted.process(id);
        assertThat(coupons.wallet("account").getFirst().status()).isEqualTo("USED");
        verify(inventory,times(1)).confirm("checkout:"+id+":confirm",id,"sku",1);
        assertThatThrownBy(() -> service.cancel("account",id)).isInstanceOf(ResponseStatusException.class);
    }

    @Test
    void everyMockScenarioRequiresEnabledFlagAndOwnership() {
        long id = create(); service.process(id);
        for (var scenario : CheckoutController.MockPaymentScenario.values()) {
            var request = new CheckoutController.MockPaymentRequest(scenario);
            assertThatThrownBy(() -> new CheckoutController(service,false).mockPay("account",id,request))
                    .isInstanceOfSatisfying(ResponseStatusException.class, ex -> assertThat(ex.getStatusCode().value()).isEqualTo(404));
            assertThatThrownBy(() -> new CheckoutController(service,true).mockPay("other",id,request))
                    .isInstanceOfSatisfying(ResponseStatusException.class, ex -> assertThat(ex.getStatusCode().value()).isEqualTo(404));
        }
        assertThat(service.get("account",id).status()).isEqualTo("WAITING_PAYMENT");
    }
}
