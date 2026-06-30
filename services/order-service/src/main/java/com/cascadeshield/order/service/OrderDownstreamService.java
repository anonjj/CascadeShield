package com.cascadeshield.order.service;

import com.cascadeshield.order.exception.DownstreamRejectedException;
import com.cascadeshield.order.exception.DownstreamUnavailableException;
import io.github.resilience4j.circuitbreaker.annotation.CircuitBreaker;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.web.client.HttpClientErrorException;
import org.springframework.web.client.HttpServerErrorException;
import org.springframework.web.client.ResourceAccessException;
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

    /**
     * CB-wrapped call to inventory. The exception split is load-bearing for
     * blast-radius correctness:
     *   - 4xx (business rejection) → DownstreamRejectedException → ignored by inventoryServiceCB
     *   - 5xx / timeout           → DownstreamUnavailableException → recorded by inventoryServiceCB
     */
    @CircuitBreaker(name = "inventoryServiceCB")
    public Object callInventory() {
        try {
            return restTemplate.getForObject(inventoryServiceUrl + "/api/v1/inventory", Object.class);
        } catch (HttpClientErrorException ex) {
            throw new DownstreamRejectedException(ex.getStatusCode(), ex.getResponseBodyAsString());
        } catch (HttpServerErrorException ex) {
            throw new DownstreamUnavailableException("inventory-service unreachable", ex);
        } catch (ResourceAccessException ex) {
            throw new DownstreamUnavailableException("inventory-service unreachable", ex);
        }
    }

    @CircuitBreaker(name = "sharedDbCB")
    public Object callSharedDb() {
        try {
            return restTemplate.getForObject(sharedDbServiceUrl + "/api/v1/shared-db", Object.class);
        } catch (HttpClientErrorException ex) {
            throw new DownstreamRejectedException(ex.getStatusCode(), ex.getResponseBodyAsString());
        } catch (HttpServerErrorException ex) {
            throw new DownstreamUnavailableException("shared-db-service unreachable", ex);
        } catch (ResourceAccessException ex) {
            throw new DownstreamUnavailableException("shared-db-service unreachable", ex);
        }
    }
}
