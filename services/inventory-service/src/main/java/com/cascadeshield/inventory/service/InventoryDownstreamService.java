package com.cascadeshield.inventory.service;

import com.cascadeshield.inventory.exception.DownstreamRejectedException;
import com.cascadeshield.inventory.exception.DownstreamUnavailableException;
import io.github.resilience4j.circuitbreaker.annotation.CircuitBreaker;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.web.client.HttpClientErrorException;
import org.springframework.web.client.HttpServerErrorException;
import org.springframework.web.client.ResourceAccessException;
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
    public Object callPayment() {
        try {
            return restTemplate.getForObject(paymentServiceUrl + "/api/v1/payment", Object.class);
        } catch (HttpClientErrorException ex) {
            throw new DownstreamRejectedException(ex.getStatusCode(), ex.getResponseBodyAsString());
        } catch (HttpServerErrorException ex) {
            throw new DownstreamUnavailableException("payment-service unreachable", ex);
        } catch (ResourceAccessException ex) {
            throw new DownstreamUnavailableException("payment-service unreachable", ex);
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
