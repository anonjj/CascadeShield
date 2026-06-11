package com.cascadeshield.inventory.service;

import io.github.resilience4j.circuitbreaker.annotation.CircuitBreaker;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestTemplate;

@Service
public class InventoryDownstreamService {

    private final RestTemplate restTemplate;

    @Value("${downstream.payment-service-url}")
    private String paymentServiceUrl;

    @Value("${downstream.shared-db-service-url}")
    private String sharedDbServiceUrl;

    public InventoryDownstreamService(RestTemplate restTemplate) {
        this.restTemplate = restTemplate;
    }

    @CircuitBreaker(name = "paymentServiceCB")
    public String callPayment() {
        return restTemplate.getForObject(paymentServiceUrl + "/api/v1/payment", String.class);
    }

    @CircuitBreaker(name = "sharedDbCB")
    public String callSharedDb() {
        return restTemplate.getForObject(sharedDbServiceUrl + "/api/v1/shared-db", String.class);
    }
}
