package com.cascadeshield.payment.controller;

import com.cascadeshield.payment.exception.DownstreamRejectedException;
import com.cascadeshield.payment.exception.DownstreamUnavailableException;
import com.cascadeshield.payment.service.PaymentDownstreamService;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.LinkedHashMap;
import java.util.Map;

@RestController
@RequestMapping("/api/v1")
public class PaymentController {

    private final PaymentDownstreamService downstreamService;

    public PaymentController(PaymentDownstreamService downstreamService) {
        this.downstreamService = downstreamService;
    }

    @GetMapping("/payment")
    public ResponseEntity<Map<String, Object>> payment() {
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("service", "payment-service");
        org.springframework.http.HttpStatusCode worst = org.springframework.http.HttpStatus.OK;

        try {
            Object notifResult = downstreamService.callNotification();
            body.put("notification", notifResult != null ? notifResult : "ok");
        } catch (DownstreamRejectedException e) {
            body.put("notification", Map.of("error", "rejected", "status", e.getStatus().value()));
            worst = worse(worst, e.getStatus());
        } catch (io.github.resilience4j.circuitbreaker.CallNotPermittedException
                | DownstreamUnavailableException e) {
            body.put("notification", Map.of("error", "unavailable", "cause", e.getClass().getSimpleName()));
            worst = worse(worst, org.springframework.http.HttpStatus.SERVICE_UNAVAILABLE);
        }

        try {
            Object dbResult = downstreamService.callSharedDb();
            body.put("sharedDb", dbResult != null ? dbResult : "ok");
        } catch (DownstreamRejectedException e) {
            body.put("sharedDb", Map.of("error", "rejected", "status", e.getStatus().value()));
            worst = worse(worst, e.getStatus());
        } catch (io.github.resilience4j.circuitbreaker.CallNotPermittedException
                | DownstreamUnavailableException e) {
            body.put("sharedDb", Map.of("error", "unavailable", "cause", e.getClass().getSimpleName()));
            worst = worse(worst, org.springframework.http.HttpStatus.SERVICE_UNAVAILABLE);
        }

        return ResponseEntity.status(worst).body(body);
    }

    private static org.springframework.http.HttpStatusCode worse(
            org.springframework.http.HttpStatusCode a,
            org.springframework.http.HttpStatusCode b) {
        return b.value() > a.value() ? b : a;
    }
}
