package com.sinrotic.rs.inventory.service;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;
import org.springframework.http.HttpStatus;
import org.springframework.web.server.ResponseStatusException;
import java.util.Map;

@Service
public class ActivityStockService {
    private final JdbcTemplate jdbc;
    private final TransactionTemplate tx;
    public record Allocation(String activityId,String skuId,int quantity) {}
    public record Movement(String activityId,long orderId,String skuId,int quantity) {}
    public ActivityStockService(JdbcTemplate jdbc,PlatformTransactionManager manager) {
        this.jdbc=jdbc;this.tx=new TransactionTemplate(manager);
    }
    public void allocate(Allocation input) {
        if(input==null) throw bad("划拨参数不能为空");
        text(input.activityId());text(input.skuId());quantity(input.quantity());
        tx.executeWithoutResult(s -> {
            lockSku(input.skuId());
            var rows=jdbc.queryForList("SELECT * FROM inventory_activity_pool WHERE activity_id=? FOR UPDATE",input.activityId());
            if(!rows.isEmpty()) {
                var pool=rows.getFirst();
                if(!input.skuId().equals(pool.get("sku_id")) || number(pool,"total_quantity")!=input.quantity())
                    throw conflict("活动划拨参数冲突");
                return;
            }
            int changed=jdbc.update("""
                    UPDATE sku_stock SET available_stock=available_stock-?,locked_stock=locked_stock+?,version=version+1
                    WHERE sku_id=? AND available_stock>=?
                    """,input.quantity(),input.quantity(),input.skuId(),input.quantity());
            if(changed!=1) throw conflict("普通可售库存不足以划拨活动库存");
            jdbc.update("INSERT INTO inventory_activity_pool(activity_id,sku_id,total_quantity,available_quantity) VALUES (?,?,?,?)",
                    input.activityId(),input.skuId(),input.quantity(),input.quantity());
        });
    }
    public void close(String activityId) {
        text(activityId);
        // 先读不可变 SKU，再按统一 SKU -> 活动池顺序获取锁。
        var rows=jdbc.queryForList("SELECT sku_id FROM inventory_activity_pool WHERE activity_id=?",activityId);
        if(rows.isEmpty()) throw missing("活动库存不存在");
        String sku=(String)rows.getFirst().get("sku_id");
        tx.executeWithoutResult(s -> {
            lockSku(sku);
            var pool=pool(activityId);
            if("CLOSED".equals(pool.get("status"))) return;
            if(number(pool,"reserved_quantity")!=0) throw conflict("活动仍有订单预留，不能归还库存");
            int available=number(pool,"available_quantity");
            if(jdbc.update("UPDATE sku_stock SET available_stock=available_stock+?,locked_stock=locked_stock-?,version=version+1 WHERE sku_id=? AND locked_stock>=?",
                    available,available,sku,available)!=1) throw conflict("活动库存汇总不一致，需核对");
            jdbc.update("UPDATE inventory_activity_pool SET status='CLOSED',available_quantity=0,returned_quantity=returned_quantity+? WHERE activity_id=?",available,activityId);
        });
    }
    public void move(String action,Movement input) {
        if(input==null || input.orderId()<=0) throw bad("订单参数不合法");
        text(input.activityId());text(input.skuId());quantity(input.quantity());
        if(!java.util.List.of("LOCK","CONFIRM","RELEASE","CANCEL","REFUND").contains(action)) throw bad("库存操作不合法");
        tx.executeWithoutResult(s -> {
            if("CONFIRM".equals(action) || "REFUND".equals(action)) lockSku(input.skuId());
            var pool=pool(input.activityId());
            if(!input.skuId().equals(pool.get("sku_id"))) throw conflict("SKU 与活动库存不匹配");
            var rows=jdbc.queryForList("SELECT * FROM inventory_activity_reservation WHERE order_id=? FOR UPDATE",input.orderId());
            var reservation=rows.isEmpty() ? null : rows.getFirst();
            if(reservation!=null && (!input.activityId().equals(reservation.get("activity_id"))
                    || !input.skuId().equals(reservation.get("sku_id")) || number(reservation,"quantity")!=input.quantity()))
                throw conflict("订单库存预留参数冲突");
            String state=reservation==null ? null : (String)reservation.get("status");
            String target=switch(action) {case "LOCK" -> "LOCKED";case "CONFIRM" -> "CONFIRMED";case "RELEASE" -> "RELEASED";case "REFUND" -> "REFUNDED";default -> "CANCELED";};
            if(target.equals(state)) return;
            if("REFUND".equals(action)) {
                if(!"CONFIRMED".equals(state)) throw conflict("仅可退回已确认售出的活动库存");
                if(jdbc.update("UPDATE sku_stock SET sold_stock=sold_stock-?,available_stock=available_stock+?,version=version+1 WHERE sku_id=? AND sold_stock>=?",
                        input.quantity(),input.quantity(),input.skuId(),input.quantity())!=1) throw conflict("已售库存不足，需核对");
                // 售后不重新开放秒杀名额，实物一律返普通库存，关闭的活动池也能退款。
                jdbc.update("UPDATE inventory_activity_pool SET sold_quantity=sold_quantity-?,returned_quantity=returned_quantity+? WHERE activity_id=?",input.quantity(),input.quantity(),input.activityId());
            } else if("LOCK".equals(action)) {
                if(state!=null || !"OPEN".equals(pool.get("status"))) throw conflict("活动预留已结束");
                if(jdbc.update("UPDATE inventory_activity_pool SET available_quantity=available_quantity-?,reserved_quantity=reserved_quantity+? WHERE activity_id=? AND available_quantity>=?",
                        input.quantity(),input.quantity(),input.activityId(),input.quantity())!=1) throw conflict("活动库存不足");
            } else if("CANCEL".equals(action) && state==null) {
                // 取消先到时持久化墓碑；迟到 LOCK 不得重新占用库存。
            } else if("CANCEL".equals(action) && "RELEASED".equals(state)) {
                target="CANCELED";
            } else {
                if(!"LOCKED".equals(state)) throw conflict("预留状态不允许此操作");
                if("CONFIRM".equals(action)) {
                    if(jdbc.update("UPDATE sku_stock SET locked_stock=locked_stock-?,sold_stock=sold_stock+?,version=version+1 WHERE sku_id=? AND locked_stock>=?",
                            input.quantity(),input.quantity(),input.skuId(),input.quantity())!=1) throw conflict("活动库存汇总不一致");
                    jdbc.update("UPDATE inventory_activity_pool SET reserved_quantity=reserved_quantity-?,sold_quantity=sold_quantity+? WHERE activity_id=?",input.quantity(),input.quantity(),input.activityId());
                } else {
                    jdbc.update("UPDATE inventory_activity_pool SET reserved_quantity=reserved_quantity-?,available_quantity=available_quantity+? WHERE activity_id=?",input.quantity(),input.quantity(),input.activityId());
                }
            }
            if(reservation==null) jdbc.update("INSERT INTO inventory_activity_reservation(order_id,activity_id,sku_id,quantity,status) VALUES (?,?,?,?,?)",
                    input.orderId(),input.activityId(),input.skuId(),input.quantity(),target);
            else jdbc.update("UPDATE inventory_activity_reservation SET status=? WHERE order_id=?",target,input.orderId());
        });
    }
    public Map<String,Object> view(String activityId) {
        text(activityId);
        var rows=jdbc.queryForList("SELECT * FROM inventory_activity_pool WHERE activity_id=?",activityId);
        if(rows.isEmpty()) throw missing("活动库存不存在");
        return rows.getFirst();
    }
    private Map<String,Object> pool(String id) {
        var rows=jdbc.queryForList("SELECT * FROM inventory_activity_pool WHERE activity_id=? FOR UPDATE",id);
        if(rows.isEmpty()) throw missing("活动库存不存在");
        return rows.getFirst();
    }
    private void lockSku(String sku) {
        if(jdbc.queryForList("SELECT sku_id FROM sku_stock WHERE sku_id=? FOR UPDATE",sku).isEmpty()) throw missing("SKU 库存不存在");
    }
    private static int number(Map<String,Object> row,String key) {return ((Number)row.get(key)).intValue();}
    private static void text(String value) { if(value==null || value.isBlank() || value.length()>64 || !value.equals(value.trim())) throw bad("标识不合法"); }
    private static void quantity(int value) {if(value<=0) throw bad("数量必须大于零");}
    private static ResponseStatusException bad(String text) {return new ResponseStatusException(HttpStatus.BAD_REQUEST,text);}
    private static ResponseStatusException conflict(String text) {return new ResponseStatusException(HttpStatus.CONFLICT,text);}
    private static ResponseStatusException missing(String text) {return new ResponseStatusException(HttpStatus.NOT_FOUND,text);}
}
