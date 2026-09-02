package com.cascadeshield.common.client;

import com.cascadeshield.common.exception.DownstreamRejectedException;
import com.cascadeshield.common.exception.DownstreamUnavailableException;
import org.springframework.web.client.HttpClientErrorException;
import org.springframework.web.client.RestClientException;
import org.springframework.web.client.RestTemplate;

/**
 * Shared call+classify helper for outbound downstream calls, generalized from the pattern
 * every {@code *DownstreamService} class already followed independently: a GET via
 * RestTemplate, classified into DownstreamRejectedException (4xx -- a business rejection,
 * ignored by the caller's circuit breaker) or DownstreamUnavailableException (everything
 * else -- 5xx, timeout, connection refused -- counted by the CB).
 *
 * Deliberately does NOT carry {@code @CircuitBreaker} itself: resilience4j's AOP proxy wraps
 * the bean method the annotation is declared on, so putting it here would collapse every
 * downstream call in the mesh onto one CB instance, destroying the per-edge topology realism
 * (orderServiceCB, inventoryServiceCB, etc. staying distinct). Each *DownstreamService method
 * keeps its own @CircuitBreaker annotation and just delegates its body to {@link #get}.
 */
public class DownstreamCaller {
    private final RestTemplate restTemplate;

    public DownstreamCaller(RestTemplate restTemplate) {
        this.restTemplate = restTemplate;
    }

    public Object get(String url, String serviceName) {
        try {
            return restTemplate.getForObject(url, Object.class);
        } catch (HttpClientErrorException ex) {
            throw new DownstreamRejectedException(ex.getStatusCode(), ex.getResponseBodyAsString());
        } catch (RestClientException ex) {
            throw new DownstreamUnavailableException(serviceName + " unreachable", ex);
        }
    }
}
