package com.sinrotic.rs.inventory.controller.app;

import com.sinrotic.rs.inventory.domain.vo.ItemAvailabilityVO;
import com.sinrotic.rs.inventory.service.InventoryService;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;

@RestController
@RequestMapping("/api/inventory/items")
public class AppInventoryController {

    private final InventoryService inventoryService;

    public AppInventoryController(InventoryService inventoryService) {
        this.inventoryService = inventoryService;
    }

    @GetMapping("/{itemId}/availability")
    public ItemAvailabilityVO getItemAvailability(@PathVariable String itemId) {
        ItemAvailabilityVO availability = inventoryService.getItemAvailability(itemId);
        if (availability == null) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "Inventory item not found");
        }
        return availability;
    }
}
