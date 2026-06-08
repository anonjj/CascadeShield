package com.cascadeshield.inventory.model;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Positive;

/** Incoming request from Service A asking to reserve stock for an order. */
public record ReserveRequest(
        @NotBlank(message = "sku must not be blank") String sku,
        @Positive(message = "quantity must be > 0") int quantity) {}
