package com.cascadeshield.gateway.exception;

import org.springframework.http.HttpStatusCode;

public class DownstreamRejectedException extends RuntimeException {
    private final HttpStatusCode status;

    public DownstreamRejectedException(HttpStatusCode status, String body) {
        super("Downstream rejected with " + status + ": " + body);
        this.status = status;
    }

    public HttpStatusCode getStatus() { return status; }
}
