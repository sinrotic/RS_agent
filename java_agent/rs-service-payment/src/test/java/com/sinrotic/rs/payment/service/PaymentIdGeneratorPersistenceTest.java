package com.sinrotic.rs.payment.service;

import org.junit.jupiter.api.Test;
import org.springframework.context.annotation.*;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.jdbc.datasource.init.ResourceDatabasePopulator;
import org.springframework.core.io.FileSystemResource;
import java.util.*;
import java.util.concurrent.*;
import static org.assertj.core.api.Assertions.*;

class PaymentIdGeneratorPersistenceTest {
    @Configuration
    @ComponentScan(basePackageClasses=IdGenerator.class,useDefaultFilters=false,
            includeFilters=@ComponentScan.Filter(type=FilterType.ASSIGNABLE_TYPE,classes=IdGenerator.class))
    static class GeneratorConfiguration {}

    AnnotationConfigApplicationContext context(JdbcTemplate jdbc) {
        var context = new AnnotationConfigApplicationContext();
        context.registerBean(JdbcTemplate.class,() -> jdbc);
        context.register(GeneratorConfiguration.class);
        context.refresh();
        return context;
    }
    @Test
    void independentProcessesAndRestartCannotReusePersistedPaymentIds() throws Exception {
        var ds = new DriverManagerDataSource("jdbc:h2:mem:"+UUID.randomUUID()+";MODE=MySQL;DB_CLOSE_DELAY=-1","sa","");
        var migration = new ResourceDatabasePopulator(new FileSystemResource("../sql/rs_service_trade_schema.sql"));
        migration.execute(ds);
        JdbcTemplate jdbc = new JdbcTemplate(ds);
        Set<Long> ids = ConcurrentHashMap.newKeySet();
        try(var first = context(jdbc)) {
            IdGenerator generator = first.getBean(IdGenerator.class);
            for(int i=0;i<10000;i++) assertThat(ids.add(generator.nextId())).isTrue();
        }
        try(var restarted = context(jdbc); var other = context(jdbc); var pool = Executors.newFixedThreadPool(4)) {
            var jobs = new ArrayList<Callable<Void>>();
            for(int i=0;i<4;i++) {
                IdGenerator generator = (i%2==0 ? restarted : other).getBean(IdGenerator.class);
                jobs.add(() -> { for(int j=0;j<100;j++) assertThat(ids.add(generator.nextId())).isTrue(); return null; });
            }
            for(var result : pool.invokeAll(jobs)) result.get();
        }
        assertThat(ids).hasSize(10400);
        long legacyId = 2_000_000_000_000L;
        jdbc.update("INSERT INTO payment_orders(payment_id,order_id,provider,amount,status) VALUES (?,123,'mock',500,'WAITING_PAY')",legacyId);
        migration.execute(ds);
        try(var upgraded = context(jdbc)) {
            assertThat(upgraded.getBean(IdGenerator.class).nextId()).isGreaterThan(legacyId);
        }
        migration.execute(ds);
        try(var restarted = context(jdbc)) {
            assertThat(ids.add(restarted.getBean(IdGenerator.class).nextId())).isTrue();
        }
    }
}
