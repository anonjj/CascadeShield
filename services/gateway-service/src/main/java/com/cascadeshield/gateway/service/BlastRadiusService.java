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

    // Direct container-name URLs — bypasses Toxiproxy to read true CB state.
    // Subject set = the four CB-bearing downstream services. shared-db-service is a leaf
    // with no outbound calls and zero @CircuitBreaker annotations, so it can never have an
    // open breaker and would only dilute the denominator; it is excluded. The gateway is
    // also excluded here (it is the measurement plane, not an experimental subject) — this
    // matches runner.py's CB_METRIC_TARGETS so both metrics range over the same 4 nodes.
    // Blast radius therefore takes values in {0, 0.25, 0.5, 0.75, 1.0} (x100 here).
    private static final List<String> SERVICE_ACTUATOR_URLS = List.of(
        "http://order-service:8081",
        "http://inventory-service:8082",
        "http://payment-service:8083",
        "http://notification-service:8084"
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
