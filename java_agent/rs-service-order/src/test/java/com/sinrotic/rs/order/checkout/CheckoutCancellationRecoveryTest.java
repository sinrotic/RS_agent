package com.sinrotic.rs.order.checkout;

import com.sinrotic.rs.order.client.InventoryClient;
import com.sinrotic.rs.inventory.service.InventoryService;
import com.sinrotic.rs.inventory.service.InventoryServiceException;
import com.sinrotic.rs.inventory.mapper.*;
import com.sinrotic.rs.inventory.domain.dto.*;
import com.sinrotic.rs.promotion.PromotionService;
import org.junit.jupiter.api.*;
import org.mybatis.spring.*;
import org.springframework.core.io.FileSystemResource;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.*;
import org.springframework.jdbc.datasource.init.ResourceDatabasePopulator;
import org.springframework.transaction.support.TransactionTemplate;
import org.springframework.web.client.ResourceAccessException;
import org.springframework.web.server.ResponseStatusException;
import java.time.*;
import java.util.*;
import java.util.concurrent.*;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;

/** 使用三个服务的真实持久化实现验证取消、迟到请求与响应丢失。 */
class CheckoutCancellationRecoveryTest {
    JdbcTemplate jdbc;
    DataSourceTransactionManager manager;
    InventoryService stock;
    InventoryClient inventory;
    PromotionService coupons;
    PromotionClient promotion;
    CheckoutService service;
    Clock clock=Clock.fixed(Instant.parse("2026-10-10T00:00:00Z"),ZoneOffset.UTC);
    String coupon;

    @BeforeEach
    void setup() throws Exception {
        var ds=new DriverManagerDataSource("jdbc:h2:mem:"+UUID.randomUUID()+";MODE=MySQL;DB_CLOSE_DELAY=-1;LOCK_TIMEOUT=10000","sa","");
        new ResourceDatabasePopulator(new FileSystemResource("../sql/rs_service_trade_schema.sql"),
                new FileSystemResource("../sql/rs_service_commerce_v1_schema.sql")).execute(ds);
        jdbc=new JdbcTemplate(ds);manager=new DataSourceTransactionManager(ds);
        jdbc.update("INSERT INTO checkout_offer(sku_id,item_id,item_title,unit_price) VALUES ('sku','item','测试商品',3000)");
        jdbc.update("INSERT INTO sku_stock(sku_id,item_id,available_stock) VALUES ('sku','item',10)");
        var factory=new SqlSessionFactoryBean();factory.setDataSource(ds);
        factory.setMapperLocations(new FileSystemResource("../rs-service-inventory/src/main/resources/mapper/SkuStockMapper.xml"),
                new FileSystemResource("../rs-service-inventory/src/main/resources/mapper/StockLogMapper.xml"));
        var config=new org.apache.ibatis.session.Configuration();config.setMapUnderscoreToCamelCase(true);factory.setConfiguration(config);
        var session=new SqlSessionTemplate(Objects.requireNonNull(factory.getObject()));
        stock=new InventoryService(session.getMapper(SkuStockMapper.class),session.getMapper(StockLogMapper.class));
        var tx=new TransactionTemplate(manager);
        inventory=spy(new InventoryClient() {
            public void lock(String r,Long id,String sku,Integer qty) {tx.executeWithoutResult(s -> stock.lockStock(new InventoryLockRequestDTO(r,id,sku,qty)));}
            public void confirm(String r,Long id,String sku,Integer qty) {tx.executeWithoutResult(s -> stock.confirmDeduct(new InventoryConfirmRequestDTO(r,id,sku,qty)));}
            public void release(String r,Long id,String sku,Integer qty) {tx.executeWithoutResult(s -> stock.releaseStock(new InventoryReleaseRequestDTO(r,id,sku,qty)));}
            public void cancel(String r,Long id,String sku,Integer qty) {tx.executeWithoutResult(s -> stock.cancelReservation(new InventoryReleaseRequestDTO(r,id,sku,qty)));}
        });
        coupons=new PromotionService(jdbc,manager,clock);
        LocalDateTime now=LocalDateTime.now(clock);
        coupons.createCampaign(new PromotionService.Campaign("campaign","测试优惠",null,10,10,2000,500,now.minusHours(1),now.plusHours(1),now.plusDays(1)));
        coupon=coupons.claim("account","campaign","claim").couponId();
        promotion=spy(new PromotionClient() {
            public long lock(long id,String c,String a,String item,long amount) {return coupons.lock(new PromotionService.LockRequest(id,c,a,item,amount)).discountAmount();}
            public void confirm(long id,String c) {coupons.finish(id,c,true);}
            public void release(long id,String c) {coupons.finish(id,c,false);}
            public void cancel(long id,String c,String a,String item,long amount) {coupons.cancel(new PromotionService.LockRequest(id,c,a,item,amount));}
        });
        service=new CheckoutService(jdbc,manager,inventory,promotion,clock);
    }
    long create(String selectedCoupon) {
        return service.create("account","profile",new CheckoutService.CreateRequest("request","item","sku",1,selectedCoupon,null,null)).orderId();
    }
    void assertReleased(long id,String status) {
        var order=service.get("account",id);
        assertThat(order.status()).isEqualTo(status);
        assertThat(order.phase()).isEqualTo("DONE");
        assertThat(order.failureReason()).isNull();
        assertThat(coupons.wallet("account").getFirst().status()).isEqualTo("AVAILABLE");
        assertThat(jdbc.queryForObject("SELECT available_stock FROM sku_stock WHERE sku_id='sku'",Integer.class)).isEqualTo(10);
        assertThat(jdbc.queryForObject("SELECT locked_stock FROM sku_stock WHERE sku_id='sku'",Integer.class)).isZero();
    }
    @Test
    void cancelAfterStockWasLockedButResponseWasLostReleasesExactlyOnce() {
        long id=create(coupon);
        doAnswer(i -> {i.callRealMethod();throw new ResourceAccessException("响应丢失");})
                .when(inventory).lock(anyString(),anyLong(),anyString(),anyInt());
        service.process(id);
        assertThat(service.get("account",id).phase()).isEqualTo("LOCK_STOCK");
        service.cancel("account",id);
        service.process(id);service.process(id);service.cancel("account",id);
        assertReleased(id,"CANCELED");
        assertThatThrownBy(() -> inventory.lock("checkout:"+id+":lock",id,"sku",1)).isInstanceOf(InventoryServiceException.class);
        assertThatThrownBy(() -> promotion.lock(id,coupon,"account","item",3000)).isInstanceOf(ResponseStatusException.class);
    }
    @Test
    void canceledOrderCannotBeRevivedByDelayedStockRequest() throws Exception {
        long id=create(coupon);
        CountDownLatch entered=new CountDownLatch(1),resume=new CountDownLatch(1);
        doAnswer(i -> {entered.countDown();assertThat(resume.await(5,TimeUnit.SECONDS)).isTrue();return i.callRealMethod();})
                .when(inventory).lock(anyString(),anyLong(),anyString(),anyInt());
        try(var pool=Executors.newSingleThreadExecutor()) {
            var processing=pool.submit(() -> service.process(id));
            assertThat(entered.await(5,TimeUnit.SECONDS)).isTrue();
            try {service.cancel("account",id);service.process(id);} finally {resume.countDown();}
            processing.get(5,TimeUnit.SECONDS);
        }
        assertReleased(id,"CANCELED");
    }
    @Test
    void canceledOrderCannotBeRevivedByDelayedCouponRequest() throws Exception {
        long id=create(coupon);
        CountDownLatch entered=new CountDownLatch(1),resume=new CountDownLatch(1);
        doAnswer(i -> {entered.countDown();assertThat(resume.await(5,TimeUnit.SECONDS)).isTrue();return i.callRealMethod();})
                .when(promotion).lock(anyLong(),anyString(),anyString(),anyString(),anyLong());
        try(var pool=Executors.newSingleThreadExecutor()) {
            var processing=pool.submit(() -> service.process(id));
            assertThat(entered.await(5,TimeUnit.SECONDS)).isTrue();
            try {service.cancel("account",id);service.process(id);} finally {resume.countDown();}
            processing.get(5,TimeUnit.SECONDS);
        }
        assertReleased(id,"CANCELED");
    }
    @Test
    void couponIsReturnedWhileStockCleanupRetriesAndRestartContinuesDurableTask() {
        long id=create(coupon);
        service.cancel("account",id);
        doThrow(new ResourceAccessException("取消响应超时")).doCallRealMethod()
                .when(inventory).cancel(anyString(),anyLong(),anyString(),anyInt());
        service.process(id);
        assertThat(service.get("account",id).phase()).isEqualTo("CANCEL_STOCK");
        assertThat(coupons.wallet("account").getFirst().status()).isEqualTo("AVAILABLE");
        new CheckoutService(jdbc,manager,inventory,promotion,clock).process(id);
        assertReleased(id,"CANCELED");
    }
    @Test
    void expiryBeforeAnyLockClosesAndFencesResources() {
        long id=create(coupon);
        var later=new CheckoutService(jdbc,manager,inventory,promotion,Clock.offset(clock,Duration.ofMinutes(20)));
        later.processPending();
        assertReleased(id,"TIMEOUT_CLOSED");
        verify(inventory,never()).lock(anyString(),anyLong(),anyString(),anyInt());
        assertThatThrownBy(() -> promotion.lock(id,coupon,"account","item",3000)).isInstanceOf(ResponseStatusException.class);
    }
    @Test
    void cancelWithInvalidCouponStillCompletesWithoutTouchingResources() {
        long id=create("not-a-coupon");
        service.cancel("account",id);service.process(id);
        assertReleased(id,"CANCELED");
    }
}
