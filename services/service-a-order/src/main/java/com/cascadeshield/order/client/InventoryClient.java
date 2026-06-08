package com.cascadeshield.order.client;

import com.cascadeshield.order.exception.InventoryRejectedException;
import com.cascadeshield.order.exception.InventoryUnavailableException;
import com.cascadeshield.order.model.ReserveRequest;
import com.cascadeshield.order.model.ReserveResponse;
import org.springframework.stereotype.Component;
import org.springframework.web.client.HttpClientErrorException;
import org.springframework.web.client.RestClient;
import org.springframework.web.client.RestClientException;

/**
 * Wraps every outbound call to Service B. Keeping the network hop behind this
 * single seam is the whole point: in Week 2 the reserve() method gets a
 * @CircuitBreaker(name = "inventory") annotation and a fallback, and nothing
 * else in Service A has to change.
 *
 * The catch blocks below encode a distinction that is critical for the study:
 *   - 4xx  -> a business rejection. Propagated with B's own status. The circuit
 *            breaker must NOT count these, or business 409s would inflate the
 *            measured blast radius.
 *   - 5xx / timeout / connection failure -> a true downstream fault. This is the
 *            only signal the circuit breaker should ever trip on.
 */
@Component
public class InventoryClient {

    private final RestClient inventoryRestClient;

    public InventoryClient(RestClient inventoryRestClient) {
        this.inventoryRestClient = inventoryRestClient;
    }

    public ReserveResponse reserve(String sku, int quantity) {
        try {
            return inventoryRestClient.post()
                    .uri("/inventory/reserve")
                    .body(new ReserveRequest(sku, quantity))
                    .retrieve()
                    .body(ReserveResponse.class);

        } catch (HttpClientErrorException ex) {
            // 4xx from Service B: a deliberate business response, not a fault.
            throw new InventoryRejectedException(ex.getStatusCode(), ex.getResponseBodyAsString());

        } catch (RestClientException ex) {
            // 5xx, read timeout, or connection refused: a genuine downstream
            // failure. HttpServerErrorException and ResourceAccessException
            // (timeouts/refused) are both RestClientException subtypes, so they
            // land here — this is the only path the circuit breaker should trip on.
            throw new InventoryUnavailableException(sku, ex);
        }
    }
}
