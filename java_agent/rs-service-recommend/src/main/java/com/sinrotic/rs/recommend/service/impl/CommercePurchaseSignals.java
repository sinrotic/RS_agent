package com.sinrotic.rs.recommend.service.impl;

import com.sinrotic.rs.common.commerce.*;
import org.springframework.stereotype.Service;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import java.time.*;
import java.util.*;
import java.security.MessageDigest;
import java.nio.charset.StandardCharsets;
import tools.jackson.databind.json.JsonMapper;

/** 购买事实独立于显式 like/dislike；退款只撤销原购买信号，不制造负反馈。 */
@Service
@ConditionalOnProperty(name="rs.recommend.commerce.enabled",havingValue="true")
public class CommercePurchaseSignals {
    private final JdbcTemplate jdbc;private final TransactionTemplate tx;
    public CommercePurchaseSignals(JdbcTemplate jdbc,PlatformTransactionManager manager) {this(jdbc,new TransactionTemplate(manager));}
    @org.springframework.beans.factory.annotation.Autowired
    public CommercePurchaseSignals(JdbcTemplate jdbc,TransactionTemplate tx) {this.jdbc=jdbc;this.tx=tx;}
    public void accept(TradeEvent event) {
        if(event==null) throw CommerceInput.bad("交易事件不能为空");event.validate();
        String fingerprint;
        try {fingerprint=HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(new JsonMapper().writeValueAsString(event).getBytes(StandardCharsets.UTF_8)));}
        catch(java.security.NoSuchAlgorithmException impossible) {throw new IllegalStateException(impossible);}
        tx.executeWithoutResult(s -> {
            // upsert 只建立互斥行；后续当前读校验来源，乱序退款先到也不会被迟到支付激活。
            jdbc.update("""
                    INSERT INTO recommendation_purchase_signal(order_id,account_id,profile_user_id,item_id,quantity,amount,provider,mock,event_version,active,created_at)
                    VALUES (?,?,?,?,?,?,?,?,0,FALSE,?) ON DUPLICATE KEY UPDATE order_id=order_id
                    """,event.orderId(),event.accountId(),event.profileUserId(),event.itemId(),event.quantity(),event.amount(),event.provider(),event.mock(),event.occurredAt());
            var row=jdbc.queryForMap("SELECT * FROM recommendation_purchase_signal WHERE order_id=? FOR UPDATE",event.orderId());
            if(!event.accountId().equals(row.get("account_id")) || !Objects.equals(event.profileUserId(),row.get("profile_user_id"))
                    || !event.itemId().equals(row.get("item_id")) || event.amount()!=((Number)row.get("amount")).longValue()
                    || event.quantity()!=((Number)row.get("quantity")).intValue() || !event.provider().equals(row.get("provider"))
                    || event.mock()!=jdbc.queryForObject("SELECT mock FROM recommendation_purchase_signal WHERE order_id=?",Boolean.class,event.orderId())) throw CommerceInput.conflict("交易事件与原订单来源冲突");
            var stored=jdbc.queryForList("SELECT fingerprint FROM recommendation_trade_event WHERE event_id=?",event.eventId());
            if(!stored.isEmpty()) {
                if(!fingerprint.equals(stored.getFirst().get("fingerprint"))) throw CommerceInput.conflict("同一事件标识参数冲突");return;
            }
            jdbc.update("INSERT INTO recommendation_trade_event(event_id,order_id,event_version,fingerprint,mock,created_at) VALUES (?,?,?,?,?,?)",event.eventId(),event.orderId(),event.version(),fingerprint,event.mock(),now());
            if(event.version()>((Number)row.get("event_version")).intValue())
                jdbc.update("UPDATE recommendation_purchase_signal SET event_version=?,active=? WHERE order_id=?",event.version(),!event.mock() && event.profileUserId()!=null && event.type().equals("PAID"),event.orderId());
        });
    }
    public Map<String,Integer> load(String profile,List<String> itemIds) {
        if(profile==null || profile.isBlank() || itemIds.isEmpty()) return Map.of();
        var ids=itemIds.stream().distinct().limit(500).toList();var args=new ArrayList<Object>();args.add(profile);args.addAll(ids);
        String placeholders=String.join(",",Collections.nCopies(ids.size(),"?"));
        var rows=jdbc.queryForList("SELECT item_id,COUNT(*) AS purchases FROM recommendation_purchase_signal WHERE profile_user_id=? AND active=TRUE AND mock=FALSE AND created_at>=? AND item_id IN ("+placeholders+") GROUP BY item_id",arguments(args));
        var result=new HashMap<String,Integer>();for(var row:rows) result.put((String)row.get("item_id"),((Number)row.get("purchases")).intValue());return result;
    }
    private static Object[] arguments(List<Object> args) {var result=new ArrayList<>(args);result.add(1,now().minusDays(180));return result.toArray();}
    private static LocalDateTime now() {return LocalDateTime.now(Clock.systemUTC());}
}
