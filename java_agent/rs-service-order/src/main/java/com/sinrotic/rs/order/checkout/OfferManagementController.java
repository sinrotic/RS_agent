package com.sinrotic.rs.order.checkout;
import com.sinrotic.rs.common.commerce.*;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;
import org.springframework.web.bind.annotation.*;
import jakarta.servlet.http.HttpServletRequest;
import java.time.*;
@RestController
@RequestMapping("/internal/checkout/offers")
public class OfferManagementController {
    private final JdbcTemplate jdbc;private final TransactionTemplate tx;
    public record Offer(String skuId,String itemId,String itemTitle,long unitPrice,boolean active,String reason) {}
    public OfferManagementController(JdbcTemplate jdbc,PlatformTransactionManager manager) {this.jdbc=jdbc;tx=new TransactionTemplate(manager);}
    @GetMapping public CommerceInput.Page<java.util.Map<String,Object>> list(@RequestParam(required=false) String afterId,@RequestParam(defaultValue="20") int limit) {
        CommerceInput.limit(limit);if(afterId!=null) CommerceInput.id(afterId);
        var rows=jdbc.queryForList("SELECT * FROM checkout_offer WHERE sku_id>? ORDER BY sku_id LIMIT ?",afterId==null ? "" : afterId,limit+1);
        boolean more=rows.size()>limit;var items=more ? rows.subList(0,limit) : rows;return new CommerceInput.Page<>(items,more ? (String)items.getLast().get("sku_id") : null);
    }
    @PostMapping public void save(@RequestBody Offer offer,HttpServletRequest request) {
        if(offer==null || offer.unitPrice()<=0 || offer.itemTitle()==null || offer.itemTitle().isBlank() || offer.itemTitle().length()>255) throw CommerceInput.bad("报价参数不合法");
        CommerceInput.id(offer.skuId());CommerceInput.id(offer.itemId());CommerceInput.reason(offer.reason());String actor=CommerceOperationsConfiguration.actor(request);
        tx.executeWithoutResult(s->{
            jdbc.update("INSERT INTO checkout_offer(sku_id,item_id,item_title,unit_price,active) VALUES (?,?,?,?,?) ON DUPLICATE KEY UPDATE sku_id=sku_id",offer.skuId(),offer.itemId(),offer.itemTitle(),offer.unitPrice(),offer.active());
            var row=jdbc.queryForMap("SELECT item_id FROM checkout_offer WHERE sku_id=? FOR UPDATE",offer.skuId());
            if(!offer.itemId().equals(row.get("item_id"))) throw CommerceInput.conflict("SKU 不能更换所属商品");
            jdbc.update("UPDATE checkout_offer SET item_title=?,unit_price=?,active=? WHERE sku_id=?",offer.itemTitle(),offer.unitPrice(),offer.active(),offer.skuId());
            jdbc.update("INSERT INTO commerce_operation_audit(component,resource_id,operator_id,action,reason,created_at) VALUES ('offer',?,?,'SAVE',?,?)",offer.skuId(),actor,offer.reason(),LocalDateTime.now(Clock.systemUTC()));
        });
    }
}
