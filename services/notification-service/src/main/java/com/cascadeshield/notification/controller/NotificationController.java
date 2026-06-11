package com.cascadeshield.notification.controller;

import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.Map;

@RestController
@RequestMapping("/api/v1")
public class NotificationController {

    @GetMapping("/notification")
    public ResponseEntity<Map<String, Object>> notification() {
        return ResponseEntity.ok(Map.of("service", "notification-service", "status", "ok"));
    }
}
