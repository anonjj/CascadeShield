package com.cascadeshield.order.controller;

import com.cascadeshield.order.service.OrderDownstreamService;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.LinkedHashMap;
import java.util.Map;

@RestController
@RequestMapping("/api/v1")
public class OrderController {

    private final OrderDownstreamService downstreamService;

    public OrderController(OrderDownstreamService downstreamService) {
        this.downstreamService = downstreamService;
    }

    @GetMapping("/order")
    public ResponseEntity<Map<String, Object>> order() {
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("service", "order-service");
        boolean failed = false;

        try {
            String inventoryResult = downstreamService.callInventory();
            body.put("inventory", inventoryResult != null ? inventoryResult : "ok");
        } catch (Exception e) {
            body.put("inventory", Map.of("error", "unavailable", "cause", e.getClass().getSimpleName()));
            failed = true;
        }

        try {
            String dbResult = downstreamService.callSharedDb();
            body.put("sharedDb", dbResult != null ? dbResult : "ok");
        } catch (Exception e) {
            body.put("sharedDb", Map.of("error", "unavailable", "cause", e.getClass().getSimpleName()));
            failed = true;
        }

        return failed ? ResponseEntity.status(503).body(body) : ResponseEntity.ok(body);
    }
}
