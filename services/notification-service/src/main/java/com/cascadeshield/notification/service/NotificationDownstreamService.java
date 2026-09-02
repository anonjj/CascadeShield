package com.cascadeshield.notification.service;

import com.cascadeshield.common.client.DownstreamCaller;
import io.github.resilience4j.circuitbreaker.annotation.CircuitBreaker;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

/**
 * CB-wrapped outbound call from notification-service to shared-db-service.
 * This is the missing piece that makes notification-service a full participant
 * in the cascade — without it, the Toxiproxy shared-db fault never opens a
 * CB in notification-service, understating blast radius in the mesh topology.
 */
@Service
public class NotificationDownstreamService {

    private final DownstreamCaller downstreamCaller;

    @Value("${downstream.shared-db-service-url}")
    private String sharedDbServiceUrl;

    public NotificationDownstreamService(DownstreamCaller downstreamCaller) {
        this.downstreamCaller = downstreamCaller;
    }

    @CircuitBreaker(name = "sharedDbCB")
    public Object callSharedDb() {
        return downstreamCaller.get(sharedDbServiceUrl + "/api/v1/shared-db", "shared-db-service");
    }
}
