package com.cascadeshield.inventory.controller;

import com.cascadeshield.inventory.exception.DownstreamRejectedException;
import com.cascadeshield.inventory.exception.DownstreamUnavailableException;
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
        org.springframework.http.HttpStatusCode worst = org.springframework.http.HttpStatus.OK;

        try {
            Object paymentResult = downstreamService.callPayment();
            body.put("payment", paymentResult != null ? paymentResult : "ok");
        } catch (DownstreamRejectedException e) {
            body.put("payment", Map.of("error", "rejected", "status", e.getStatus().value()));
            worst = worse(worst, e.getStatus());
        } catch (io.github.resilience4j.circuitbreaker.CallNotPermittedException
                | DownstreamUnavailableException e) {
            body.put("payment", Map.of("error", "unavailable", "cause", e.getClass().getSimpleName()));
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
