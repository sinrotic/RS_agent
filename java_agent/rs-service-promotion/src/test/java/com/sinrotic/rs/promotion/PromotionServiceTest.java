package com.sinrotic.rs.promotion;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.jdbc.datasource.init.ResourceDatabasePopulator;
import org.springframework.core.io.FileSystemResource;
import org.springframework.web.server.ResponseStatusException;

import java.time.*;
import java.util.*;
import java.util.concurrent.*;

import static org.assertj.core.api.Assertions.*;

class PromotionServiceTest {
    JdbcTemplate jdbc;
    PromotionService service;
    Clock clock = Clock.fixed(Instant.parse("2026-09-13T00:00:00Z"),ZoneOffset.UTC);

    @BeforeEach
    void setup() {
        var ds = new DriverManagerDataSource("jdbc:h2:mem:" + UUID.randomUUID() + ";MODE=MySQL;DB_CLOSE_DELAY=-1;LOCK_TIMEOUT=10000","sa","");
        new ResourceDatabasePopulator(new FileSystemResource("../sql/rs_service_trade_schema.sql"),
                new FileSystemResource("../sql/rs_service_commerce_v1_schema.sql")).execute(ds);
        jdbc = new JdbcTemplate(ds);
        service = new PromotionService(jdbc,new DataSourceTransactionManager(ds),clock);
        campaign("campaign",10);
    }

    void campaign(String id,int count) {
        var now = LocalDateTime.now(clock);
        service.createCampaign(new PromotionService.Campaign(id,"满 20 减 5",null,count,count,2000,500,
                now.minusHours(1),now.plusHours(1),now.plusDays(1)));
    }

    @Test void walletPaginationPassesTwoHundredAndRemainsAccountScoped() {
        for(int i=0;i<205;i++) {
            String id=String.format("history-%03d",i);campaign(id,2);service.claim("account",id,"claim-"+i);
        }
        service.claim("other","history-000","other-claim");
        var found=new HashSet<String>();String cursor=null;int count=0;
        do {var page=service.walletPage("account",cursor,20);for(var coupon:page.items()){assertThat(coupon.accountId()).isEqualTo("account");assertThat(found.add(coupon.couponId())).isTrue();count++;}cursor=page.nextCursor();}while(cursor!=null);
        assertThat(count).isEqualTo(205);
    }

    @Test void campaignPublicationReplayDoesNotReplenishClaimedQuotaOrDuplicateAudit() {
        var manager=new DataSourceTransactionManager(Objects.requireNonNull(jdbc.getDataSource()));
        var management=new PromotionManagement(jdbc,manager,service);var now=LocalDateTime.now(clock);
        var input=new PromotionService.Campaign("managed","限量",null,2,2,2000,500,now.minusHours(1),now.plusHours(1),now.plusDays(1));
        management.create(input,"operator");service.claim("account","managed","claim-managed");management.create(input,"operator");
        assertThat(jdbc.queryForObject("SELECT remaining_quantity FROM promotion_campaign WHERE campaign_id='managed'",Integer.class)).isOne();
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM commerce_operation_audit WHERE resource_id='managed'",Integer.class)).isOne();
        assertThatThrownBy(()->management.create(new PromotionService.Campaign("managed","限量",null,3,3,2000,500,input.startsAt(),input.endsAt(),input.expiresAt()),"operator")).isInstanceOf(ResponseStatusException.class);
    }

    @Test
    void concurrentClaimsNeverExceedQuotaAndDoNotLeakStock() throws Exception {
        try (var pool = Executors.newFixedThreadPool(8)) {
            var results = new ArrayList<Future<Boolean>>();
            for(int i=0;i<80;i++) {
                String account = "account-" + i;
                results.add(pool.submit(() -> {
                    try { service.claim(account,"campaign","claim"); return true; }
                    catch(ResponseStatusException rejected) { assertThat(rejected.getStatusCode().value()).isEqualTo(409); return false; }
                }));
            }
            int claimed = 0;
            for(var result : results) if(result.get(20,TimeUnit.SECONDS)) claimed++;
            assertThat(claimed).isEqualTo(10);
        }
        assertThat(jdbc.queryForObject("SELECT remaining_quantity FROM promotion_campaign WHERE campaign_id = 'campaign'",Integer.class)).isZero();
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM promotion_coupon",Integer.class)).isEqualTo(10);
    }

    @Test
    void concurrentSameAccountGetsOneCouponEvenWithDifferentRequestIds() throws Exception {
        try(var pool = Executors.newFixedThreadPool(8)) {
            var tasks = new ArrayList<Callable<String>>();
            for(int i=0;i<20;i++) {
                String requestId = "req-"+i;
                tasks.add(() -> service.claim("account","campaign",requestId).couponId());
            }
            Set<String> ids = new HashSet<>();
            for(var result : pool.invokeAll(tasks)) ids.add(result.get());
            assertThat(ids).hasSize(1);
        }
        assertThat(jdbc.queryForObject("SELECT remaining_quantity FROM promotion_campaign WHERE campaign_id = 'campaign'",Integer.class)).isEqualTo(9);
    }

    @Test
    void reusedRequestCannotClaimAnotherCampaign() {
        campaign("other",10);
        service.claim("account","campaign","request");
        service.claim("account","campaign","second-request");
        assertThatThrownBy(() -> service.claim("account","other","second-request")).isInstanceOf(ResponseStatusException.class);
        assertThatThrownBy(() -> service.claim("account","other","request")).isInstanceOf(ResponseStatusException.class);
        assertThat(jdbc.queryForObject("SELECT remaining_quantity FROM promotion_campaign WHERE campaign_id = 'other'",Integer.class)).isEqualTo(10);
    }

    @Test
    void cancelBeforeLockPreventsLateReservationWithoutTouchingAnotherOrder() {
        String id=service.claim("account","campaign","req").couponId();
        var canceled = new PromotionService.LockRequest(1L,id,"account","item",3000L);
        service.cancel(canceled);service.cancel(canceled);
        assertThatThrownBy(() -> service.lock(canceled)).isInstanceOf(ResponseStatusException.class);
        service.lock(new PromotionService.LockRequest(2L,id,"account","item",3000L));
        service.cancel(canceled);
        assertThat(service.wallet("account").getFirst().lockedOrderId()).isEqualTo(2L);
    }

    @Test
    void lockAndCancelRaceAlwaysEndsWithAvailableCoupon() throws Exception {
        String id=service.claim("account","campaign","req").couponId();
        var request=new PromotionService.LockRequest(1L,id,"account","item",3000L);
        try(var pool=Executors.newFixedThreadPool(2)) {
            var start=new CountDownLatch(1);
            var lock=pool.submit(() -> { start.await();try {service.lock(request);}catch(ResponseStatusException ignored){} return null; });
            var cancel=pool.submit(() -> { start.await();service.cancel(request);return null; });
            start.countDown();lock.get();cancel.get();
        }
        service.cancel(request);
        assertThat(service.wallet("account").getFirst().status()).isEqualTo("AVAILABLE");
        assertThatThrownBy(() -> service.lock(request)).isInstanceOf(ResponseStatusException.class);
    }

    @Test
    void sameCouponCannotBeLockedByTwoOrdersAndRetryDoesNotRelockReleasedReservation() throws Exception {
        String id = service.claim("account","campaign","req").couponId();
        try(var pool = Executors.newFixedThreadPool(2)) {
            var start = new CountDownLatch(1);
            List<Future<Long>> jobs = new ArrayList<>();
            for(long order=1;order<=2;order++) {
                long orderId = order;
                jobs.add(pool.submit(() -> {
                    start.await();
                    try { service.lock(new PromotionService.LockRequest(orderId,id,"account","item",3000L)); return orderId; }
                    catch(ResponseStatusException rejected) { return 0L; }
                }));
            }
            start.countDown();
            long winner = jobs.get(0).get()+jobs.get(1).get();
            assertThat(winner).isBetween(1L,2L);
            assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM promotion_reservation",Integer.class)).isOne();
            service.finish(winner,id,false);
            service.finish(winner,id,false);
            assertThatThrownBy(() -> service.lock(new PromotionService.LockRequest(winner,id,"account","item",3000L)))
                    .isInstanceOf(ResponseStatusException.class);
            assertThat(service.wallet("account").getFirst().status()).isEqualTo("AVAILABLE");
            assertThatThrownBy(() -> service.finish(winner,id,true)).isInstanceOf(ResponseStatusException.class);
        }
    }

    @Test
    void rejectsWrongOwnerWrongItemAndInsufficientAmount() {
        var now = LocalDateTime.now(clock);
        service.createCampaign(new PromotionService.Campaign("specific","限定商品","item",1,1,2000,500,
                now.minusHours(1),now.plusHours(1),now.plusDays(1)));
        String id = service.claim("account","specific","req").couponId();
        assertThatThrownBy(() -> service.lock(new PromotionService.LockRequest(1L,id,"other","item",3000L))).isInstanceOf(ResponseStatusException.class);
        assertThatThrownBy(() -> service.lock(new PromotionService.LockRequest(1L,id,"account","wrong",3000L))).isInstanceOf(ResponseStatusException.class);
        assertThatThrownBy(() -> service.lock(new PromotionService.LockRequest(1L,id,"account","item",1999L))).isInstanceOf(ResponseStatusException.class);
        assertThat(service.wallet("account").getFirst().status()).isEqualTo("AVAILABLE");
    }

    @Test
    void confirmAndReleaseAreMutuallyExclusiveAndExpirySurvivesReturn() {
        String id = service.claim("account","campaign","req").couponId();
        service.lock(new PromotionService.LockRequest(1L,id,"account","item",3000L));
        service.finish(1L,id,true);
        service.finish(1L,id,true);
        assertThatThrownBy(() -> service.finish(1L,id,false)).isInstanceOf(ResponseStatusException.class);
        assertThat(service.wallet("account").getFirst().status()).isEqualTo("USED");

        String second = service.claim("other","campaign","req").couponId();
        service.lock(new PromotionService.LockRequest(2L,second,"other","item",3000L));
        var later = new PromotionService(jdbc,new DataSourceTransactionManager(Objects.requireNonNull(jdbc.getDataSource())),
                Clock.offset(clock,Duration.ofDays(2)));
        later.finish(2L,second,false);
        assertThat(later.wallet("other").getFirst().status()).isEqualTo("EXPIRED");
    }
}
