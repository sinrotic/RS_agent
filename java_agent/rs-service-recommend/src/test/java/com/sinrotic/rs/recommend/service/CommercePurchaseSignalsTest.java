package com.sinrotic.rs.recommend.service;
import com.sinrotic.rs.common.commerce.TradeEvent;
import com.sinrotic.rs.recommend.service.impl.CommercePurchaseSignals;
import org.junit.jupiter.api.*;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.*;
import org.springframework.jdbc.datasource.init.ResourceDatabasePopulator;
import org.springframework.core.io.FileSystemResource;
import java.util.*;
import static org.assertj.core.api.Assertions.*;
class CommercePurchaseSignalsTest {
    CommercePurchaseSignals service;JdbcTemplate jdbc;
    final java.time.LocalDateTime occurredAt=java.time.LocalDateTime.now(java.time.Clock.systemUTC());
    @BeforeEach void setup() {
        var ds=new DriverManagerDataSource("jdbc:h2:mem:"+UUID.randomUUID()+";MODE=MySQL;DB_CLOSE_DELAY=-1","sa","");
        new ResourceDatabasePopulator(new FileSystemResource("../sql/rs_service_trade_schema.sql"),new FileSystemResource("../sql/rs_service_commerce_v1_schema.sql")).execute(ds);
        jdbc=new JdbcTemplate(ds);service=new CommercePurchaseSignals(jdbc,new DataSourceTransactionManager(ds));
    }
    TradeEvent event(long order,String type,boolean mock) {return new TradeEvent(order+":"+type,order,type.equals("PAID")?1:2,type,"account","profile",null,null,"item",1,3000,mock?"mock":"verified-provider",mock,occurredAt);}
    @Test void realPurchaseActivatesOnceAndRefundOnlyRemovesItsOwnSignal() {
        service.accept(event(1,"PAID",false));service.accept(event(1,"PAID",false));service.accept(event(2,"PAID",false));
        assertThat(service.load("profile",List.of("item"))).containsEntry("item",2);
        service.accept(event(1,"REFUNDED",false));assertThat(service.load("profile",List.of("item"))).containsEntry("item",1);
        assertThat(service.load("another",List.of("item"))).isEmpty();
    }
    @Test void refundBeforePaymentCannotBeReactivatedAndMockNeverChangesProfile() {
        service.accept(event(1,"REFUNDED",false));service.accept(event(1,"PAID",false));service.accept(event(2,"PAID",true));
        assertThat(service.load("profile",List.of("item"))).isEmpty();
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM recommendation_trade_event",Integer.class)).isEqualTo(3);
    }
    @Test void delayedDeliveryDoesNotTurnOldPurchaseIntoRecentPreference() {
        var old=event(1,"PAID",false);
        service.accept(new TradeEvent(old.eventId(),old.orderId(),old.version(),old.type(),old.accountId(),old.profileUserId(),null,null,old.itemId(),old.quantity(),old.amount(),old.provider(),false,occurredAt.minusDays(181)));
        assertThat(service.load("profile",List.of("item"))).isEmpty();
    }
}
