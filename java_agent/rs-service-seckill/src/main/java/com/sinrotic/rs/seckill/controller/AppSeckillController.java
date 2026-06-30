package com.sinrotic.rs.seckill.controller;

import com.sinrotic.rs.seckill.domain.dto.SeckillSubmitRequestDTO;
import com.sinrotic.rs.seckill.domain.vo.SeckillSubmitVO;
import com.sinrotic.rs.seckill.service.SeckillService;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/seckill")
public class AppSeckillController {

    private final SeckillService seckillService;

    public AppSeckillController(SeckillService seckillService) {
        this.seckillService = seckillService;
    }

    @PostMapping("/activities/{activityId}/submit")
    public SeckillSubmitVO submit(
            @PathVariable String activityId,
            @RequestBody SeckillSubmitRequestDTO request
    ) {
        if (request == null) {
            return seckillService.submit(null);
        }
        return seckillService.submit(new SeckillSubmitRequestDTO(
                request.requestId(),
                request.accountId(),
                activityId,
                request.itemId(),
                request.skuId(),
                request.quantity()
        ));
    }
}
