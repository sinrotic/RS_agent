package com.sinrotic.rs.inventory.controller.internal;

import com.sinrotic.rs.inventory.domain.dto.InventoryConfirmRequestDTO;
import com.sinrotic.rs.inventory.domain.dto.InventoryLockRequestDTO;
import com.sinrotic.rs.inventory.domain.dto.InventoryReleaseRequestDTO;
import com.sinrotic.rs.inventory.service.InventoryService;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/internal/inventory")
public class InternalInventoryController {

    private final InventoryService inventoryService;

    public InternalInventoryController(InventoryService inventoryService) {
        this.inventoryService = inventoryService;
    }

    @PostMapping("/lock")
    public void lockStock(@RequestBody InventoryLockRequestDTO request) {
        inventoryService.lockStock(request);
    }

    @PostMapping("/confirm-deduct")
    public void confirmDeduct(@RequestBody InventoryConfirmRequestDTO request) {
        inventoryService.confirmDeduct(request);
    }

    @PostMapping("/release")
    public void releaseStock(@RequestBody InventoryReleaseRequestDTO request) {
        inventoryService.releaseStock(request);
    }
}
