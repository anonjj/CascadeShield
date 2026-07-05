package com.cascadeshield.order.controller;

import com.cascadeshield.order.exception.DownstreamRejectedException;
import com.cascadeshield.order.exception.DownstreamUnavailableException;
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
        org.springframework.http.HttpStatusCode worst = org.springframework.http.HttpStatus.OK;

        try {
            Object inventoryResult = downstreamService.callInventory();
            body.put("inventory", inventoryResult != null ? inventoryResult : "ok");
        } catch (DownstreamRejectedException e) {
            body.put("inventory", Map.of("error", "rejected", "status", e.getStatus().value()));
            worst = worse(worst, e.getStatus());
        } catch (io.github.resilience4j.circuitbreaker.CallNotPermittedException
                | DownstreamUnavailableException e) {
            body.put("inventory", Map.of("error", "unavailable", "cause", e.getClass().getSimpleName()));
            worst = worse(worst, org.springframework.http.HttpStatus.SERVICE_UNAVAILABLE);
        }

        try {
            Object dbResult = downstreamService.callSharedDb();
            body.put("sharedDb", dbResult != null ? dbResult : "ok");
        } catch (DownstreamRejectedException e) {
            body.put("sharedDb", Map.of("error", "rejected", "status", e.getStatus().value()));
            worst = worse(worst, e.getStatus());
        } catch (io.github.resilience4j.circuitbreaker.CallNotPermittedException
                | DownstreamUnavailableException e) {
            body.put("sharedDb", Map.of("error", "unavailable", "cause", e.getClass().getSimpleName()));
            worst = worse(worst, org.springframework.http.HttpStatus.SERVICE_UNAVAILABLE);
        }

        return ResponseEntity.status(worst).body(body);
    }

    private static org.springframework.http.HttpStatusCode worse(
            org.springframework.http.HttpStatusCode a,
            org.springframework.http.HttpStatusCode b) {
        return b.value() > a.value() ? b : a;
    }
}
