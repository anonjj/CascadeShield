package com.cascadeshield.gateway.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestTemplate;

import java.util.List;

/**
 * Queries the /actuator/health endpoint of each downstream service (bypassing Toxiproxy
 * so we see the real CB state, not the injected fault) and computes blast radius as
 * the percentage of services with at least one OPEN circuit breaker.
 */
@Service
public class BlastRadiusService {

    private static final Logger log = LoggerFactory.getLogger(BlastRadiusService.class);

    // Direct container-name URLs — bypasses Toxiproxy to read true CB state
    private static final List<String> SERVICE_ACTUATOR_URLS = List.of(
        "http://order-service:8081",
        "http://inventory-service:8082",
        "http://payment-service:8083",
        "http://notification-service:8084",
        "http://shared-db-service:8085"
    );

    private final RestTemplate restTemplate;
    private final ObjectMapper objectMapper = new ObjectMapper();

    public BlastRadiusService(RestTemplate restTemplate) {
        this.restTemplate = restTemplate;
    }

    public double calculateBlastRadius() {
        int total = SERVICE_ACTUATOR_URLS.size();
        int degraded = 0;

        for (String baseUrl : SERVICE_ACTUATOR_URLS) {
            try {
                String json = restTemplate.getForObject(baseUrl + "/actuator/health", String.class);
                if (hasOpenCircuitBreaker(json)) {
                    degraded++;
                }
            } catch (Exception e) {
                // Unreachable service also counts as degraded
                log.warn("Could not reach actuator at {}: {}", baseUrl, e.getMessage());
                degraded++;
            }
        }

        return total > 0 ? (double) degraded / total * 100.0 : 0.0;
    }

    private boolean hasOpenCircuitBreaker(String healthJson) {
        if (healthJson == null) return false;
        try {
            JsonNode root = objectMapper.readTree(healthJson);
            JsonNode details = root.path("components").path("circuitBreakers").path("details");
            if (!details.isMissingNode() && details.isObject()) {
                for (JsonNode cbNode : details) {
                    if ("CIRCUIT_OPEN".equals(cbNode.path("status").asText(""))) {
                        return true;
                    }
                }
            }
        } catch (Exception e) {
            log.debug("Failed to parse health JSON: {}", e.getMessage());
        }
        return false;
    }
}
