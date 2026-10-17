package com.sinrotic.rs.seckill.controller;

import com.sinrotic.rs.seckill.domain.dto.SeckillSubmitRequestDTO;
import com.sinrotic.rs.seckill.domain.vo.SeckillSubmitVO;
import com.sinrotic.rs.seckill.service.SeckillService;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/seckill")
public class AppSeckillController {

    private final SeckillService seckillService;

    public AppSeckillController(SeckillService seckillService) {
        this.seckillService = seckillService;
    }

    @org.springframework.web.bind.annotation.GetMapping("/activities")
    public java.util.List<SeckillService.ActivityView> activities(@RequestHeader("X-Account-Id") String accountId,
            @org.springframework.web.bind.annotation.RequestParam String itemId) { return seckillService.activities(accountId,itemId); }

    @org.springframework.web.bind.annotation.GetMapping("/activities/{activityId}")
    public SeckillService.ActivityView activity(@RequestHeader("X-Account-Id") String accountId,@PathVariable String activityId) {
        return seckillService.activity(accountId,activityId);
    }

    @org.springframework.web.bind.annotation.GetMapping("/requests/{requestId}")
    public SeckillSubmitVO result(@RequestHeader("X-Account-Id") String accountId,@PathVariable String requestId) {
        return seckillService.result(accountId,requestId);
    }

    @PostMapping("/activities/{activityId}/submit")
    public SeckillSubmitVO submit(
            @PathVariable String activityId,
            @RequestHeader("X-Account-Id") String accountId,
            @RequestBody SeckillSubmitRequestDTO request
    ) {
        if (request == null) {
            return seckillService.submit(null);
        }
        return seckillService.submit(new SeckillSubmitRequestDTO(
                request.requestId(),
                accountId,
                activityId,
                request.itemId(),
                request.skuId(),
                request.quantity()
        ));
    }
}
