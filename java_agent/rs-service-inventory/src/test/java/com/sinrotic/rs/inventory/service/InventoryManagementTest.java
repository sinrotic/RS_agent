package com.sinrotic.rs.inventory.service;
import org.junit.jupiter.api.*;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.*;
import org.springframework.jdbc.datasource.init.ResourceDatabasePopulator;
import org.springframework.core.io.FileSystemResource;
import org.springframework.web.server.ResponseStatusException;
import java.util.*;
import static org.assertj.core.api.Assertions.*;
class InventoryManagementTest {
    JdbcTemplate jdbc;InventoryManagement service;
    @BeforeEach void setup() {
        var ds=new DriverManagerDataSource("jdbc:h2:mem:"+UUID.randomUUID()+";MODE=MySQL;DB_CLOSE_DELAY=-1","sa","");
        new ResourceDatabasePopulator(new FileSystemResource("../sql/rs_service_trade_schema.sql"),new FileSystemResource("../sql/rs_service_commerce_v1_schema.sql")).execute(ds);
        jdbc=new JdbcTemplate(ds);service=new InventoryManagement(jdbc,new DataSourceTransactionManager(ds));
    }
    void receipt() {service.adjust(new InventoryManagement.Adjustment("receipt","sku","item","RECEIPT",10,null,"采购入库"),"operator");}
    @Test void backgroundReconciliationWrapsEmptyCursorAndRechecksResolvedStock() {
        receipt();jdbc.update("UPDATE sku_stock SET available_stock=9");service.tick();assertThat(service.cases()).hasSize(1);
        jdbc.update("UPDATE sku_stock SET available_stock=10");service.tick();assertThat(service.cases()).isEmpty();
        assertThat(jdbc.queryForObject("SELECT after_sku_id FROM inventory_reconciliation_cursor",String.class)).isEmpty();
    }
    @Test void receiptIsIdempotentAndStocktakeRejectsStaleVersionAndReservedShortage() {
        receipt();receipt();assertThat(service.check("sku")).containsEntry("healthy",true);
        assertThat(jdbc.queryForObject("SELECT available_stock FROM sku_stock",Integer.class)).isEqualTo(10);
        jdbc.update("UPDATE sku_stock SET locked_stock=3,available_stock=7,version=version+1");
        assertThatThrownBy(()->service.adjust(new InventoryManagement.Adjustment("count","sku","item","STOCKTAKE",9,1L,"盘点"),"operator")).isInstanceOf(ResponseStatusException.class);
        assertThatThrownBy(()->service.adjust(new InventoryManagement.Adjustment("count","sku","item","STOCKTAKE",2,2L,"盘点"),"operator")).isInstanceOf(ResponseStatusException.class);
        service.adjust(new InventoryManagement.Adjustment("count","sku","item","STOCKTAKE",9,2L,"盘点"),"operator");
        assertThat(jdbc.queryForObject("SELECT available_stock FROM sku_stock",Integer.class)).isEqualTo(6);
    }
    @Test void reconciliationRecordsDiscrepancyAndOnlyResolvesAfterHealthyRecheck() {
        receipt();jdbc.update("UPDATE sku_stock SET available_stock=9");
        assertThat(service.check("sku")).containsEntry("healthy",false);
        String id=(String)service.cases().getFirst().get("case_id");service.acknowledge(id,"operator","核对仓库实物");
        assertThat(service.cases().getFirst()).containsEntry("status","ACKNOWLEDGED");
        jdbc.update("UPDATE sku_stock SET available_stock=10");assertThat(service.check("sku")).containsEntry("healthy",true);
        assertThat(service.cases()).isEmpty();
    }
    @Test void adjustmentCannotReuseKeyForDifferentSkuOrQuantity() {
        receipt();assertThatThrownBy(()->service.adjust(new InventoryManagement.Adjustment("receipt","sku","item","RECEIPT",20,null,"采购入库"),"operator")).isInstanceOf(ResponseStatusException.class);
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM inventory_adjustment",Integer.class)).isOne();
    }
}
