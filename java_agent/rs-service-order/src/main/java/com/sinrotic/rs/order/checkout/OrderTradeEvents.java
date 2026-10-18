package com.sinrotic.rs.order.checkout;

import com.sinrotic.rs.common.commerce.TradeEvent;
import org.springframework.jdbc.core.JdbcTemplate;
import tools.jackson.databind.json.JsonMapper;
import java.time.LocalDateTime;

/** 必须在订单事实事务内调用，交付失败不撤销已经提交的支付/退款事实。 */
final class OrderTradeEvents {
    static void append(JdbcTemplate jdbc,long orderId,String type,LocalDateTime now) {
        String id="order:"+orderId+":"+type;
        if(jdbc.queryForObject("SELECT COUNT(*) FROM commerce_order_event WHERE event_id=?",Integer.class,id)>0) return;
        var rows=jdbc.query("""
                SELECT o.*,i.item_id,i.quantity,p.provider,p.mock,s.activity_id FROM orders o
                JOIN order_items i ON i.order_id=o.order_id JOIN checkout_payment_fact p ON p.order_id=o.order_id
                LEFT JOIN checkout_stock_scope s ON s.order_id=o.order_id WHERE o.order_id=?
                """,(r,n)->new TradeEvent(id,orderId,type.equals("PAID") ? 1 : 2,type,r.getString("account_id"),r.getString("profile_user_id"),
                r.getString("session_id"),r.getString("recommend_request_id"),r.getString("item_id"),r.getInt("quantity"),r.getLong("total_amount"),r.getString("provider"),r.getBoolean("mock"),now),orderId);
        if(rows.isEmpty()) throw new IllegalStateException("缺少已验证的支付事实");
        jdbc.update("INSERT INTO commerce_order_event(event_id,order_id,event_type,payload,created_at) VALUES (?,?,?,?,?)",id,orderId,type,new JsonMapper().writeValueAsString(rows.getFirst()),now);
        jdbc.update("INSERT INTO commerce_event_delivery(event_id,target,next_attempt_at) VALUES (?,'recommend',?)",id,now);
        if(jdbc.queryForObject("SELECT COUNT(*) FROM checkout_stock_scope WHERE order_id=?",Integer.class,orderId)>0)
            jdbc.update("INSERT INTO commerce_event_delivery(event_id,target,next_attempt_at) VALUES (?,'seckill',?)",id,now);
    }
    private OrderTradeEvents() {}
}
