package com.sinrotic.rs.order.checkout;

import com.sinrotic.rs.order.client.InventoryClient;
import com.sinrotic.rs.inventory.service.*;
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

class RefundWorkflowTest {
    JdbcTemplate jdbc;CheckoutService checkout;RefundService refunds;RefundPaymentClient payment;
    PromotionService coupons;ActivityStockService pools;String coupon;DataSourceTransactionManager manager;
    @BeforeEach void setup() throws Exception {
        var ds=new DriverManagerDataSource("jdbc:h2:mem:"+UUID.randomUUID()+";MODE=MySQL;DB_CLOSE_DELAY=-1;LOCK_TIMEOUT=10000","sa","");
        new ResourceDatabasePopulator(new FileSystemResource("../sql/rs_service_trade_schema.sql"),new FileSystemResource("../sql/rs_service_commerce_v1_schema.sql")).execute(ds);
        jdbc=new JdbcTemplate(ds);manager=new DataSourceTransactionManager(ds);var tx=new TransactionTemplate(manager);
        jdbc.update("INSERT INTO sku_stock(sku_id,item_id,available_stock) VALUES ('sku','item',10)");
        jdbc.update("INSERT INTO checkout_offer(sku_id,item_id,item_title,unit_price) VALUES ('sku','item','商品',3000)");
        var factory=new SqlSessionFactoryBean();factory.setDataSource(ds);
        factory.setMapperLocations(new FileSystemResource("../rs-service-inventory/src/main/resources/mapper/SkuStockMapper.xml"),new FileSystemResource("../rs-service-inventory/src/main/resources/mapper/StockLogMapper.xml"));
        var config=new org.apache.ibatis.session.Configuration();config.setMapUnderscoreToCamelCase(true);factory.setConfiguration(config);
        var session=new SqlSessionTemplate(Objects.requireNonNull(factory.getObject()));
        var stock=new InventoryService(session.getMapper(SkuStockMapper.class),session.getMapper(StockLogMapper.class));
        var returned=new RefundStockService(jdbc,manager);pools=new ActivityStockService(jdbc,manager);
        var inventory=new InventoryClient() {
            public void lock(String key,Long id,String sku,Integer q) {tx.executeWithoutResult(s->stock.lockStock(new InventoryLockRequestDTO(key,id,sku,q)));}
            public void confirm(String key,Long id,String sku,Integer q) {tx.executeWithoutResult(s->stock.confirmDeduct(new InventoryConfirmRequestDTO(key,id,sku,q)));}
            public void release(String key,Long id,String sku,Integer q) {tx.executeWithoutResult(s->stock.releaseStock(new InventoryReleaseRequestDTO(key,id,sku,q)));}
            public void refund(String key,Long id,String sku,Integer q) {returned.refund(new InventoryReleaseRequestDTO(key,id,sku,q));}
            public void activity(String action,String pool,Long id,String sku,Integer q) {pools.move(action,new ActivityStockService.Movement(pool,id,sku,q));}
        };
        coupons=new PromotionService(jdbc,manager);var now=LocalDateTime.now(Clock.systemUTC());
        coupons.createCampaign(new PromotionService.Campaign("campaign","满减",null,10,10,2000,500,now.minusHours(1),now.plusHours(1),now.plusDays(1)));
        coupon=coupons.claim("account","campaign","claim").couponId();
        var promotion=new PromotionClient() {
            public long lock(long id,String c,String account,String item,long amount) {return coupons.lock(new PromotionService.LockRequest(id,c,account,item,amount)).discountAmount();}
            public void confirm(long id,String c) {coupons.finish(id,c,true);}
            public void release(long id,String c) {coupons.finish(id,c,false);}
            public void refund(long id,String c) {coupons.refund(id,c);}
        };
        checkout=new CheckoutService(jdbc,manager,inventory,promotion,Clock.systemUTC());
        payment=mock(RefundPaymentClient.class);
        when(payment.refund(anyString(),anyLong(),anyLong(),anyString(),anyBoolean())).thenAnswer(i->new RefundPaymentClient.Result(i.getArgument(0),"SUCCEEDED",true,false));
        refunds=new RefundService(jdbc,manager,payment,inventory,promotion);
    }
    @AfterEach void close() {checkout.close();}
    @Test void orderHistorySeekPaginationDoesNotStopAtFiftyOrLeakOtherAccounts() {
        var expected=new HashSet<Long>();
        for(int i=0;i<57;i++) expected.add(checkout.create("account","profile",new CheckoutService.CreateRequest("history-"+i,"item","sku",1,null,null,null)).orderId());
        checkout.create("other","profile",new CheckoutService.CreateRequest("other","item","sku",1,null,null,null));
        var found=new ArrayList<Long>();Long cursor=null;
        do {var page=checkout.page("account",cursor,null,20);found.addAll(page.items().stream().map(CheckoutService.OrderView::orderId).toList());cursor=page.nextCursor()==null ? null : Long.valueOf(page.nextCursor());} while(cursor!=null);
        assertThat(found).hasSize(57).doesNotHaveDuplicates().containsExactlyInAnyOrderElementsOf(expected);
        assertThatThrownBy(()->checkout.page("account",null,null,101)).isInstanceOf(ResponseStatusException.class);
    }
    long paid(boolean activity) {
        var request=new CheckoutService.CreateRequest(UUID.randomUUID().toString(),"item","sku",1,activity ? null : coupon,null,null);
        if(activity) pools.allocate(new ActivityStockService.Allocation("activity","sku",5));
        long id=(activity ? checkout.createAccepted("account",request,new CheckoutService.Offer("sku","item","商品",3000),"activity") : checkout.create("account","profile",request)).orderId();
        checkout.process(id);checkout.paidFromProvider(id,checkout.get("account",id).totalAmount(),"mock","payment-"+id);checkout.process(id);return id;
    }
    @Test void fullRefundRestoresStockAndCouponOnlyOnceAndKeepsImmutableEvents() {
        long id=paid(false);var request=new RefundService.Request("refund-key","未发货整单退款","SUCCESS");
        var refund=refunds.request("account",id,request);
        assertThat(refunds.request("account",id,request).refundId()).isEqualTo(refund.refundId());
        refunds.process(refund.refundId());refunds.process(refund.refundId());
        assertThat(checkout.get("account",id).status()).isEqualTo("REFUNDED");
        assertThat(jdbc.queryForObject("SELECT available_stock FROM sku_stock",Integer.class)).isEqualTo(10);
        assertThat(coupons.wallet("account").getFirst().status()).isEqualTo("AVAILABLE");
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM stock_logs WHERE type='REFUND'",Integer.class)).isOne();
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM commerce_order_event",Integer.class)).isEqualTo(2);
        assertThatThrownBy(()->refunds.request("other",id,request)).isInstanceOf(ResponseStatusException.class);
    }
    @Test void unknownPaymentResultNeverReturnsStockUntilSameRefundSucceeds() {
        long id=paid(false);var refund=refunds.request("account",id,new RefundService.Request("refund-key","整单退款","RESPONSE_LOST"));
        doThrow(new ResourceAccessException("已退款但响应丢失")).doAnswer(i->new RefundPaymentClient.Result(i.getArgument(0),"SUCCEEDED",true,false))
                .when(payment).refund(anyString(),anyLong(),anyLong(),anyString(),anyBoolean());
        refunds.process(refund.refundId());assertThat(jdbc.queryForObject("SELECT sold_stock FROM sku_stock",Integer.class)).isOne();
        refunds.process(refund.refundId());assertThat(refunds.get("account",id).status()).isEqualTo("REFUNDED");
        verify(payment,times(2)).refund(eq(refund.refundId()),eq(id),eq(2500L),eq("RESPONSE_LOST"),eq(false));
    }
    @Test void originalPaymentNotificationCanReplayDuringAndAfterRefundWithoutReactivatingOrder() {
        long id=paid(false);var refund=refunds.request("account",id,new RefundService.Request("refund","整单退款","SUCCESS"));
        checkout.paidFromProvider(id,2500L,"mock","payment-"+id);
        assertThat(checkout.get("account",id).status()).isEqualTo("REFUNDING");
        refunds.process(refund.refundId());checkout.paidFromProvider(id,2500L,"mock","payment-"+id);
        assertThat(checkout.get("account",id).status()).isEqualTo("REFUNDED");
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM commerce_order_event",Integer.class)).isEqualTo(2);
        assertThatThrownBy(()->checkout.paidFromProvider(id,2500L,"mock","different-tx")).isInstanceOf(ResponseStatusException.class);
    }
    @Test void closedActivityRefundReturnsOrdinaryStockWithoutReopeningPool() {
        long id=paid(true);pools.close("activity");
        var refund=refunds.request("account",id,new RefundService.Request("refund-key","整单退款","SUCCESS"));refunds.process(refund.refundId());
        assertThat(pools.view("activity")).containsEntry("status","CLOSED").containsEntry("returned_quantity",5).containsEntry("sold_quantity",0);
        assertThat(jdbc.queryForObject("SELECT available_stock FROM sku_stock",Integer.class)).isEqualTo(10);
        assertThatThrownBy(()->pools.move("LOCK",new ActivityStockService.Movement("activity",90,"sku",1))).isInstanceOf(ResponseStatusException.class);
    }
    @Test void declinedRefundParksThenAuditedRetryRetainsIdAndExpiresCoupon() {
        long id=paid(false);jdbc.update("UPDATE promotion_campaign SET ends_at=?,expires_at=?",LocalDateTime.now(Clock.systemUTC()).minusSeconds(2),LocalDateTime.now(Clock.systemUTC()).minusSeconds(1));
        var refund=refunds.request("account",id,new RefundService.Request("refund-key","整单退款","DECLINED"));
        when(payment.refund(anyString(),anyLong(),anyLong(),anyString(),eq(false))).thenReturn(new RefundPaymentClient.Result(refund.refundId(),"FAILED",true,false));
        refunds.process(refund.refundId());assertThat(refunds.get("account",id).status()).isEqualTo("REVIEW_REQUIRED");
        refunds.retry(refund.refundId(),"operator","渠道问题已排除");refunds.process(refund.refundId());
        assertThat(coupons.wallet("account").getFirst().status()).isEqualTo("EXPIRED");
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM commerce_operation_audit WHERE component='refund'",Integer.class)).isOne();
    }
    @Test void concurrentRefundRequestsShareOneRefundAndAliasesCannotChangeOrders() throws Exception {
        long order=paid(false);
        try(var executor=Executors.newFixedThreadPool(4)) {
            var tasks=new ArrayList<Callable<String>>();for(int i=0;i<10;i++) {String key="key-"+i;tasks.add(()->refunds.request("account",order,new RefundService.Request(key,"退款","SUCCESS")).refundId());}
            var ids=new HashSet<String>();for(var task:executor.invokeAll(tasks)) ids.add(task.get());assertThat(ids).hasSize(1);
        }
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM checkout_refund",Integer.class)).isOne();
    }
}
