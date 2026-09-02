package com.cascadeshield.payment.service;

import com.cascadeshield.common.client.DownstreamCaller;
import io.github.resilience4j.circuitbreaker.annotation.CircuitBreaker;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

@Service
public class PaymentDownstreamService {

    private final DownstreamCaller downstreamCaller;

    @Value("${downstream.notification-service-url}")
    private String notificationServiceUrl;

    @Value("${downstream.shared-db-service-url}")
    private String sharedDbServiceUrl;

    public PaymentDownstreamService(DownstreamCaller downstreamCaller) {
        this.downstreamCaller = downstreamCaller;
    }

    @CircuitBreaker(name = "notificationServiceCB")
    public Object callNotification() {
        return downstreamCaller.get(notificationServiceUrl + "/api/v1/notification", "notification-service");
    }

    @CircuitBreaker(name = "sharedDbCB")
    public Object callSharedDb() {
        return downstreamCaller.get(sharedDbServiceUrl + "/api/v1/shared-db", "shared-db-service");
    }
}
