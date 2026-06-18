package com.cascadeshield.payment.controller;

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
        boolean failed = false;

        try {
            Object notifResult = downstreamService.callNotification();
            body.put("notification", notifResult != null ? notifResult : "ok");
        } catch (Exception e) {
            body.put("notification", Map.of("error", "unavailable", "cause", e.getClass().getSimpleName()));
            failed = true;
        }

        try {
            Object dbResult = downstreamService.callSharedDb();
            body.put("sharedDb", dbResult != null ? dbResult : "ok");
        } catch (Exception e) {
            body.put("sharedDb", Map.of("error", "unavailable", "cause", e.getClass().getSimpleName()));
            failed = true;
        }

        return failed ? ResponseEntity.status(503).body(body) : ResponseEntity.ok(body);
    }
}
