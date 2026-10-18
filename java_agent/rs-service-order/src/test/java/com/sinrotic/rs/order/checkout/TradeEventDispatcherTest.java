package com.sinrotic.rs.order.checkout;

import com.sun.net.httpserver.HttpServer;
import org.junit.jupiter.api.*;
import org.springframework.core.io.FileSystemResource;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.*;
import org.springframework.jdbc.datasource.init.ResourceDatabasePopulator;
import org.springframework.web.client.RestClient;
import java.net.InetSocketAddress;
import java.time.LocalDateTime;
import java.util.UUID;
import java.util.concurrent.*;
import java.util.concurrent.atomic.*;
import static org.assertj.core.api.Assertions.*;

class TradeEventDispatcherTest {
    JdbcTemplate jdbc;TradeEventDispatcher dispatcher;HttpServer server;
    AtomicInteger status=new AtomicInteger(200),calls=new AtomicInteger();
    CountDownLatch entered=new CountDownLatch(1),release=new CountDownLatch(1);
    boolean block;
    @BeforeEach void setup() throws Exception {
        var ds=new DriverManagerDataSource("jdbc:h2:mem:"+UUID.randomUUID()+";MODE=MySQL;DB_CLOSE_DELAY=-1","sa","");
        new ResourceDatabasePopulator(new FileSystemResource("../sql/rs_service_trade_schema.sql"),new FileSystemResource("../sql/rs_service_commerce_v1_schema.sql")).execute(ds);
        jdbc=new JdbcTemplate(ds);
        jdbc.update("INSERT INTO commerce_order_event(event_id,order_id,event_type,payload,created_at) VALUES ('order:1:PAID',1,'PAID','{}',?)",LocalDateTime.now(java.time.Clock.systemUTC()));
        jdbc.update("INSERT INTO commerce_event_delivery(event_id,target,next_attempt_at) VALUES ('order:1:PAID','recommend',?)",LocalDateTime.now(java.time.Clock.systemUTC()).minusMinutes(1));
        server=HttpServer.create(new InetSocketAddress("127.0.0.1",0),0);
        server.createContext("/internal/recommend/commerce-events",exchange->{
            calls.incrementAndGet();entered.countDown();
            assertThat(exchange.getRequestHeaders().getFirst("Authorization")).isEqualTo("Bearer "+"s".repeat(32));
            assertThat(new String(exchange.getRequestBody().readAllBytes(),java.nio.charset.StandardCharsets.UTF_8)).isEqualTo("{}");
            if(block) try {release.await(5,TimeUnit.SECONDS);} catch(InterruptedException interrupted) {Thread.currentThread().interrupt();}
            exchange.sendResponseHeaders(status.get(),-1);exchange.close();
        });server.start();String url="http://127.0.0.1:"+server.getAddress().getPort();
        dispatcher=new TradeEventDispatcher(jdbc,new DataSourceTransactionManager(ds),RestClient.builder(),url,url,"s".repeat(32));
    }
    @AfterEach void close(){release.countDown();server.stop(0);}
    @Test void networkFailurePreservesEventAndBackoffThenReplaysSamePayload() {
        status.set(503);dispatcher.dispatch();
        assertThat(jdbc.queryForObject("SELECT attempts FROM commerce_event_delivery",Integer.class)).isOne();
        dispatcher.dispatch();assertThat(calls.get()).isOne();
        status.set(200);jdbc.update("UPDATE commerce_event_delivery SET next_attempt_at=?",LocalDateTime.now(java.time.Clock.systemUTC()).minusMinutes(1));dispatcher.dispatch();dispatcher.dispatch();
        assertThat(calls.get()).isEqualTo(2);assertThat(jdbc.queryForObject("SELECT status FROM commerce_event_delivery",String.class)).isEqualTo("DONE");
    }
    @Test void multipleInstancesDoNotConcurrentlyDeliverTheSameTask() throws Exception {
        block=true;
        try(var executor=Executors.newFixedThreadPool(2)) {
            var first=executor.submit(dispatcher::dispatch);assertThat(entered.await(5,TimeUnit.SECONDS)).isTrue();
            executor.submit(dispatcher::dispatch).get(5,TimeUnit.SECONDS);assertThat(calls.get()).isOne();release.countDown();first.get(5,TimeUnit.SECONDS);
        }
    }
    @Test void exhaustedDeliveryNeedsAuditedRetryAndKeepsOriginalEventId() {
        jdbc.update("UPDATE commerce_event_delivery SET attempts=19");status.set(503);dispatcher.dispatch();
        assertThat(jdbc.queryForObject("SELECT status FROM commerce_event_delivery",String.class)).isEqualTo("REVIEW_REQUIRED");
        dispatcher.retry("order:1:PAID","recommend","operator","已修复接收器");status.set(200);dispatcher.dispatch();
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM commerce_order_event",Integer.class)).isOne();
        assertThat(jdbc.queryForObject("SELECT operator_id FROM commerce_operation_audit",String.class)).isEqualTo("operator");
    }
}
