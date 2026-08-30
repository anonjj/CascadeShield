package com.cascadeshield.common.exception;

import io.github.resilience4j.circuitbreaker.CallNotPermittedException;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

import java.util.Map;

/**
 * Defensive fallback, not the primary error path: every controller in this codebase
 * (Order/Inventory/Payment/Notification's single-endpoint handlers, and Gateway's
 * linear() -- see its own catch block) already catches DownstreamRejectedException/
 * DownstreamUnavailableException/CallNotPermittedException locally, per-downstream-call,
 * so it can report a per-leg breakdown (and, for Order/Inventory/Payment, merge multiple
 * downstream outcomes into one worst-status response) -- this advice normally never
 * fires for those endpoints. It exists so an exception that manages to escape local
 * handling (a future endpoint that forgets to catch, or a call site added without
 * updating its try/catch) still gets a sensible status code instead of Spring's default
 * 500, rather than as the thing that currently classifies these exceptions in practice.
 */
@RestControllerAdvice
public class GlobalExceptionHandler {

    /** CB is OPEN -- short-circuit, return 503 so load generator counts it as failure. */
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

    /** Business rejection from a downstream call (4xx). Re-surface with its real status. */
    @ExceptionHandler(DownstreamRejectedException.class)
    public ResponseEntity<Map<String, String>> handleRejected(DownstreamRejectedException ex) {
        return ResponseEntity.status(ex.getStatus())
                .body(Map.of("error", "downstream_rejected", "detail", ex.getMessage()));
    }
}
