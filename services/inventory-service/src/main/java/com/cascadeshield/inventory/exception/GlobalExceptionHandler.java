package com.cascadeshield.inventory.exception;

import io.github.resilience4j.circuitbreaker.CallNotPermittedException;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

import java.util.Map;

@RestControllerAdvice
public class GlobalExceptionHandler {

    @ExceptionHandler(CallNotPermittedException.class)
    public ResponseEntity<Map<String, String>> handleCbOpen(CallNotPermittedException ex) {
        return ResponseEntity.status(HttpStatus.SERVICE_UNAVAILABLE)
                .body(Map.of("error", "circuit_open", "breaker", ex.getCausingCircuitBreakerName()));
    }

    @ExceptionHandler(DownstreamUnavailableException.class)
    public ResponseEntity<Map<String, String>> handleUnavailable(DownstreamUnavailableException ex) {
        return ResponseEntity.status(HttpStatus.SERVICE_UNAVAILABLE)
                .body(Map.of("error", "downstream_unavailable", "detail", ex.getMessage()));
    }

    @ExceptionHandler(DownstreamRejectedException.class)
    public ResponseEntity<Map<String, String>> handleRejected(DownstreamRejectedException ex) {
        return ResponseEntity.status(ex.getStatus())
                .body(Map.of("error", "downstream_rejected", "detail", ex.getMessage()));
    }
}
