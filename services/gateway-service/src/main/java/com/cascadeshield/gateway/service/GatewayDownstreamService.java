package com.cascadeshield.gateway.service;

import com.cascadeshield.common.client.DownstreamCaller;
import io.github.resilience4j.circuitbreaker.annotation.CircuitBreaker;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

@Service
public class GatewayDownstreamService {

    private final DownstreamCaller downstreamCaller;

    @Value("${downstream.order-service-url}")
    private String orderServiceUrl;

    @Value("${downstream.inventory-service-url}")
    private String inventoryServiceUrl;

    @Value("${downstream.payment-service-url}")
    private String paymentServiceUrl;

    public GatewayDownstreamService(DownstreamCaller downstreamCaller) {
        this.downstreamCaller = downstreamCaller;
    }

    @CircuitBreaker(name = "orderServiceCB")
    public Object callOrder() {
        return downstreamCaller.get(orderServiceUrl + "/api/v1/order", "order-service");
    }

    @CircuitBreaker(name = "inventoryServiceCB")
    public Object callInventory() {
        return downstreamCaller.get(inventoryServiceUrl + "/api/v1/inventory", "inventory-service");
    }

    @CircuitBreaker(name = "paymentServiceCB")
    public Object callPayment() {
        return downstreamCaller.get(paymentServiceUrl + "/api/v1/payment", "payment-service");
    }
}
