package com.cascadeshield.inventory.controller;

import com.cascadeshield.inventory.model.InventoryItem;
import com.cascadeshield.inventory.model.ReserveRequest;
import com.cascadeshield.inventory.model.ReserveResponse;
import com.cascadeshield.inventory.service.InventoryService;
import jakarta.validation.Valid;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/inventory")
public class InventoryController {

    private final InventoryService inventoryService;

    public InventoryController(InventoryService inventoryService) {
        this.inventoryService = inventoryService;
    }

    /** GET /inventory/{sku} -> current stock level. */
    @GetMapping("/{sku}")
    public InventoryItem getStock(@PathVariable String sku) {
        return inventoryService.getItem(sku);
    }

    /** POST /inventory/reserve -> reserve units, returns what remains. */
    @PostMapping("/reserve")
    public ReserveResponse reserve(@Valid @RequestBody ReserveRequest request) {
        return inventoryService.reserve(request.sku(), request.quantity());
    }
}
