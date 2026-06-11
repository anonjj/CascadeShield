package com.cascadeshield.order.service;

import io.github.resilience4j.circuitbreaker.annotation.CircuitBreaker;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestTemplate;

@Service
public class OrderDownstreamService {

    private final RestTemplate restTemplate;

    @Value("${downstream.inventory-service-url}")
    private String inventoryServiceUrl;

    @Value("${downstream.shared-db-service-url}")
    private String sharedDbServiceUrl;

    public OrderDownstreamService(RestTemplate restTemplate) {
        this.restTemplate = restTemplate;
    }

    @CircuitBreaker(name = "inventoryServiceCB")
    public String callInventory() {
        return restTemplate.getForObject(inventoryServiceUrl + "/api/v1/inventory", String.class);
    }

    @CircuitBreaker(name = "sharedDbCB")
    public String callSharedDb() {
        return restTemplate.getForObject(sharedDbServiceUrl + "/api/v1/shared-db", String.class);
    }
}
