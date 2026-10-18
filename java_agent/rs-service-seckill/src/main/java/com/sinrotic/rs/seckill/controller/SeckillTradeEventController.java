package com.sinrotic.rs.seckill.controller;
import com.sinrotic.rs.common.commerce.*;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.web.bind.annotation.*;
import org.springframework.beans.factory.annotation.Value;
@RestController
public class SeckillTradeEventController {
    private final JdbcTemplate jdbc;private final String token;
    public SeckillTradeEventController(JdbcTemplate jdbc,@Value("${rs.commerce.service-token:}") String token) {this.jdbc=jdbc;this.token=token;}
    @PostMapping("/internal/seckill/order-events") public void accept(@RequestHeader(value="Authorization",required=false) String authorization,@RequestBody TradeEvent event) {
        CommerceServiceAuthorization.require(authorization,token);event.validate();
        if(event.type().equals("REFUNDED") && jdbc.update("UPDATE seckill_request_v1 SET status='REFUNDED' WHERE order_id=? AND account_id=? AND status IN ('PAID','REFUNDING','REFUNDED')",event.orderId(),event.accountId())==0)
            throw CommerceInput.conflict("秒杀对账尚未关联该订单，保留原事件重试");
    }
}
