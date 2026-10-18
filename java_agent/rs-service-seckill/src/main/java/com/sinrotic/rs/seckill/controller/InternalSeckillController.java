package com.sinrotic.rs.seckill.controller;

import com.sinrotic.rs.seckill.service.SeckillService;
import org.springframework.web.bind.annotation.*;

@RestController
public class InternalSeckillController {
    private final SeckillService service;
    public InternalSeckillController(SeckillService service) { this.service=service; }
    @PostMapping("/internal/seckill/activities")
    public void create(@RequestBody SeckillService.Activity activity) { service.createActivity(activity); }
    @GetMapping("/internal/seckill/activities")
    public com.sinrotic.rs.common.commerce.CommerceInput.Page<java.util.Map<String,Object>> activities(@RequestParam(required=false) String afterId,@RequestParam(defaultValue="20") int limit) {return service.managementActivities(afterId,limit);}
    @GetMapping("/internal/seckill/tasks")
    public java.util.List<SeckillService.TaskView> tasks(@RequestParam(defaultValue="60") int minimumAgeSeconds) {
        return service.stalledTasks(minimumAgeSeconds);
    }
    @GetMapping("/internal/seckill/tasks/summary")
    public java.util.Map<String,Long> summary() { return service.taskSummary(); }
    @PostMapping("/internal/seckill/tasks/{eventId}/retry")
    public void retry(@PathVariable String eventId,@RequestBody SeckillService.OperatorAction action,jakarta.servlet.http.HttpServletRequest request) {
        service.retryTask(eventId,authenticated(action,request));
    }
    @GetMapping("/internal/seckill/allocations")
    public java.util.List<java.util.Map<String,Object>> allocations() {return service.allocationTasks();}
    @PostMapping("/internal/seckill/allocations/{id}/retry")
    public void retryAllocation(@PathVariable String id,@RequestBody SeckillService.OperatorAction action,jakarta.servlet.http.HttpServletRequest request) {
        service.retryAllocation(id,authenticated(action,request));
    }
    private SeckillService.OperatorAction authenticated(SeckillService.OperatorAction action,jakarta.servlet.http.HttpServletRequest request) {
        return new SeckillService.OperatorAction(com.sinrotic.rs.common.commerce.CommerceOperationsConfiguration.actor(request),action.reason());
    }
}
