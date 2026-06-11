package com.cascadeshield.payment.service;

import io.github.resilience4j.circuitbreaker.annotation.CircuitBreaker;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestTemplate;

@Service
public class PaymentDownstreamService {

    private final RestTemplate restTemplate;

    @Value("${downstream.notification-service-url}")
    private String notificationServiceUrl;

    @Value("${downstream.shared-db-service-url}")
    private String sharedDbServiceUrl;

    public PaymentDownstreamService(RestTemplate restTemplate) {
        this.restTemplate = restTemplate;
    }

    @CircuitBreaker(name = "notificationServiceCB")
    public String callNotification() {
        return restTemplate.getForObject(notificationServiceUrl + "/api/v1/notification", String.class);
    }

    @CircuitBreaker(name = "sharedDbCB")
    public String callSharedDb() {
        return restTemplate.getForObject(sharedDbServiceUrl + "/api/v1/shared-db", String.class);
    }
}
