package com.sinrotic.rs.inventory.service;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.jdbc.datasource.init.ResourceDatabasePopulator;
import org.springframework.core.io.FileSystemResource;
import java.util.*;
import java.util.concurrent.*;
import static org.assertj.core.api.Assertions.*;

class ActivityStockServiceTest {
    JdbcTemplate jdbc;ActivityStockService service;
    @BeforeEach void setup() {
        var ds=new DriverManagerDataSource("jdbc:h2:mem:"+UUID.randomUUID()+";MODE=MySQL;DB_CLOSE_DELAY=-1;LOCK_TIMEOUT=10000","sa","");
        new ResourceDatabasePopulator(new FileSystemResource("../sql/rs_service_trade_schema.sql"),new FileSystemResource("../sql/rs_service_commerce_v1_schema.sql")).execute(ds);
        jdbc=new JdbcTemplate(ds);service=new ActivityStockService(jdbc,new DataSourceTransactionManager(ds));
        jdbc.update("INSERT INTO sku_stock(sku_id,item_id,available_stock) VALUES ('sku','item',10)");
    }
    void allocate() {service.allocate(new ActivityStockService.Allocation("activity","sku",5));}
    void move(String action,long order) {service.move(action,new ActivityStockService.Movement("activity",order,"sku",1));}
    int stock(String column) {return jdbc.queryForObject("SELECT "+column+" FROM sku_stock",Integer.class);}
    @Test void allocationIsIsolatedIdempotentAndCannotBeReinitialized() {
        allocate();allocate();
        assertThat(stock("available_stock")).isEqualTo(5);assertThat(stock("locked_stock")).isEqualTo(5);
        assertThatThrownBy(()->service.allocate(new ActivityStockService.Allocation("activity","sku",6))).isInstanceOf(org.springframework.web.server.ResponseStatusException.class);
        assertThatThrownBy(()->service.allocate(new ActivityStockService.Allocation("other","sku",6))).isInstanceOf(org.springframework.web.server.ResponseStatusException.class);
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM inventory_activity_pool",Integer.class)).isOne();
        // 普通买家消耗所有未划拨库存后，活动仍有自己的五件库存。
        jdbc.update("UPDATE sku_stock SET available_stock=0,locked_stock=locked_stock+5");
        move("LOCK",1);move("LOCK",1);move("CONFIRM",1);move("CONFIRM",1);
        assertThat(stock("sold_stock")).isOne();assertThat(stock("locked_stock")).isEqualTo(9);
        assertThat(service.view("activity")).containsEntry("available_quantity",4).containsEntry("sold_quantity",1);
    }
    @Test void cancelBeforeLockFencesLateLockAndReleaseStaysInPoolUntilClose() {
        allocate();move("CANCEL",1);move("CANCEL",1);
        assertThatThrownBy(()->move("LOCK",1)).isInstanceOf(org.springframework.web.server.ResponseStatusException.class);
        move("LOCK",2);move("RELEASE",2);move("RELEASE",2);
        assertThat(stock("available_stock")).isEqualTo(5);
        service.close("activity");service.close("activity");
        assertThat(stock("available_stock")).isEqualTo(10);assertThat(stock("locked_stock")).isZero();
        assertThat(service.view("activity")).containsEntry("returned_quantity",5);
        assertThatThrownBy(()->move("LOCK",3)).isInstanceOf(org.springframework.web.server.ResponseStatusException.class);
    }
    @Test void closeWaitsForReservationsAndOppositeTerminalCannotStealOtherStock() {
        allocate();move("LOCK",1);move("LOCK",2);
        assertThatThrownBy(()->service.close("activity")).isInstanceOf(org.springframework.web.server.ResponseStatusException.class);
        move("CONFIRM",1);
        assertThatThrownBy(()->move("RELEASE",1)).isInstanceOf(org.springframework.web.server.ResponseStatusException.class);
        move("CANCEL",2);service.close("activity");
        assertThat(stock("available_stock")).isEqualTo(9);assertThat(stock("locked_stock")).isZero();assertThat(stock("sold_stock")).isOne();
    }
    @Test void concurrentReservationsAndTerminalRacesConserveStock() throws Exception {
        allocate();
        try(var executor=Executors.newFixedThreadPool(8)) {
            var tasks=new ArrayList<Callable<Boolean>>();
            for(long id=1;id<=40;id++) {long order=id;tasks.add(()->{try{move("LOCK",order);return true;}catch(org.springframework.web.server.ResponseStatusException rejected){return false;}});}
            int successes=0;for(var result:executor.invokeAll(tasks)) if(result.get()) successes++;
            assertThat(successes).isEqualTo(5);
            long order=jdbc.queryForObject("SELECT order_id FROM inventory_activity_reservation LIMIT 1",Long.class);
            var start=new CountDownLatch(1);
            var confirm=executor.submit(()->{start.await();try{move("CONFIRM",order);return true;}catch(org.springframework.web.server.ResponseStatusException rejected){return false;}});
            var release=executor.submit(()->{start.await();try{move("RELEASE",order);return true;}catch(org.springframework.web.server.ResponseStatusException rejected){return false;}});
            start.countDown();assertThat(List.of(confirm.get(),release.get()).stream().filter(Boolean::booleanValue).count()).isOne();
        }
        assertThat(stock("available_stock")+stock("locked_stock")+stock("sold_stock")).isEqualTo(10);
        assertThat(service.view("activity").get("reserved_quantity")).isEqualTo(4);
    }
}
