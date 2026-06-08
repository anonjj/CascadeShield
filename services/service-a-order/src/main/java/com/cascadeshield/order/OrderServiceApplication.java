package com.cascadeshield.order;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

/**
 * CascadeShield Service A — Order.
 *
 * Role in the mesh: upstream entry of the Linear Chain (A -> B). It accepts
 * order requests and calls the Inventory service (Service B) to reserve stock.
 * The A -> B call is the first hop we will wrap with a Resilience4j circuit
 * breaker in Week 2, so it is deliberately isolated in InventoryClient.
 */
@SpringBootApplication
public class OrderServiceApplication {
    public static void main(String[] args) {
        SpringApplication.run(OrderServiceApplication.class, args);
    }
}
