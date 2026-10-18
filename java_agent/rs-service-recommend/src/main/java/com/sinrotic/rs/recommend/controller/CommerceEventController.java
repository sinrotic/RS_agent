package com.sinrotic.rs.recommend.controller;
import com.sinrotic.rs.common.commerce.*;
import com.sinrotic.rs.recommend.service.impl.CommercePurchaseSignals;
import org.springframework.web.bind.annotation.*;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
@RestController
@ConditionalOnProperty(name="rs.recommend.commerce.enabled",havingValue="true")
public class CommerceEventController {
    private final CommercePurchaseSignals service;private final String token;
    public CommerceEventController(CommercePurchaseSignals service,@Value("${rs.commerce.service-token:}") String token) {this.service=service;this.token=token;}
    @PostMapping("/internal/recommend/commerce-events") public void accept(@RequestHeader(value="Authorization",required=false) String authorization,@RequestBody TradeEvent event) {
        CommerceServiceAuthorization.require(authorization,token);service.accept(event);
    }
}
