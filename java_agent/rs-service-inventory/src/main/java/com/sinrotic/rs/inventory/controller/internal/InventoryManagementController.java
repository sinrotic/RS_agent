package com.sinrotic.rs.inventory.controller.internal;
import com.sinrotic.rs.inventory.service.InventoryManagement;
import com.sinrotic.rs.common.commerce.*;
import org.springframework.web.bind.annotation.*;
import jakarta.servlet.http.HttpServletRequest;
@RestController
@RequestMapping("/internal/inventory/management")
public class InventoryManagementController {
    private final InventoryManagement service;
    public InventoryManagementController(InventoryManagement service) {this.service=service;}
    @GetMapping("/stocks") public CommerceInput.Page<java.util.Map<String,Object>> stocks(@RequestParam(required=false) String afterId,@RequestParam(defaultValue="20") int limit) {return service.stocks(afterId,limit);}
    @GetMapping("/stocks/{sku}/ledger") public java.util.List<java.util.Map<String,Object>> ledger(@PathVariable String sku) {return service.ledger(sku);}
    @PostMapping("/adjustments") public java.util.Map<String,Object> adjust(@RequestBody InventoryManagement.Adjustment input,HttpServletRequest request) {return service.adjust(input,CommerceOperationsConfiguration.actor(request));}
    @PostMapping("/reconciliations") public java.util.List<java.util.Map<String,Object>> reconcile(@RequestParam(required=false) String afterId,@RequestParam(defaultValue="100") int limit) {return service.reconcile(afterId,limit);}
    @GetMapping("/reconciliations") public java.util.List<java.util.Map<String,Object>> cases() {return service.cases();}
    public record Disposition(String reason) {}
    @PostMapping("/reconciliations/{id}/acknowledge") public void acknowledge(@PathVariable String id,@RequestBody Disposition input,HttpServletRequest request) {service.acknowledge(id,CommerceOperationsConfiguration.actor(request),input.reason());}
}
