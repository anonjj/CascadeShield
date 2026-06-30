package com.cascadeshield.payment.service;

import com.cascadeshield.payment.exception.DownstreamRejectedException;
import com.cascadeshield.payment.exception.DownstreamUnavailableException;
import io.github.resilience4j.circuitbreaker.annotation.CircuitBreaker;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.web.client.HttpClientErrorException;
import org.springframework.web.client.HttpServerErrorException;
import org.springframework.web.client.ResourceAccessException;
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
    public Object callNotification() {
        try {
            return restTemplate.getForObject(notificationServiceUrl + "/api/v1/notification", Object.class);
        } catch (HttpClientErrorException ex) {
            throw new DownstreamRejectedException(ex.getStatusCode(), ex.getResponseBodyAsString());
        } catch (HttpServerErrorException ex) {
            throw new DownstreamUnavailableException("notification-service unreachable", ex);
        } catch (ResourceAccessException ex) {
            throw new DownstreamUnavailableException("notification-service unreachable", ex);
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
