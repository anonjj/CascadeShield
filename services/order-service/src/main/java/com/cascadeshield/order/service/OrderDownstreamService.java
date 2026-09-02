package com.cascadeshield.order.service;

import com.cascadeshield.common.client.DownstreamCaller;
import io.github.resilience4j.circuitbreaker.annotation.CircuitBreaker;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

@Service
public class OrderDownstreamService {

    private final DownstreamCaller downstreamCaller;

    @Value("${downstream.inventory-service-url}")
    private String inventoryServiceUrl;

    @Value("${downstream.shared-db-service-url}")
    private String sharedDbServiceUrl;

    public OrderDownstreamService(DownstreamCaller downstreamCaller) {
        this.downstreamCaller = downstreamCaller;
    }

    /**
     * CB-wrapped call to inventory. The exception split (in DownstreamCaller) is load-bearing
     * for blast-radius correctness:
     *   - 4xx (business rejection) → DownstreamRejectedException → ignored by inventoryServiceCB
     *   - 5xx / timeout           → DownstreamUnavailableException → recorded by inventoryServiceCB
     */
    @CircuitBreaker(name = "inventoryServiceCB")
    public Object callInventory() {
        return downstreamCaller.get(inventoryServiceUrl + "/api/v1/inventory", "inventory-service");
    }

    @CircuitBreaker(name = "sharedDbCB")
    public Object callSharedDb() {
        return downstreamCaller.get(sharedDbServiceUrl + "/api/v1/shared-db", "shared-db-service");
    }
}
