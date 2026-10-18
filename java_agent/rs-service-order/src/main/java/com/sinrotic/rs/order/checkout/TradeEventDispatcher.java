package com.sinrotic.rs.order.checkout;

import com.sinrotic.rs.common.commerce.*;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;
import org.springframework.web.client.RestClient;
import java.time.*;
import java.util.*;

@Service
public class TradeEventDispatcher {
    private final JdbcTemplate jdbc;private final TransactionTemplate tx;private final WorkerLeaseStore leases;
    private final RestClient client;private final Map<String,String> urls;private final String token;
    public TradeEventDispatcher(JdbcTemplate jdbc,PlatformTransactionManager manager,RestClient.Builder builder,
            @Value("${rs.recommend.base-url:http://localhost:18103}") String recommendUrl,
            @Value("${rs.seckill.base-url:http://localhost:8094}") String seckillUrl,@Value("${rs.commerce.service-token:}") String token) {
        this.jdbc=jdbc;tx=new TransactionTemplate(manager);leases=new WorkerLeaseStore(jdbc);this.token=token;
        var factory=new org.springframework.http.client.SimpleClientHttpRequestFactory();factory.setConnectTimeout(2000);factory.setReadTimeout(3000);
        client=builder.requestFactory(factory).build();urls=Map.of("recommend",recommendUrl+"/internal/recommend/commerce-events","seckill",seckillUrl+"/internal/seckill/order-events");
    }
    public void dispatch() {
        for(var row:jdbc.queryForList("SELECT d.*,e.payload FROM commerce_event_delivery d JOIN commerce_order_event e ON e.event_id=d.event_id WHERE d.status='PENDING' AND d.next_attempt_at<=? ORDER BY d.next_attempt_at LIMIT 30",now())) {
            String id=(String)row.get("event_id"),target=(String)row.get("target"),key=id+":"+target;
            String token=leases.acquire("trade-event",key);if(token==null) continue;
            try {
                // 另一个实例可能已交付或退避；取得租约后重新读取当前状态。
                var current=jdbc.queryForList("SELECT * FROM commerce_event_delivery WHERE event_id=? AND target=? AND status='PENDING' AND next_attempt_at<=?",id,target,now());
                if(current.isEmpty()) continue;
                client.post().uri(urls.get(target)).header("Authorization","Bearer "+this.token).header("Content-Type","application/json")
                        .body((String)row.get("payload")).retrieve().toBodilessEntity();
                tx.executeWithoutResult(s->{if(leases.owns("trade-event",key,token)) jdbc.update("UPDATE commerce_event_delivery SET status='DONE',last_error=NULL WHERE event_id=? AND target=?",id,target);});
            } catch(RuntimeException failure) {
                tx.executeWithoutResult(s->{if(leases.owns("trade-event",key,token)) {
                    int attempts=jdbc.queryForObject("SELECT attempts FROM commerce_event_delivery WHERE event_id=? AND target=? FOR UPDATE",Integer.class,id,target)+1;
                    jdbc.update("UPDATE commerce_event_delivery SET status=?,attempts=?,next_attempt_at=?,last_error=? WHERE event_id=? AND target=? AND status='PENDING'",
                            attempts>=20 ? "REVIEW_REQUIRED" : "PENDING",attempts,now().plusSeconds(Math.min(60,attempts*5)),failure.getClass().getSimpleName(),id,target);
                }});
            } finally {leases.release("trade-event",key,token);}
        }
    }
    public List<Map<String,Object>> tasks() {return jdbc.queryForList("SELECT d.*,e.created_at FROM commerce_event_delivery d JOIN commerce_order_event e ON e.event_id=d.event_id WHERE d.status<>'DONE' ORDER BY e.created_at LIMIT 100");}
    public void retry(String id,String target,String actor,String reason) {
        CommerceInput.id(id);CommerceInput.id(actor);CommerceInput.reason(reason);
        tx.executeWithoutResult(s->{
            if(jdbc.update("UPDATE commerce_event_delivery SET status='PENDING',attempts=0,next_attempt_at=?,last_error=NULL WHERE event_id=? AND target=? AND status='REVIEW_REQUIRED'",now(),id,target)!=1) throw CommerceInput.conflict("仅可恢复待核对的交付");
            jdbc.update("INSERT INTO commerce_operation_audit(component,resource_id,operator_id,action,reason,created_at) VALUES ('trade-event',?,?,'RETRY',?,?)",id,actor,reason,now());
        });
    }
    private static LocalDateTime now() {return LocalDateTime.now(Clock.systemUTC());}
}
