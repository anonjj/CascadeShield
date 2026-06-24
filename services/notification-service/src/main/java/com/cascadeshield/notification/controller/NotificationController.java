package com.cascadeshield.notification.controller;

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
        boolean failed = false;

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
