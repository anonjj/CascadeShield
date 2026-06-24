package com.cascadeshield.order.exception;

import org.springframework.http.HttpStatusCode;

/**
 * Thrown when inventory returns a 4xx (e.g. 409 insufficient stock).
 * This is a deliberate business response, NOT a fault — inventoryServiceCB
 * must NOT count it (listed in ignore-exceptions in application.yml).
 */
public class DownstreamRejectedException extends RuntimeException {
    private final HttpStatusCode status;

    public DownstreamRejectedException(HttpStatusCode status, String body) {
        super("Downstream rejected with " + status + ": " + body);
        this.status = status;
    }

    public HttpStatusCode getStatus() { return status; }
}
