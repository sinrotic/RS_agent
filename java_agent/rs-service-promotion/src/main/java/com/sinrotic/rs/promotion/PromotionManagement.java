package com.sinrotic.rs.promotion;
import com.sinrotic.rs.common.commerce.*;
import org.springframework.stereotype.Service;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;
import java.time.*;
import java.util.*;
@Service
public class PromotionManagement {
    private final JdbcTemplate jdbc;private final TransactionTemplate tx;private final PromotionService service;
    public PromotionManagement(JdbcTemplate jdbc,PlatformTransactionManager manager,PromotionService service) {this.jdbc=jdbc;tx=new TransactionTemplate(manager);this.service=service;}
    public CommerceInput.Page<Map<String,Object>> list(String afterId,int limit) {
        CommerceInput.limit(limit);if(afterId!=null) CommerceInput.id(afterId);
        var rows=jdbc.queryForList("SELECT * FROM promotion_campaign WHERE campaign_id>? ORDER BY campaign_id LIMIT ?",afterId==null ? "" : afterId,limit+1);
        boolean more=rows.size()>limit;var items=more ? rows.subList(0,limit) : rows;return new CommerceInput.Page<>(items,more ? (String)items.getLast().get("campaign_id") : null);
    }
    public void create(PromotionService.Campaign input,String actor) {
        tx.executeWithoutResult(s->{
            try {service.createCampaign(input);} catch(org.springframework.dao.DuplicateKeyException duplicate) {
                var row=jdbc.queryForMap("SELECT * FROM promotion_campaign WHERE campaign_id=? FOR UPDATE",input.campaignId());
                if(!input.title().equals(row.get("title")) || !Objects.equals(input.itemId(),row.get("item_id"))
                        || input.totalQuantity()!=((Number)row.get("total_quantity")).intValue()
                        || input.minimumAmount()!=((Number)row.get("minimum_amount")).longValue()
                        || input.discountAmount()!=((Number)row.get("discount_amount")).longValue()
                        || !sameTime(input.startsAt(),row.get("starts_at")) || !sameTime(input.endsAt(),row.get("ends_at"))
                        || !sameTime(input.expiresAt(),row.get("expires_at"))) throw CommerceInput.conflict("活动标识已用于不同发布参数");
                return;
            }
            jdbc.update("INSERT INTO commerce_operation_audit(component,resource_id,operator_id,action,reason,created_at) VALUES ('campaign',?,?,'CREATE','发布限量满减活动',?)",input.campaignId(),actor,LocalDateTime.now(Clock.systemUTC()));
        });
    }
    private static boolean sameTime(LocalDateTime input,Object stored) {
        var value=stored instanceof java.sql.Timestamp timestamp ? timestamp.toLocalDateTime() : (LocalDateTime)stored;
        return input.truncatedTo(java.time.temporal.ChronoUnit.MICROS).equals(value);
    }
}
