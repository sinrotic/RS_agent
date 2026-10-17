package com.sinrotic.rs.inventory.service;

import com.sinrotic.rs.inventory.mapper.*;
import com.sinrotic.rs.inventory.domain.dto.*;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mybatis.spring.SqlSessionFactoryBean;
import org.mybatis.spring.SqlSessionTemplate;
import org.springframework.core.io.FileSystemResource;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.jdbc.datasource.init.ResourceDatabasePopulator;
import org.springframework.transaction.support.TransactionTemplate;

import java.util.*;
import java.util.concurrent.*;
import static org.assertj.core.api.Assertions.*;

class InventoryConcurrencyTest {
    JdbcTemplate jdbc;
    InventoryService service;
    TransactionTemplate tx;
    @BeforeEach
    void setup() throws Exception {
        var ds=new DriverManagerDataSource("jdbc:h2:mem:"+UUID.randomUUID()+";MODE=MySQL;DB_CLOSE_DELAY=-1;LOCK_TIMEOUT=10000","sa","");
        new ResourceDatabasePopulator(new FileSystemResource("../sql/rs_service_trade_schema.sql")).execute(ds);
        jdbc=new JdbcTemplate(ds);
        jdbc.update("INSERT INTO sku_stock(sku_id,item_id,available_stock) VALUES ('sku','item',10)");
        var factory=new SqlSessionFactoryBean(); factory.setDataSource(ds);
        factory.setMapperLocations(new FileSystemResource("src/main/resources/mapper/SkuStockMapper.xml"),
                new FileSystemResource("src/main/resources/mapper/StockLogMapper.xml"));
        var configuration=new org.apache.ibatis.session.Configuration();
        configuration.setMapUnderscoreToCamelCase(true);factory.setConfiguration(configuration);
        var session=new SqlSessionTemplate(Objects.requireNonNull(factory.getObject()));
        service=new InventoryService(session.getMapper(SkuStockMapper.class),session.getMapper(StockLogMapper.class));
        tx=new TransactionTemplate(new DataSourceTransactionManager(ds));
    }
    void run(Runnable action) { tx.executeWithoutResult(status -> action.run()); }
    void lock(long id) { run(() -> service.lockStock(new InventoryLockRequestDTO("lock-"+id,id,"sku",1))); }
    void confirm(long id) { run(() -> service.confirmDeduct(new InventoryConfirmRequestDTO("confirm-"+id,id,"sku",1))); }
    void release(long id) { run(() -> service.releaseStock(new InventoryReleaseRequestDTO("release-"+id,id,"sku",1))); }
    void cancel(long id) { run(() -> service.cancelReservation(new InventoryReleaseRequestDTO("cancel-"+id,id,"sku",1))); }
    int quantity(String column) { return jdbc.queryForObject("SELECT "+column+" FROM sku_stock WHERE sku_id='sku'",Integer.class); }

    @Test
    void cancellationBeforeLockIsDurableAndDoesNotConsumeAnotherOrdersStock() {
        lock(2);
        cancel(1); cancel(1);
        assertThatThrownBy(() -> lock(1)).isInstanceOf(InventoryServiceException.class);
        assertThatThrownBy(() -> confirm(1)).isInstanceOf(InventoryServiceException.class);
        assertThat(quantity("locked_stock")).isEqualTo(1);
        assertThat(quantity("available_stock")).isEqualTo(9);
        confirm(2);
        assertThat(quantity("sold_stock")).isEqualTo(1);
    }

    @Test
    void lockAndCancellationRaceAlwaysEndsWithNoReservation() throws Exception {
        try(var pool=Executors.newFixedThreadPool(2)) {
            var start=new CountDownLatch(1);
            var first=pool.submit(() -> { start.await(); try {lock(1);}catch(InventoryServiceException ignored){} return null; });
            var second=pool.submit(() -> { start.await();cancel(1);return null; });
            start.countDown();first.get();second.get();
        }
        cancel(1);
        assertThat(quantity("available_stock")).isEqualTo(10);
        assertThat(quantity("locked_stock")).isZero();
        assertThatThrownBy(() -> lock(1)).isInstanceOf(InventoryServiceException.class);
    }

    @Test
    void cancellationCannotUndoConfirmedStock() {
        lock(1);confirm(1);
        assertThatThrownBy(() -> cancel(1)).isInstanceOf(InventoryServiceException.class);
        assertThat(quantity("sold_stock")).isEqualTo(1);
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM stock_logs WHERE type='CANCEL'",Integer.class)).isZero();
    }

    @Test
    void oppositeTerminalOperationCannotConsumeAnotherOrdersReservation() {
        lock(1);lock(2);release(1);
        assertThatThrownBy(() -> confirm(1)).isInstanceOf(InventoryServiceException.class);
        assertThat(quantity("locked_stock")).isEqualTo(1);
        assertThat(quantity("available_stock")).isEqualTo(9);
        confirm(2);confirm(2);
        assertThat(quantity("sold_stock")).isEqualTo(1);
        assertThat(quantity("locked_stock")).isZero();
    }

    @Test
    void racingConfirmAndReleaseHaveExactlyOneWinner() throws Exception {
        lock(1);lock(2);
        try(var pool=Executors.newFixedThreadPool(2)) {
            var start=new CountDownLatch(1);
            var first=pool.submit(() -> { start.await(); try {confirm(1);return true;}catch(InventoryServiceException ex){return false;} });
            var second=pool.submit(() -> { start.await(); try {release(1);return true;}catch(InventoryServiceException ex){return false;} });
            start.countDown();
            assertThat(List.of(first.get(),second.get()).stream().filter(Boolean::booleanValue).count()).isEqualTo(1);
        }
        assertThat(quantity("locked_stock")).isEqualTo(1);
        assertThat(quantity("available_stock")+quantity("locked_stock")+quantity("sold_stock")).isEqualTo(10);
    }

    @Test
    void concurrentReservationsNeverOversellAndFailedTransactionsLeaveNoLogs() throws Exception {
        try(var pool=Executors.newFixedThreadPool(8)) {
            var tasks=new ArrayList<Callable<Boolean>>();
            for(int i=1;i<=40;i++) { long id=i;tasks.add(() -> {try{lock(id);return true;}catch(InventoryServiceException ex){return false;}}); }
            int successes=0;
            for(var result:pool.invokeAll(tasks)) if(result.get()) successes++;
            assertThat(successes).isEqualTo(10);
        }
        assertThat(quantity("available_stock")).isZero();
        assertThat(quantity("locked_stock")).isEqualTo(10);
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM stock_logs",Integer.class)).isEqualTo(10);
    }

    @Test
    void duplicateConcurrentLockIsAppliedOnce() throws Exception {
        try(var pool=Executors.newFixedThreadPool(6)) {
            var tasks=new ArrayList<Callable<Void>>();
            for(int i=0;i<12;i++) tasks.add(() -> {lock(1);return null;});
            for(var result:pool.invokeAll(tasks)) result.get();
        }
        assertThat(quantity("available_stock")).isEqualTo(9);
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM stock_logs",Integer.class)).isEqualTo(1);
    }
}
