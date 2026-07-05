package com.cascadeshield.notification.controller;

import com.cascadeshield.notification.exception.DownstreamRejectedException;
import com.cascadeshield.notification.exception.DownstreamUnavailableException;
import com.cascadeshield.notification.service.NotificationDownstreamService;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.LinkedHashMap;
import java.util.Map;

@RestController
@RequestMapping("/api/v1")
public class NotificationController {

    private final NotificationDownstreamService downstreamService;

    public NotificationController(NotificationDownstreamService downstreamService) {
        this.downstreamService = downstreamService;
    }

    @GetMapping("/notification")
    public ResponseEntity<Map<String, Object>> notification() {
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("service", "notification-service");
        org.springframework.http.HttpStatusCode worst = org.springframework.http.HttpStatus.OK;

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
