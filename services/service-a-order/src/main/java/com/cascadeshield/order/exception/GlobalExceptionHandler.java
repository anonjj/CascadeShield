package com.cascadeshield.order.exception;

import org.springframework.http.HttpStatus;
import org.springframework.http.ProblemDetail;
// InventoryRejectedException + InventoryUnavailableException are in this package
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

/**
 * Maps Service A failures to deterministic HTTP statuses. A downstream
 * outage becomes 503 (SERVICE_UNAVAILABLE) — this is the response the
 * experiment harness will treat as part of the blast radius when Service B
 * is faulted and no circuit breaker is protecting the call yet.
 */
@RestControllerAdvice
public class GlobalExceptionHandler {

    @ExceptionHandler(InventoryUnavailableException.class)
    public ProblemDetail handleInventoryDown(InventoryUnavailableException ex) {
        return ProblemDetail.forStatusAndDetail(HttpStatus.SERVICE_UNAVAILABLE, ex.getMessage());
    }

    @ExceptionHandler(InventoryRejectedException.class)
    public ProblemDetail handleInventoryRejected(InventoryRejectedException ex) {
        // Mirror Service B's business status (e.g. 409, 404) instead of masking it.
        return ProblemDetail.forStatusAndDetail(ex.getStatus(), ex.getMessage());
    }

    @ExceptionHandler(MethodArgumentNotValidException.class)
    public ProblemDetail handleValidation(MethodArgumentNotValidException ex) {
        String detail = ex.getBindingResult().getFieldErrors().stream()
                .map(f -> f.getField() + ": " + f.getDefaultMessage())
                .findFirst()
                .orElse("Invalid request");
        return ProblemDetail.forStatusAndDetail(HttpStatus.BAD_REQUEST, detail);
    }
}
