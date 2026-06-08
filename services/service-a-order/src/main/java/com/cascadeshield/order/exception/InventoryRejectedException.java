package com.cascadeshield.order.exception;

import org.springframework.http.HttpStatusCode;

/**
 * Raised when Service B returns a 4xx — a business rejection (e.g. 409
 * insufficient stock, 404 unknown SKU). This is a normal outcome, NOT a
 * service fault, so it must never be counted against the circuit breaker.
 * Service A mirrors B's status code rather than masking it as a 503.
 */
public class InventoryRejectedException extends RuntimeException {
    private final HttpStatusCode status;

    public InventoryRejectedException(HttpStatusCode status, String detail) {
        super(detail);
        this.status = status;
    }

    public HttpStatusCode getStatus() {
        return status;
    }
}
