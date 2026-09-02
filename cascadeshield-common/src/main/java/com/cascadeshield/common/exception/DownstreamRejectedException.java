package com.cascadeshield.common.exception;

import org.springframework.http.HttpStatusCode;

/**
 * Thrown when a downstream call returns a 4xx (e.g. a business validation error).
 * This is a deliberate business response, NOT a fault -- the caller's circuit breaker
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
