package com.cascadeshield.gateway.service;

import io.github.resilience4j.circuitbreaker.annotation.CircuitBreaker;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestTemplate;

@Service
public class GatewayDownstreamService {

    private final RestTemplate restTemplate;

    @Value("${downstream.order-service-url}")
    private String orderServiceUrl;

    public GatewayDownstreamService(RestTemplate restTemplate) {
        this.restTemplate = restTemplate;
    }

    /**
     * CB-wrapped call to order-service. No fallback — exception propagates to controller
     * which returns HTTP 503 so the load generator counts it as a failure.
     */
    @CircuitBreaker(name = "orderServiceCB")
    public Object callOrder() {
        return restTemplate.getForObject(orderServiceUrl + "/api/v1/order", Object.class);
    }
}
