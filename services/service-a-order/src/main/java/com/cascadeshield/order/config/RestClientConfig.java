package com.cascadeshield.order.config;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.web.client.RestClientCustomizer;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.web.client.RestClient;

import java.time.Duration;

/**
 * Builds the RestClient used to reach Service B.
 *
 * The base URL comes from configuration (services.inventory.base-url) so the
 * same jar can point at localhost, a Docker service name, or a Toxiproxy
 * sidecar without a rebuild — essential for the fault-injection sweeps.
 *
 * Connect/read timeouts are set explicitly: an unbounded client would hang
 * forever under a latency fault, which would make "time_to_open" unmeasurable.
 */
@Configuration
public class RestClientConfig {

    @Bean
    RestClient inventoryRestClient(
            RestClient.Builder builder,
            @Value("${services.inventory.base-url}") String inventoryBaseUrl,
            @Value("${services.inventory.connect-timeout-ms:1000}") long connectTimeoutMs,
            @Value("${services.inventory.read-timeout-ms:2000}") long readTimeoutMs) {

        var requestFactory = new SimpleClientHttpRequestFactory();
        requestFactory.setConnectTimeout(Duration.ofMillis(connectTimeoutMs));
        requestFactory.setReadTimeout(Duration.ofMillis(readTimeoutMs));

        return builder
                .baseUrl(inventoryBaseUrl)
                .requestFactory(requestFactory)
                .build();
    }
}
