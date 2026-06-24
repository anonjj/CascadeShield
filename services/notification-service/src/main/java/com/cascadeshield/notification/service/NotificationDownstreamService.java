package com.cascadeshield.notification.service;

import com.cascadeshield.notification.exception.DownstreamRejectedException;
import com.cascadeshield.notification.exception.DownstreamUnavailableException;
import io.github.resilience4j.circuitbreaker.annotation.CircuitBreaker;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.web.client.HttpClientErrorException;
import org.springframework.web.client.RestClientException;
import org.springframework.web.client.RestTemplate;

/**
 * CB-wrapped outbound call from notification-service to shared-db-service.
 * This is the missing piece that makes notification-service a full participant
 * in the cascade — without it, the Toxiproxy shared-db fault never opens a
 * CB in notification-service, understating blast radius in the mesh topology.
 */
@Service
public class NotificationDownstreamService {

    private final RestTemplate restTemplate;

    @Value("${downstream.shared-db-service-url}")
    private String sharedDbServiceUrl;

    public NotificationDownstreamService(RestTemplate restTemplate) {
        this.restTemplate = restTemplate;
    }

    @CircuitBreaker(name = "sharedDbCB")
    public Object callSharedDb() {
        try {
            return restTemplate.getForObject(sharedDbServiceUrl + "/api/v1/shared-db", Object.class);
        } catch (HttpClientErrorException ex) {
            throw new DownstreamRejectedException(ex.getStatusCode(), ex.getResponseBodyAsString());
        } catch (RestClientException ex) {
            throw new DownstreamUnavailableException("shared-db-service unreachable", ex);
        }
    }
}
