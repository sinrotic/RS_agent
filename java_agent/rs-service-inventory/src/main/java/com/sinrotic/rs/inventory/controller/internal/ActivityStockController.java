package com.sinrotic.rs.inventory.controller.internal;

import com.sinrotic.rs.inventory.service.ActivityStockService;
import org.springframework.web.bind.annotation.*;
import java.util.Map;

@RestController
@RequestMapping("/internal/inventory/activities")
public class ActivityStockController {
    private final ActivityStockService service;
    public ActivityStockController(ActivityStockService service) {this.service=service;}
    @PostMapping("/allocate") public void allocate(@RequestBody ActivityStockService.Allocation input) {service.allocate(input);}
    @GetMapping("/{id}") public Map<String,Object> view(@PathVariable String id) {return service.view(id);}
    @PostMapping("/{id}/close") public void close(@PathVariable String id) {service.close(id);}
    @PostMapping("/movements/{action}") public void move(@PathVariable String action,@RequestBody ActivityStockService.Movement input) {service.move(action,input);}
}
