package com.sinrotic.rs.inventory.service;

import com.sinrotic.rs.common.commerce.CommerceInput;
import com.sinrotic.rs.inventory.domain.dto.InventoryReleaseRequestDTO;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;

@Service
public class RefundStockService {
    private final JdbcTemplate jdbc;private final TransactionTemplate tx;
    public RefundStockService(JdbcTemplate jdbc,PlatformTransactionManager manager) {this.jdbc=jdbc;tx=new TransactionTemplate(manager);}
    public void refund(InventoryReleaseRequestDTO input) {
        if(input==null || input.orderId()==null || input.orderId()<=0 || input.quantity()==null || input.quantity()<=0) throw CommerceInput.bad("退库参数不合法");
        CommerceInput.id(input.requestId());CommerceInput.id(input.skuId());
        tx.executeWithoutResult(s -> {
            if(jdbc.queryForList("SELECT sku_id FROM sku_stock WHERE sku_id=? FOR UPDATE",input.skuId()).isEmpty()) throw CommerceInput.missing("库存不存在");
            var existing=jdbc.queryForList("SELECT request_id,quantity FROM stock_logs WHERE order_id=? AND sku_id=? AND type='REFUND'",input.orderId(),input.skuId());
            if(!existing.isEmpty()) {
                var row=existing.getFirst();if(!input.requestId().equals(row.get("request_id")) || input.quantity()!=((Number)row.get("quantity")).intValue()) throw CommerceInput.conflict("退库请求参数冲突");return;
            }
            var confirmed=jdbc.queryForList("SELECT quantity FROM stock_logs WHERE order_id=? AND sku_id=? AND type='CONFIRM'",input.orderId(),input.skuId());
            if(confirmed.isEmpty() || input.quantity()!=((Number)confirmed.getFirst().get("quantity")).intValue()) throw CommerceInput.conflict("缺少匹配的已售库存记录");
            if(jdbc.update("UPDATE sku_stock SET sold_stock=sold_stock-?,available_stock=available_stock+?,version=version+1 WHERE sku_id=? AND sold_stock>=?",
                    input.quantity(),input.quantity(),input.skuId(),input.quantity())!=1) throw CommerceInput.conflict("已售库存不足");
            jdbc.update("INSERT INTO stock_logs(request_id,order_id,sku_id,quantity,type) VALUES (?,?,?,?,'REFUND')",input.requestId(),input.orderId(),input.skuId(),input.quantity());
        });
    }
}
