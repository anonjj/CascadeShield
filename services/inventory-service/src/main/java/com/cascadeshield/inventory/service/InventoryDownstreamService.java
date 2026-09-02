package com.cascadeshield.inventory.service;

import com.cascadeshield.common.client.DownstreamCaller;
import io.github.resilience4j.circuitbreaker.annotation.CircuitBreaker;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

@Service
public class InventoryDownstreamService {

    private final DownstreamCaller downstreamCaller;

    @Value("${downstream.payment-service-url}")
    private String paymentServiceUrl;

    @Value("${downstream.shared-db-service-url}")
    private String sharedDbServiceUrl;

    public InventoryDownstreamService(DownstreamCaller downstreamCaller) {
        this.downstreamCaller = downstreamCaller;
    }

    @CircuitBreaker(name = "paymentServiceCB")
    public Object callPayment() {
        return downstreamCaller.get(paymentServiceUrl + "/api/v1/payment", "payment-service");
    }

    @CircuitBreaker(name = "sharedDbCB")
    public Object callSharedDb() {
        return downstreamCaller.get(sharedDbServiceUrl + "/api/v1/shared-db", "shared-db-service");
    }
}
