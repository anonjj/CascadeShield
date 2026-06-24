package com.cascadeshield.order.exception;

import io.github.resilience4j.circuitbreaker.CallNotPermittedException;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

import java.util.Map;

@RestControllerAdvice
public class GlobalExceptionHandler {

    /** CB is OPEN — short-circuit, return 503 so load generator counts it as failure. */
    @ExceptionHandler(CallNotPermittedException.class)
    public ResponseEntity<Map<String, String>> handleCbOpen(CallNotPermittedException ex) {
        return ResponseEntity.status(HttpStatus.SERVICE_UNAVAILABLE)
                .body(Map.of("error", "circuit_open", "breaker", ex.getCausingCircuitBreakerName()));
    }

    /** True downstream fault (5xx / timeout). Propagate as 503. */
    @ExceptionHandler(DownstreamUnavailableException.class)
    public ResponseEntity<Map<String, String>> handleUnavailable(DownstreamUnavailableException ex) {
        return ResponseEntity.status(HttpStatus.SERVICE_UNAVAILABLE)
                .body(Map.of("error", "downstream_unavailable", "detail", ex.getMessage()));
    }

    /** Business rejection from inventory (4xx). Re-surface with the downstream's status. */
    @ExceptionHandler(DownstreamRejectedException.class)
    public ResponseEntity<Map<String, String>> handleRejected(DownstreamRejectedException ex) {
        return ResponseEntity.status(ex.getStatus())
                .body(Map.of("error", "downstream_rejected", "detail", ex.getMessage()));
    }
}
