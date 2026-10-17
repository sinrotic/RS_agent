package com.sinrotic.rs.payment.service;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;
import org.springframework.web.server.ResponseStatusException;
import java.time.LocalDateTime;
import java.time.Clock;
import java.util.List;
import java.util.Map;

@Service
public class PaymentOperationsService {
    private final JdbcTemplate jdbc;
    private final TransactionTemplate tx;
    private final boolean mockRefundEnabled;
    public record OperatorAction(String operatorId,String reason) {}
    public record TaskView(long orderId,String status,int attempts,String lastError,LocalDateTime nextAttemptAt) {}
    public record MockRefundResult(long orderId,String status,boolean mock,boolean moneyMoved) {}
    public PaymentOperationsService(JdbcTemplate jdbc,PlatformTransactionManager manager,
            @Value("${rs.payment.mock-refund-enabled:false}") boolean mockRefundEnabled) {
        this.jdbc=jdbc;this.tx=new TransactionTemplate(manager);this.mockRefundEnabled=mockRefundEnabled;
    }
    public List<TaskView> tasks(int minimumAgeSeconds) {
        if(minimumAgeSeconds<0 || minimumAgeSeconds>2592000) throw bad("查询年龄范围不合法");
        // 通知表使用数据库时间；到期时间超过阈值的任务才算停滞，正常退避不告警。
        return jdbc.query("""
                SELECT * FROM payment_order_notifications
                WHERE status='REVIEW' OR (status IN ('PENDING','PROCESSING') AND next_attempt_at<=TIMESTAMPADD(SECOND,?,CURRENT_TIMESTAMP(6)))
                ORDER BY next_attempt_at,order_id LIMIT 100
                """,(r,n)->new TaskView(r.getLong("order_id"),r.getString("status"),r.getInt("attempts"),
                r.getString("last_error"),r.getObject("next_attempt_at",LocalDateTime.class)),-minimumAgeSeconds);
    }
    public Map<String,Long> summary() {
        return jdbc.queryForObject("""
                SELECT COALESCE(SUM(CASE WHEN status IN ('PENDING','PROCESSING','REVIEW') THEN 1 ELSE 0 END),0) AS pending,
                COALESCE(SUM(CASE WHEN status='REVIEW' THEN 1 ELSE 0 END),0) AS review_count
                FROM payment_order_notifications
                """,(r,n)->Map.of("pending",r.getLong("pending"),"reviewRequired",r.getLong("review_count")));
    }
    public void retry(long orderId,OperatorAction action) { update(orderId,action,false); }
    public MockRefundResult mockRefund(long orderId,OperatorAction action) {
        if(!mockRefundEnabled) throw new ResponseStatusException(HttpStatus.NOT_FOUND);
        update(orderId,action,true);
        return new MockRefundResult(orderId,"MOCK_REFUNDED",true,false);
    }
    private void update(long orderId,OperatorAction action,boolean refund) {
        if(orderId<=0 || action==null || action.operatorId()==null || action.operatorId().isBlank()
                || action.operatorId().length()>64 || !action.operatorId().equals(action.operatorId().trim())
                || action.reason()==null || action.reason().isBlank() || action.reason().length()>255) throw bad("操作人和原因不合法");
        tx.executeWithoutResult(s -> {
            var rows=jdbc.queryForList("SELECT status FROM payment_order_notifications WHERE order_id=? FOR UPDATE",orderId);
            if(rows.isEmpty()) throw new ResponseStatusException(HttpStatus.NOT_FOUND,"支付通知不存在");
            if(refund && "MOCK_REFUNDED".equals(rows.getFirst().get("status"))) return;
            if(!"REVIEW".equals(rows.getFirst().get("status"))) throw new ResponseStatusException(HttpStatus.CONFLICT,"仅可处理待核对通知");
            if(refund) {
                var payments=jdbc.queryForList("SELECT provider,status FROM payment_orders WHERE order_id=? FOR UPDATE",orderId);
                if(payments.isEmpty() || !"mock".equals(payments.getFirst().get("provider"))
                        || !"PAID".equals(payments.getFirst().get("status")))
                    throw new ResponseStatusException(HttpStatus.CONFLICT,"模拟退款仅适用于 mock 提供方的已支付记录");
            }
            jdbc.update("""
                    UPDATE payment_order_notifications SET status=?,attempts=0,next_attempt_at=CURRENT_TIMESTAMP(6),
                    claim_token=NULL,lease_until=NULL,last_error=NULL WHERE order_id=?
                    """,refund ? "MOCK_REFUNDED" : "PENDING",orderId);
            jdbc.update("""
                    INSERT INTO commerce_operation_audit(component,resource_id,operator_id,action,reason,created_at)
                    VALUES ('payment',?,?,?,?,?)
                    """,Long.toString(orderId),action.operatorId(),refund ? "MOCK_REFUND" : "RETRY",action.reason(),LocalDateTime.now(Clock.systemUTC()));
        });
    }
    private static ResponseStatusException bad(String reason) { return new ResponseStatusException(HttpStatus.BAD_REQUEST,reason); }
}
