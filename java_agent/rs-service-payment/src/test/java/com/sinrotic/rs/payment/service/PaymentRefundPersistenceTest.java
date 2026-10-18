package com.sinrotic.rs.payment.service;
import org.junit.jupiter.api.*;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.*;
import org.springframework.jdbc.datasource.init.ResourceDatabasePopulator;
import org.springframework.core.io.FileSystemResource;
import org.springframework.web.client.RestClient;
import org.springframework.web.server.ResponseStatusException;
import com.sun.net.httpserver.HttpServer;
import java.net.*;
import java.nio.charset.StandardCharsets;
import java.util.*;
import static org.assertj.core.api.Assertions.*;
class PaymentRefundPersistenceTest {
    JdbcTemplate jdbc;PaymentRefundService service;HttpServer server;String secret="s".repeat(32);String quoteStatus="REFUNDING";
    @BeforeEach void setup() throws Exception {
        var ds=new DriverManagerDataSource("jdbc:h2:mem:"+UUID.randomUUID()+";MODE=MySQL;DB_CLOSE_DELAY=-1","sa","");
        new ResourceDatabasePopulator(new FileSystemResource("../sql/rs_service_trade_schema.sql"),new FileSystemResource("../sql/rs_service_commerce_v1_schema.sql")).execute(ds);
        jdbc=new JdbcTemplate(ds);server=HttpServer.create(new InetSocketAddress("127.0.0.1",0),0);
        server.createContext("/internal/checkout/orders/10/refund-quote",exchange->{
            String body="{\"orderId\":10,\"accountId\":\"account\",\"amount\":3000,\"provider\":\"mock\",\"mock\":true,\"status\":\""+quoteStatus+"\"}";
            byte[] bytes=body.getBytes(StandardCharsets.UTF_8);exchange.getResponseHeaders().set("Content-Type","application/json");exchange.sendResponseHeaders(200,bytes.length);exchange.getResponseBody().write(bytes);exchange.close();
        });server.start();
        service=new PaymentRefundService(jdbc,new DataSourceTransactionManager(ds),RestClient.builder(),"http://127.0.0.1:"+server.getAddress().getPort(),"t".repeat(32),true,secret);
    }
    @AfterEach void close() {server.stop(0);}
    PaymentRefundService.Request request(String scenario,boolean retry) {return new PaymentRefundService.Request("refund",10,3000,scenario,retry);}
    PaymentRefundService.Callback callback(String status) {
        String tx="mock-refund-refund";
        return new PaymentRefundService.Callback("refund",10,3000,tx,status,MockPaymentCallbackSignature.sign(secret,"mock-refund:"+status,tx,10L,3000L,"refund"));
    }
    @Test void responseLostCommitsProviderFactAndReplayCannotRefundTwice() {
        assertThatThrownBy(()->service.refund(request("RESPONSE_LOST",false))).isInstanceOf(ResponseStatusException.class);
        assertThat(jdbc.queryForObject("SELECT status FROM payment_refund",String.class)).isEqualTo("SUCCEEDED");
        assertThat(service.refund(request("RESPONSE_LOST",false)).status()).isEqualTo("SUCCEEDED");
        assertThat(jdbc.queryForObject("SELECT attempts FROM payment_refund",Integer.class)).isOne();
        assertThatThrownBy(()->service.refund(new PaymentRefundService.Request("different",10,3000,"SUCCESS",false))).isInstanceOf(ResponseStatusException.class);
    }
    @Test void signedDuplicateCallbackResolvesPendingButCannotReverseSuccess() {
        assertThatThrownBy(()->service.refund(request("TIMEOUT_BEFORE_PAYMENT",false))).isInstanceOf(ResponseStatusException.class);
        service.callback(callback("SUCCEEDED"));service.callback(callback("SUCCEEDED"));
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM payment_refund_callback",Integer.class)).isOne();
        assertThatThrownBy(()->service.callback(callback("FAILED"))).isInstanceOf(ResponseStatusException.class);
        assertThat(jdbc.queryForObject("SELECT status FROM payment_refund",String.class)).isEqualTo("SUCCEEDED");
    }
    @Test void declinedRefundNeedsExplicitRetryAndAuthoritativeAmountCannotChange() {
        assertThat(service.refund(request("DECLINED",false)).status()).isEqualTo("FAILED");
        assertThat(service.refund(request("SUCCESS",false)).status()).isEqualTo("FAILED");
        assertThat(service.refund(request("SUCCESS",true)).status()).isEqualTo("SUCCEEDED");
        assertThatThrownBy(()->service.refund(new PaymentRefundService.Request("refund",10,3001,"SUCCESS",true))).isInstanceOf(ResponseStatusException.class);
    }
    @Test void forgedCallbackCannotChangeProviderState() {
        assertThatThrownBy(()->service.refund(request("TIMEOUT_BEFORE_PAYMENT",false))).isInstanceOf(ResponseStatusException.class);
        var valid=callback("SUCCEEDED");
        assertThatThrownBy(()->service.callback(new PaymentRefundService.Callback(valid.refundId(),10,3001,valid.transactionId(),valid.status(),valid.signature()))).isInstanceOf(ResponseStatusException.class);
        assertThat(jdbc.queryForObject("SELECT status FROM payment_refund",String.class)).isEqualTo("PENDING");
    }
    @Test void latePaymentOnCanceledOrderRequiresOwnVerifiedPaymentAndDurableCompensation() {
        quoteStatus="CANCELED";
        assertThatThrownBy(()->service.refund(request("SUCCESS",false))).isInstanceOf(ResponseStatusException.class);
        jdbc.update("INSERT INTO payment_orders(payment_id,order_id,provider,status,amount) VALUES (1,10,'mock','PAID',3000)");
        jdbc.update("INSERT INTO payment_order_notifications(order_id,provider,provider_transaction_id,status,next_attempt_at) VALUES (10,'mock','late-tx','REVIEW',CURRENT_TIMESTAMP)");
        assertThat(service.refund(request("SUCCESS",false)).status()).isEqualTo("SUCCEEDED");
        assertThat(service.refund(request("SUCCESS",false)).moneyMoved()).isFalse();
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM payment_refund",Integer.class)).isOne();
    }
}
