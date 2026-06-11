package com.cascadeshield.shareddb.controller;

import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.Map;

@RestController
@RequestMapping("/api/v1")
public class SharedDbController {

    @GetMapping("/shared-db")
    public ResponseEntity<Map<String, Object>> query() {
        return ResponseEntity.ok(Map.of("service", "shared-db-service", "status", "ok"));
    }
}
