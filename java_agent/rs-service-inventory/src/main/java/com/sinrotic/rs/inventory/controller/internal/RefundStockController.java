package com.sinrotic.rs.inventory.controller.internal;
import com.sinrotic.rs.inventory.service.RefundStockService;
import com.sinrotic.rs.inventory.domain.dto.InventoryReleaseRequestDTO;
import org.springframework.web.bind.annotation.*;
@RestController
public class RefundStockController {
    private final RefundStockService service;
    public RefundStockController(RefundStockService service) {this.service=service;}
    @PostMapping("/internal/inventory/refund") public void refund(@RequestBody InventoryReleaseRequestDTO input) {service.refund(input);}
}
