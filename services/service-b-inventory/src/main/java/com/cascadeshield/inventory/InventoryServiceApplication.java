package com.cascadeshield.inventory;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

/**
 * CascadeShield Service B — Inventory.
 *
 * Role in the mesh: downstream leaf on the Linear Chain (A -> B). It receives
 * calls from the Order service and owns stock levels. In later topologies it
 * will itself call Service C, but for Week 1 it makes no outbound calls.
 */
@SpringBootApplication
public class InventoryServiceApplication {
    public static void main(String[] args) {
        SpringApplication.run(InventoryServiceApplication.class, args);
    }
}
