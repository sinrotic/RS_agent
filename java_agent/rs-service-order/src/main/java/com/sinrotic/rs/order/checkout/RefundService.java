package com.sinrotic.rs.order.checkout;

import com.sinrotic.rs.common.commerce.*;
import com.sinrotic.rs.order.client.InventoryClient;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;
import org.springframework.web.client.HttpClientErrorException;
import java.time.*;
import java.util.*;
import static com.sinrotic.rs.common.commerce.CommerceInput.*;

@Service
public class RefundService {
    public record Request(String requestId,String reason,String scenario) {}
    public record View(String refundId,long orderId,long amount,String status,String phase,String reason,String lastError) {}
    public record Quote(long orderId,String accountId,long amount,String provider,boolean mock,String status) {}
    private final JdbcTemplate jdbc;private final TransactionTemplate tx;private final WorkerLeaseStore leases;
    private final RefundPaymentClient payment;private final InventoryClient inventory;private final PromotionClient promotion;
    public RefundService(JdbcTemplate jdbc,PlatformTransactionManager manager,RefundPaymentClient payment,InventoryClient inventory,PromotionClient promotion) {
        this.jdbc=jdbc;tx=new TransactionTemplate(manager);leases=new WorkerLeaseStore(jdbc);this.payment=payment;this.inventory=inventory;this.promotion=promotion;
    }
    public View request(String account,long orderId,Request input) {
        id(account);if(input==null) throw bad("退款请求不能为空");id(input.requestId());String reason=reason(input.reason());
        String scenario=input.scenario()==null ? "SUCCESS" : input.scenario();
        if(!List.of("SUCCESS","DECLINED","TIMEOUT_BEFORE_PAYMENT","RESPONSE_LOST").contains(scenario)) throw bad("退款场景不合法");
        return tx.execute(s -> {
            var order=jdbc.queryForList("SELECT o.status,o.total_amount,w.phase FROM orders o JOIN checkout_workflow w ON w.order_id=o.order_id WHERE o.order_id=? AND o.account_id=? FOR UPDATE",orderId,account);
            if(order.isEmpty()) throw missing("订单不存在");
            var aliases=jdbc.queryForList("SELECT order_id FROM checkout_refund_request WHERE account_id=? AND request_id=?",account,input.requestId());
            if(!aliases.isEmpty() && ((Number)aliases.getFirst().get("order_id")).longValue()!=orderId) throw conflict("退款请求键已用于其他订单");
            var existing=find(account,orderId);
            if(existing!=null) {
                if(!existing.reason().equals(reason)) throw conflict("原退款原因不能覆盖");
                remember(account,input.requestId(),orderId,existing.refundId());return existing;
            }
            if(!"PAID".equals(order.getFirst().get("status")) || !"DONE".equals(order.getFirst().get("phase"))) throw conflict("订单需已支付且资源确认完成才能申请整单退款");
            if(jdbc.queryForObject("SELECT COUNT(*) FROM checkout_payment_fact WHERE order_id=?",Integer.class,orderId)!=1) throw conflict("历史支付缺少来源记录，需人工核对");
            String refundId=UUID.randomUUID().toString();
            jdbc.update("INSERT INTO checkout_refund(refund_id,order_id,account_id,amount,reason,scenario,status,phase,next_attempt_at,created_at) VALUES (?,?,?,?,?,?,'REFUNDING','PAYMENT',?,?)",
                    refundId,orderId,account,order.getFirst().get("total_amount"),reason,scenario,now(),now());
            remember(account,input.requestId(),orderId,refundId);
            jdbc.update("UPDATE orders SET status='REFUNDING',updated_at=? WHERE order_id=?",now(),orderId);
            return find(account,orderId);
        });
    }
    private void remember(String account,String key,long orderId,String refundId) {
        if(jdbc.queryForObject("SELECT COUNT(*) FROM checkout_refund_request WHERE account_id=? AND request_id=?",Integer.class,account,key)==0)
            jdbc.update("INSERT INTO checkout_refund_request(account_id,request_id,order_id,refund_id) VALUES (?,?,?,?)",account,key,orderId,refundId);
    }
    public View get(String account,long orderId) {id(account);var value=find(account,orderId);if(value==null) throw missing("退款单不存在");return value;}
    private View find(String account,long orderId) {
        var found=jdbc.query("SELECT * FROM checkout_refund WHERE account_id=? AND order_id=?",(r,n)->new View(r.getString("refund_id"),orderId,r.getLong("amount"),r.getString("status"),r.getString("phase"),r.getString("reason"),r.getString("last_error")),account,orderId);
        return found.isEmpty() ? null : found.getFirst();
    }
    public Quote quote(long orderId) {
        var found=jdbc.query("SELECT o.account_id,o.status,p.* FROM orders o JOIN checkout_payment_fact p ON p.order_id=o.order_id WHERE o.order_id=?",
                (r,n)->new Quote(orderId,r.getString("account_id"),r.getLong("amount"),r.getString("provider"),r.getBoolean("mock"),r.getString("status")),orderId);
        if(!found.isEmpty()) return found.getFirst();
        var orders=jdbc.query("SELECT account_id,total_amount,status FROM orders WHERE order_id=?",(r,n)->new Quote(orderId,r.getString("account_id"),r.getLong("total_amount"),"unknown",false,r.getString("status")),orderId);
        if(orders.isEmpty()) throw missing("订单不存在");return orders.getFirst();
    }
    public void processPending() {
        var ids=jdbc.queryForList("SELECT refund_id FROM checkout_refund WHERE status='REFUNDING' AND next_attempt_at<=? ORDER BY next_attempt_at LIMIT 50",String.class,now());
        for(String id:ids) process(id);
    }
    public void process(String id) {
        String token=leases.acquire("refund",id);if(token==null) return;
        try {
            for(int step=0;step<4;step++) {
                var row=jdbc.queryForMap("SELECT r.*,w.coupon_id,i.sku_id,i.quantity,p.activity_id FROM checkout_refund r JOIN checkout_workflow w ON w.order_id=r.order_id JOIN order_items i ON i.order_id=r.order_id LEFT JOIN checkout_stock_scope p ON p.order_id=r.order_id WHERE r.refund_id=?",id);
                if(!"REFUNDING".equals(row.get("status")) || !Boolean.TRUE.equals(tx.execute(s->leases.owns("refund",id,token)))) return;
                String phase=(String)row.get("phase");long order=((Number)row.get("order_id")).longValue();
                try {
                    String next;
                    switch(phase) {
                        case "PAYMENT","PAYMENT_RETRY" -> {
                            var result=payment.refund(id,order,((Number)row.get("amount")).longValue(),(String)row.get("scenario"),phase.equals("PAYMENT_RETRY"));
                            if("FAILED".equals(result.status())) {review(id,token,"退款渠道明确拒绝",phase);return;}
                            if(!"SUCCEEDED".equals(result.status())) throw new IllegalStateException("退款渠道仍在处理");next="STOCK";
                        }
                        case "STOCK" -> {
                            String sku=(String)row.get("sku_id");int qty=((Number)row.get("quantity")).intValue();
                            if(row.get("activity_id")!=null) inventory.activity("REFUND",(String)row.get("activity_id"),order,sku,qty);
                            else inventory.refund("checkout:"+order+":refund",order,sku,qty);
                            next=row.get("coupon_id")==null ? "DONE" : "COUPON";
                        }
                        case "COUPON" -> {promotion.refund(order,(String)row.get("coupon_id"));next="DONE";}
                        default -> throw new IllegalStateException("未知退款阶段");
                    }
                    tx.executeWithoutResult(s -> {
                        if(!leases.owns("refund",id,token)) return;
                        int changed=jdbc.update("UPDATE checkout_refund SET phase=?,status=?,attempts=0,last_error=NULL,next_attempt_at=? WHERE refund_id=? AND status='REFUNDING' AND phase=?",
                                next,next.equals("DONE") ? "REFUNDED" : "REFUNDING",now(),id,phase);
                        if(changed==1 && next.equals("DONE")) {
                            jdbc.update("UPDATE orders SET status='REFUNDED',updated_at=? WHERE order_id=?",now(),order);
                            OrderTradeEvents.append(jdbc,order,"REFUNDED",now());
                        }
                    });
                } catch(RuntimeException failure) {
                    tx.executeWithoutResult(s -> {
                        if(!leases.owns("refund",id,token)) return;
                        int attempts=((Number)row.get("attempts")).intValue()+1;
                        boolean permanent=failure instanceof HttpClientErrorException http && http.getStatusCode().is4xxClientError() && !List.of(408,429).contains(http.getStatusCode().value());
                        jdbc.update("UPDATE checkout_refund SET attempts=?,status=?,next_attempt_at=?,last_error=? WHERE refund_id=? AND phase=? AND status='REFUNDING'",
                                attempts,permanent || attempts>=20 ? "REVIEW_REQUIRED" : "REFUNDING",now().plusSeconds(Math.min(60,5L*attempts)),"退款阶段未确认："+failure.getClass().getSimpleName(),id,phase);
                    });return;
                }
            }
        } finally {leases.release("refund",id,token);}
    }
    private void review(String id,String token,String message,String phase) {
        tx.executeWithoutResult(s->{if(leases.owns("refund",id,token)) jdbc.update("UPDATE checkout_refund SET status='REVIEW_REQUIRED',last_error=? WHERE refund_id=? AND phase=?",message,id,phase);});
    }
    public List<Map<String,Object>> tasks() {return jdbc.queryForList("SELECT refund_id,order_id,status,phase,amount,attempts,next_attempt_at,created_at,last_error FROM checkout_refund WHERE status<>'REFUNDED' ORDER BY created_at LIMIT 100");}
    public void retry(String id,String actor,String reason) {
        id(id);id(actor);reason(reason);
        tx.executeWithoutResult(s->{
            int changed=jdbc.update("UPDATE checkout_refund SET status='REFUNDING',phase=CASE WHEN phase IN ('PAYMENT','PAYMENT_RETRY') THEN 'PAYMENT_RETRY' ELSE phase END,attempts=0,last_error=NULL,next_attempt_at=? WHERE refund_id=? AND status='REVIEW_REQUIRED'",now(),id);
            if(changed!=1) throw conflict("仅可恢复待核对退款");
            jdbc.update("INSERT INTO commerce_operation_audit(component,resource_id,operator_id,action,reason,created_at) VALUES ('refund',?,?,'RETRY',?,?)",id,actor,reason,now());
        });
    }
    private static LocalDateTime now() {return LocalDateTime.now(Clock.systemUTC());}
}
