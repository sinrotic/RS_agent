package com.sinrotic.rs.order.checkout;

import com.sinrotic.rs.order.client.InventoryClient;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.jdbc.datasource.init.ResourceDatabasePopulator;
import org.springframework.core.io.FileSystemResource;
import tools.jackson.databind.json.JsonMapper;
import java.time.*;
import java.util.*;
import java.util.concurrent.*;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;

class SeckillCheckoutConsumerTest {
    @Test
    void concurrentRepeatedEventCreatesOneOrderAtFrozenPriceAndPaysOnce() throws Exception {
        var ds=new DriverManagerDataSource("jdbc:h2:mem:"+UUID.randomUUID()+";MODE=MySQL;DB_CLOSE_DELAY=-1;LOCK_TIMEOUT=10000","sa","");
        new ResourceDatabasePopulator(new FileSystemResource("../sql/rs_service_trade_schema.sql"),
                new FileSystemResource("../sql/rs_service_commerce_v1_schema.sql")).execute(ds);
        var jdbc=new JdbcTemplate(ds);
        jdbc.update("INSERT INTO checkout_offer(sku_id,item_id,item_title,unit_price) VALUES ('sku','item','新报价',9000)");
        var inventory=mock(InventoryClient.class);
        var service=new CheckoutService(jdbc,new DataSourceTransactionManager(ds),inventory,mock(PromotionClient.class),
                Clock.fixed(Instant.parse("2026-10-10T00:00:00Z"),ZoneOffset.UTC));
        var mapper=new JsonMapper();var consumer=new SeckillCheckoutConsumer(service,mapper);
        String payload=mapper.writeValueAsString(new SeckillCheckoutConsumer.Accepted("event","request","account","activity","item","sku",1,"活动冻结报价",3000));
        try(var pool=Executors.newFixedThreadPool(6)) {
            var tasks=new ArrayList<Callable<Void>>();
            for(int i=0;i<12;i++) tasks.add(() -> { consumer.consume(payload); return null; });
            for(var result:pool.invokeAll(tasks)) result.get();
        }
        var order=service.byRequest("account","event");
        assertThat(order.totalAmount()).isEqualTo(3000);
        assertThat(order.itemTitle()).isEqualTo("活动冻结报价");
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM orders",Integer.class)).isOne();
        service.process(order.orderId());
        assertThat(service.get("account",order.orderId()).status()).isEqualTo("WAITING_PAYMENT");
        service.paidFromProvider(order.orderId(),3000L,"mock","transaction");
        service.process(order.orderId());consumer.consume(payload);service.process(order.orderId());
        assertThat(service.get("account",order.orderId()).phase()).isEqualTo("DONE");
        verify(inventory,times(1)).confirm("checkout:"+order.orderId()+":confirm",order.orderId(),"sku",1);
    }

    @Test
    void malformedQuantityDoesNotCreateAnOrder() {
        var service=mock(CheckoutService.class);var mapper=new JsonMapper();
        var consumer=new SeckillCheckoutConsumer(service,mapper);
        String payload=mapper.writeValueAsString(new SeckillCheckoutConsumer.Accepted("event","request","account","activity","item","sku",2,"title",3000));
        assertThatThrownBy(() -> consumer.consume(payload)).isInstanceOf(IllegalArgumentException.class);
        verifyNoInteractions(service);
    }
}
