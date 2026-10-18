package com.sinrotic.rs.inventory.service;

import com.sinrotic.rs.common.commerce.*;
import org.springframework.stereotype.Service;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;
import java.time.*;
import java.util.*;
import static com.sinrotic.rs.common.commerce.CommerceInput.*;

@Service
public class InventoryManagement {
    public record Adjustment(String requestId,String skuId,String itemId,String type,int quantity,Long expectedVersion,String reason) {}
    private final JdbcTemplate jdbc;private final TransactionTemplate tx;
    public InventoryManagement(JdbcTemplate jdbc,PlatformTransactionManager manager) {this.jdbc=jdbc;tx=new TransactionTemplate(manager);}
    public Map<String,Object> adjust(Adjustment input,String actor) {
        if(input==null) throw bad("库存变更不能为空");id(input.requestId());id(input.skuId());id(input.itemId());id(actor);reason(input.reason());
        if(input.type()==null || !List.of("RECEIPT","STOCKTAKE").contains(input.type()) || input.quantity()<0 || input.type().equals("RECEIPT") && input.quantity()==0
                || input.type().equals("STOCKTAKE") && input.expectedVersion()==null) throw bad("入库或盘点参数不合法");
        return tx.execute(s -> {
            var baseline=jdbc.queryForList("SELECT opening_total FROM inventory_stock_baseline WHERE sku_id=?",input.skuId());
            if(baseline.isEmpty() && jdbc.queryForObject("SELECT COUNT(*) FROM sku_stock WHERE sku_id=?",Integer.class,input.skuId())>0) throw conflict("期初库存基线缺失，先核对迁移");
            jdbc.update("INSERT INTO inventory_stock_baseline(sku_id,opening_total) VALUES (?,0) ON DUPLICATE KEY UPDATE sku_id=sku_id",input.skuId());
            jdbc.queryForMap("SELECT * FROM inventory_stock_baseline WHERE sku_id=? FOR UPDATE",input.skuId());
            var stocks=jdbc.queryForList("SELECT * FROM sku_stock WHERE sku_id=? FOR UPDATE",input.skuId());
            if(stocks.isEmpty()) {
                if(!input.type().equals("RECEIPT")) throw missing("盘点 SKU 不存在");
                jdbc.update("INSERT INTO sku_stock(sku_id,item_id,available_stock) VALUES (?,?,0)",input.skuId(),input.itemId());
            }
            var stock=jdbc.queryForMap("SELECT * FROM sku_stock WHERE sku_id=? FOR UPDATE",input.skuId());
            if(!input.itemId().equals(stock.get("item_id"))) throw conflict("SKU 不能更换所属商品");
            var previous=jdbc.queryForList("SELECT * FROM inventory_adjustment WHERE request_id=?",input.requestId());
            if(!previous.isEmpty()) {
                var row=previous.getFirst();
                if(!input.skuId().equals(row.get("sku_id")) || !input.type().equals(row.get("movement_type"))
                        || input.quantity()!=number(row,"input_quantity") || !Objects.equals(input.expectedVersion(),row.get("expected_version"))
                        || !input.reason().equals(row.get("reason"))) throw conflict("库存请求键参数冲突");return stock;
            }
            long available=number(stock,"available_stock"),locked=number(stock,"locked_stock");
            if(input.type().equals("STOCKTAKE") && input.expectedVersion()!=number(stock,"version")) throw conflict("库存已变化，请重新读取后盘点");
            long target=input.type().equals("RECEIPT") ? available+input.quantity() : input.quantity()-locked;
            if(target<0 || target>Integer.MAX_VALUE) throw conflict("盘点实存不能低于已预留量，库存也不能溢出");
            long delta=target-available;
            jdbc.update("UPDATE sku_stock SET available_stock=?,version=version+1 WHERE sku_id=?",target,input.skuId());
            jdbc.update("INSERT INTO inventory_adjustment(request_id,sku_id,movement_type,input_quantity,expected_version,delta_quantity,operator_id,reason,created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                    input.requestId(),input.skuId(),input.type(),input.quantity(),input.expectedVersion(),delta,actor,input.reason(),now());
            audit(input.skuId(),actor,input.type(),input.reason());
            return jdbc.queryForMap("SELECT * FROM sku_stock WHERE sku_id=?",input.skuId());
        });
    }
    public Page<Map<String,Object>> stocks(String afterId,int limit) {
        limit(limit);if(afterId!=null) id(afterId);
        var rows=jdbc.queryForList("SELECT * FROM sku_stock WHERE sku_id>? ORDER BY sku_id LIMIT ?",afterId==null ? "" : afterId,limit+1);
        boolean more=rows.size()>limit;var items=more ? rows.subList(0,limit) : rows;
        return new Page<>(items,more ? (String)items.getLast().get("sku_id") : null);
    }
    public List<Map<String,Object>> ledger(String skuId) {id(skuId);return jdbc.queryForList("SELECT * FROM inventory_adjustment WHERE sku_id=? ORDER BY created_at DESC LIMIT 100",skuId);}
    public List<Map<String,Object>> reconcile(String afterId,int limit) {
        var page=stocks(afterId,limit);var result=new ArrayList<Map<String,Object>>();
        for(var row:page.items()) result.add(check((String)row.get("sku_id")));
        return result;
    }
    public void tick() {
        String cursor=jdbc.queryForList("SELECT after_sku_id FROM inventory_reconciliation_cursor WHERE id=1",String.class).stream().findFirst().orElse("");
        var page=stocks(cursor,100);for(var row:page.items()) check((String)row.get("sku_id"));
        String next=page.nextCursor()==null ? "" : page.nextCursor();
        jdbc.update("INSERT INTO inventory_reconciliation_cursor(id,after_sku_id) VALUES (1,?) ON DUPLICATE KEY UPDATE after_sku_id=VALUES(after_sku_id)",next);
    }
    public Map<String,Object> check(String sku) {
        id(sku);
        return tx.execute(s -> {
            var stock=jdbc.queryForMap("SELECT * FROM sku_stock WHERE sku_id=? FOR UPDATE",sku);
            var baselines=jdbc.queryForList("SELECT opening_total FROM inventory_stock_baseline WHERE sku_id=?",Long.class,sku);
            Long expected=baselines.isEmpty() ? null : baselines.getFirst()+sum("SELECT COALESCE(SUM(delta_quantity),0) FROM inventory_adjustment WHERE sku_id=?",sku);
            long actual=number(stock,"available_stock")+number(stock,"locked_stock")+number(stock,"sold_stock");
            long normalLocks=sum("""
                    SELECT COALESCE(SUM(l.quantity),0) FROM stock_logs l WHERE l.sku_id=? AND l.type='LOCK'
                    AND NOT EXISTS(SELECT 1 FROM stock_logs t WHERE t.order_id=l.order_id AND t.sku_id=l.sku_id AND t.type IN ('CONFIRM','RELEASE','CANCEL'))
                    """,sku);
            long poolLocks=sum("SELECT COALESCE(SUM(available_quantity+reserved_quantity),0) FROM inventory_activity_pool WHERE sku_id=?",sku);
            long normalSold=sum("SELECT COALESCE(SUM(CASE WHEN type='CONFIRM' THEN quantity WHEN type='REFUND' THEN -quantity ELSE 0 END),0) FROM stock_logs WHERE sku_id=?",sku);
            long poolSold=sum("SELECT COALESCE(SUM(sold_quantity),0) FROM inventory_activity_pool WHERE sku_id=?",sku);
            long locked=number(stock,"locked_stock"),sold=number(stock,"sold_stock");
            boolean healthy=expected!=null && expected==actual && locked==normalLocks+poolLocks && sold==normalSold+poolSold;
            if(!healthy) {
                var open=jdbc.queryForList("SELECT case_id FROM inventory_reconciliation WHERE sku_id=? AND status IN ('OPEN','ACKNOWLEDGED')",String.class,sku);
                String reason=expected==null ? "期初基线缺失" : "汇总、活动池或订单流水数量不一致";
                if(open.isEmpty()) jdbc.update("INSERT INTO inventory_reconciliation(case_id,sku_id,status,expected_total,actual_total,expected_locked,actual_locked,expected_sold,actual_sold,reason,created_at) VALUES (?,?,'OPEN',?,?,?,?,?,?,?,?)",
                        UUID.randomUUID().toString(),sku,expected,actual,normalLocks+poolLocks,locked,normalSold+poolSold,sold,reason,now());
                else jdbc.update("UPDATE inventory_reconciliation SET expected_total=?,actual_total=?,expected_locked=?,actual_locked=?,expected_sold=?,actual_sold=?,reason=? WHERE case_id=?",
                        expected,actual,normalLocks+poolLocks,locked,normalSold+poolSold,sold,reason,open.getFirst());
            } else jdbc.update("UPDATE inventory_reconciliation SET status='RESOLVED',disposition='后续复检一致' WHERE sku_id=? AND status IN ('OPEN','ACKNOWLEDGED')",sku);
            return Map.of("skuId",sku,"healthy",healthy,"actualTotal",actual,"expectedTotal",expected==null ? -1 : expected,"expectedLocked",normalLocks+poolLocks,"expectedSold",normalSold+poolSold);
        });
    }
    public List<Map<String,Object>> cases() {return jdbc.queryForList("SELECT * FROM inventory_reconciliation WHERE status<>'RESOLVED' ORDER BY created_at LIMIT 100");}
    public void acknowledge(String caseId,String actor,String reason) {
        id(caseId);id(actor);reason(reason);
        tx.executeWithoutResult(s->{
            if(jdbc.update("UPDATE inventory_reconciliation SET status='ACKNOWLEDGED',operator_id=?,disposition=? WHERE case_id=? AND status IN ('OPEN','ACKNOWLEDGED')",actor,reason,caseId)!=1) throw conflict("差异已解决或不存在");
            audit(caseId,actor,"ACKNOWLEDGE",reason);
        });
    }
    private void audit(String resource,String actor,String action,String reason) {jdbc.update("INSERT INTO commerce_operation_audit(component,resource_id,operator_id,action,reason,created_at) VALUES ('inventory',?,?,?,?,?)",resource,actor,action,reason,now());}
    private long sum(String sql,String sku) {return Objects.requireNonNull(jdbc.queryForObject(sql,Long.class,sku));}
    private static long number(Map<String,Object> row,String key) {return ((Number)row.get(key)).longValue();}
    private static LocalDateTime now() {return LocalDateTime.now(Clock.systemUTC());}
}
