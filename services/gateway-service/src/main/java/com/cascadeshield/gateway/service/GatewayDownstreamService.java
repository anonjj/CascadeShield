package com.cascadeshield.gateway.service;

import com.cascadeshield.gateway.exception.DownstreamRejectedException;
import com.cascadeshield.gateway.exception.DownstreamUnavailableException;
import io.github.resilience4j.circuitbreaker.annotation.CircuitBreaker;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.web.client.HttpClientErrorException;
import org.springframework.web.client.RestClientException;
import org.springframework.web.client.RestTemplate;

@Service
public class GatewayDownstreamService {

    private final RestTemplate restTemplate;

    @Value("${downstream.order-service-url}")
    private String orderServiceUrl;

    @Value("${downstream.inventory-service-url}")
    private String inventoryServiceUrl;

    @Value("${downstream.payment-service-url}")
    private String paymentServiceUrl;

    public GatewayDownstreamService(RestTemplate restTemplate) {
        this.restTemplate = restTemplate;
    }

    @CircuitBreaker(name = "orderServiceCB")
    public Object callOrder() {
        return get(orderServiceUrl + "/api/v1/order", "order-service");
    }

    @CircuitBreaker(name = "inventoryServiceCB")
    public Object callInventory() {
        return get(inventoryServiceUrl + "/api/v1/inventory", "inventory-service");
    }

    @CircuitBreaker(name = "paymentServiceCB")
    public Object callPayment() {
        return get(paymentServiceUrl + "/api/v1/payment", "payment-service");
    }

    /**
     * Shared call+classify helper, mirroring the pattern in
     * service-a-order's InventoryClient.
     *   - 4xx                       -> DownstreamRejectedException -> ignored by the CB
     *   - 5xx / timeout / refused   -> DownstreamUnavailableException -> recorded by the CB
     */
    private Object get(String url, String serviceName) {
        try {
            return restTemplate.getForObject(url, Object.class);
        } catch (HttpClientErrorException ex) {
            throw new DownstreamRejectedException(ex.getStatusCode(), ex.getResponseBodyAsString());
        } catch (RestClientException ex) {
            throw new DownstreamUnavailableException(serviceName + " unreachable", ex);
        }
    }
}
