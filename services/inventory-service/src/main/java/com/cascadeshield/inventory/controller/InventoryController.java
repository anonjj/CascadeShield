package com.cascadeshield.inventory.controller;

import com.cascadeshield.inventory.service.InventoryDownstreamService;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.LinkedHashMap;
import java.util.Map;

@RestController
@RequestMapping("/api/v1")
public class InventoryController {

    private final InventoryDownstreamService downstreamService;

    public InventoryController(InventoryDownstreamService downstreamService) {
        this.downstreamService = downstreamService;
    }

    @GetMapping("/inventory")
    public ResponseEntity<Map<String, Object>> inventory() {
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("service", "inventory-service");
        boolean failed = false;

        try {
            Object paymentResult = downstreamService.callPayment();
            body.put("payment", paymentResult != null ? paymentResult : "ok");
        } catch (Exception e) {
            body.put("payment", Map.of("error", "unavailable", "cause", e.getClass().getSimpleName()));
            failed = true;
        }

        try {
            Object dbResult = downstreamService.callSharedDb();
            body.put("sharedDb", dbResult != null ? dbResult : "ok");
        } catch (Exception e) {
            body.put("sharedDb", Map.of("error", "unavailable", "cause", e.getClass().getSimpleName()));
            failed = true;
        }

        return failed ? ResponseEntity.status(503).body(body) : ResponseEntity.ok(body);
    }
}
