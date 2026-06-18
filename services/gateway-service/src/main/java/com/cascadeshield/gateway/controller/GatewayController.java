package com.cascadeshield.gateway.controller;

import com.cascadeshield.gateway.service.BlastRadiusService;
import com.cascadeshield.gateway.service.GatewayDownstreamService;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.client.RestTemplate;

import java.util.LinkedHashMap;
import java.util.Map;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

@RestController
@RequestMapping("/api/v1")
public class GatewayController {

    private final GatewayDownstreamService downstreamService;
    private final BlastRadiusService blastRadiusService;
    private final RestTemplate restTemplate;

    @Value("${downstream.inventory-service-url:http://inventory-service:8082}")
    private String inventoryServiceUrl;

    @Value("${downstream.payment-service-url:http://payment-service:8083}")
    private String paymentServiceUrl;

    public GatewayController(GatewayDownstreamService downstreamService,
                              BlastRadiusService blastRadiusService,
                              RestTemplate restTemplate) {
        this.downstreamService = downstreamService;
        this.blastRadiusService = blastRadiusService;
        this.restTemplate = restTemplate;
    }

    /**
     * Linear chain: gateway -> order -> inventory -> payment -> notification
     * Fault propagates upstream through the chain.
     */
    @GetMapping("/linear")
    public ResponseEntity<Map<String, Object>> linear() {
        try {
            Object result = downstreamService.callOrder();
            return ResponseEntity.ok(Map.of("topology", "linear", "result", result != null ? result : "ok"));
        } catch (Exception e) {
            return ResponseEntity.status(503).body(Map.of(
                "topology", "linear",
                "error", "service_unavailable",
                "cause", e.getClass().getSimpleName()
            ));
        }
    }

    /**
     * Fan-out: gateway calls order, inventory, payment in parallel.
     * Independent failures — one slow/open CB does not block others.
     */
    @GetMapping("/fanout")
    public ResponseEntity<Map<String, Object>> fanout() {
        ExecutorService exec = Executors.newFixedThreadPool(3);
        try {
            CompletableFuture<Object> orderFuture = CompletableFuture.supplyAsync(
                () -> safeCall(downstreamService::callOrder, "order-service"), exec);
            CompletableFuture<Object> inventoryFuture = CompletableFuture.supplyAsync(
                () -> safeGet(inventoryServiceUrl + "/api/v1/inventory", "inventory-service"), exec);
            CompletableFuture<Object> paymentFuture = CompletableFuture.supplyAsync(
                () -> safeGet(paymentServiceUrl + "/api/v1/payment", "payment-service"), exec);

            CompletableFuture.allOf(orderFuture, inventoryFuture, paymentFuture).join();

            Map<String, Object> body = new LinkedHashMap<>();
            body.put("topology", "fanout");
            body.put("order", orderFuture.join());
            body.put("inventory", inventoryFuture.join());
            body.put("payment", paymentFuture.join());

            boolean anyFailed = body.values().stream()
                .anyMatch(v -> v instanceof Map<?, ?> m && m.containsKey("error"));
            return anyFailed
                ? ResponseEntity.status(503).body(body)
                : ResponseEntity.ok(body);
        } finally {
            exec.shutdown();
        }
    }

    /**
     * Shared-dependency mesh: same as fan-out at gateway level, but order/inventory/payment
     * each internally call shared-db-service, creating the shared-dependency mesh topology.
     * A fault on shared-db-service degrades all three simultaneously.
     */
    @GetMapping("/mesh")
    public ResponseEntity<Map<String, Object>> mesh() {
        return fanout();
    }

    /**
     * Returns the current blast radius: % of downstream services with an OPEN circuit breaker.
     */
    @GetMapping("/blast-radius")
    public ResponseEntity<Map<String, Object>> blastRadius() {
        double br = blastRadiusService.calculateBlastRadius();
        return ResponseEntity.ok(Map.of("blastRadius", br));
    }

    private Object safeCall(java.util.function.Supplier<Object> supplier, String serviceName) {
        try {
            return supplier.get();
        } catch (Exception e) {
            return Map.of("error", serviceName + " unavailable", "cause", e.getClass().getSimpleName());
        }
    }

    private Object safeGet(String url, String serviceName) {
        try {
            return restTemplate.getForObject(url, Object.class);
        } catch (Exception e) {
            return Map.of("error", serviceName + " unavailable", "cause", e.getClass().getSimpleName());
        }
    }
}
