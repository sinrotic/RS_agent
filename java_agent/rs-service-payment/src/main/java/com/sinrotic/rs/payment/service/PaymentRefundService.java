package com.sinrotic.rs.payment.service;

import com.sinrotic.rs.common.commerce.CommerceInput;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;
import org.springframework.web.client.RestClient;
import org.springframework.http.HttpStatus;
import org.springframework.web.server.ResponseStatusException;
import java.time.*;
import java.util.*;
import java.security.MessageDigest;
import java.nio.charset.StandardCharsets;

@Service
public class PaymentRefundService {
    public record Request(String refundId,long orderId,long amount,String scenario,boolean retryFailed) {}
    public record Result(String refundId,String status,boolean mock,boolean moneyMoved) {}
    public record Callback(String refundId,long orderId,long amount,String transactionId,String status,String signature) {}
    public record Quote(long orderId,String accountId,long amount,String provider,boolean mock,String status) {}
    private final JdbcTemplate jdbc;private final TransactionTemplate tx;private final RestClient orders;
    private final boolean enabled;private final String token,secret;
    public PaymentRefundService(JdbcTemplate jdbc,PlatformTransactionManager manager,RestClient.Builder builder,
            @Value("${rs.order.base-url:http://localhost:8091}") String orderUrl,@Value("${rs.commerce.service-token:}") String token,
            @Value("${rs.payment.mock-refund-enabled:false}") boolean enabled,@Value("${rs.payment.mock-callback-secret:}") String secret) {
        this.jdbc=jdbc;tx=new TransactionTemplate(manager);this.enabled=enabled;this.token=token;this.secret=secret;
        var factory=new org.springframework.http.client.SimpleClientHttpRequestFactory();factory.setConnectTimeout(2000);factory.setReadTimeout(3000);
        orders=builder.baseUrl(orderUrl).requestFactory(factory).build();
    }
    public Result refund(Request input) {
        if(!enabled) throw new ResponseStatusException(HttpStatus.NOT_FOUND);
        if(input==null || input.orderId()<=0 || input.amount()<=0) throw CommerceInput.bad("退款参数不合法");CommerceInput.id(input.refundId());
        if(input.scenario()==null || !List.of("SUCCESS","DECLINED","TIMEOUT_BEFORE_PAYMENT","RESPONSE_LOST").contains(input.scenario())) throw CommerceInput.bad("退款场景不合法");
        // 网络查询发生在事务外；金额、支付来源由原订单/支付事实裁决，调用者不能决定金额。
        var quote=orders.get().uri("/internal/checkout/orders/{id}/refund-quote",input.orderId()).header("Authorization","Bearer "+token).retrieve().body(Quote.class);
        if(quote==null || quote.orderId()!=input.orderId() || quote.amount()!=input.amount()) throw CommerceInput.conflict("退款金额与原订单不匹配");
        boolean normal=quote.mock() && "mock".equals(quote.provider()) && List.of("PAID","REFUNDING","REFUNDED").contains(quote.status());
        if(!normal) {
            var paid=jdbc.queryForList("SELECT p.amount FROM payment_orders p JOIN payment_order_notifications n ON n.order_id=p.order_id WHERE p.order_id=? AND p.status='PAID' AND p.provider='mock' AND n.status IN ('REVIEW','MOCK_REFUNDED')",input.orderId());
            if(!List.of("CANCELED","TIMEOUT_CLOSED").contains(quote.status()) || paid.isEmpty()
                    || input.amount()!=((Number)paid.getFirst().get("amount")).longValue()) throw CommerceInput.conflict("退款与可信的模拟支付事实不匹配");
        }
        Result result=tx.execute(s -> {
            jdbc.update("INSERT INTO payment_refund_guard(order_id) VALUES (?) ON DUPLICATE KEY UPDATE order_id=order_id",input.orderId());
            jdbc.queryForMap("SELECT order_id FROM payment_refund_guard WHERE order_id=? FOR UPDATE",input.orderId());
            var rows=jdbc.queryForList("SELECT * FROM payment_refund WHERE order_id=? FOR UPDATE",input.orderId());
            if(rows.isEmpty()) {
                jdbc.update("INSERT INTO payment_refund(refund_id,order_id,amount,provider,transaction_id,status,scenario,created_at,updated_at) VALUES (?,?,?,'mock',?,'PENDING',?,?,?)",
                        input.refundId(),input.orderId(),input.amount(),"mock-refund-"+input.refundId(),input.scenario(),now(),now());
            } else {
                var row=rows.getFirst();
                if(!input.refundId().equals(row.get("refund_id")) || input.amount()!=((Number)row.get("amount")).longValue()) throw CommerceInput.conflict("原订单已有不同退款请求");
                if("SUCCEEDED".equals(row.get("status"))) return new Result(input.refundId(),"SUCCEEDED",true,false);
                if("FAILED".equals(row.get("status"))) {
                    if(!input.retryFailed()) return new Result(input.refundId(),"FAILED",true,false);
                    jdbc.update("UPDATE payment_refund SET status='PENDING',scenario='SUCCESS' WHERE refund_id=?",input.refundId());
                }
            }
            var row=jdbc.queryForMap("SELECT * FROM payment_refund WHERE refund_id=?",input.refundId());
            int attempts=((Number)row.get("attempts")).intValue()+1;String scenario=(String)row.get("scenario");
            String status=scenario.equals("DECLINED") ? "FAILED" : scenario.equals("TIMEOUT_BEFORE_PAYMENT") && attempts==1 ? "PENDING" : "SUCCEEDED";
            jdbc.update("UPDATE payment_refund SET status=?,attempts=?,updated_at=? WHERE refund_id=?",status,attempts,now(),input.refundId());
            return new Result(input.refundId(),scenario.equals("RESPONSE_LOST") && attempts==1 ? "RESPONSE_LOST" : status,true,false);
        });
        // 先提交模拟退款事实，再注入响应丢失；重试返回同一退款的 SUCCEEDED。
        if(result.status().equals("RESPONSE_LOST") || result.status().equals("PENDING")) throw new ResponseStatusException(HttpStatus.GATEWAY_TIMEOUT,"模拟退款结果待回查");
        return result;
    }
    public void callback(Callback input) {
        if(!enabled) throw new ResponseStatusException(HttpStatus.NOT_FOUND);
        if(input==null || input.status()==null || !List.of("SUCCEEDED","FAILED").contains(input.status()) || secret.getBytes(StandardCharsets.UTF_8).length<32) throw CommerceInput.bad("退款回调参数或密钥不合法");
        CommerceInput.id(input.refundId());if(input.transactionId()==null || input.transactionId().length()>128 || input.signature()==null) throw CommerceInput.bad("退款流水不合法");
        String signature=MockPaymentCallbackSignature.sign(secret,"mock-refund:"+input.status(),input.transactionId(),input.orderId(),input.amount(),input.refundId());
        if(!MessageDigest.isEqual(signature.getBytes(StandardCharsets.US_ASCII),input.signature().getBytes(StandardCharsets.US_ASCII))) throw new ResponseStatusException(HttpStatus.UNAUTHORIZED,"退款回调签名不匹配");
        tx.executeWithoutResult(s -> {
            var rows=jdbc.queryForList("SELECT * FROM payment_refund WHERE refund_id=? FOR UPDATE",input.refundId());
            if(rows.isEmpty()) throw CommerceInput.missing("退款记录不存在");var row=rows.getFirst();
            if(input.orderId()!=((Number)row.get("order_id")).longValue() || input.amount()!=((Number)row.get("amount")).longValue()
                    || !input.transactionId().equals(row.get("transaction_id"))) throw CommerceInput.conflict("退款回调与原记录不符");
            if("SUCCEEDED".equals(row.get("status")) && !input.status().equals("SUCCEEDED")) throw CommerceInput.conflict("成功退款不能被失败回调覆盖");
            if(jdbc.queryForObject("SELECT COUNT(*) FROM payment_refund_callback WHERE refund_id=? AND transaction_id=? AND status=?",Integer.class,input.refundId(),input.transactionId(),input.status())==0)
                jdbc.update("INSERT INTO payment_refund_callback(refund_id,transaction_id,status,amount,created_at) VALUES (?,?,?,?,?)",input.refundId(),input.transactionId(),input.status(),input.amount(),now());
            jdbc.update("UPDATE payment_refund SET status=?,updated_at=? WHERE refund_id=?",input.status(),now(),input.refundId());
        });
    }
    private static LocalDateTime now() {return LocalDateTime.now(Clock.systemUTC());}
}
