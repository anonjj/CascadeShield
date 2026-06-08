package com.cascadeshield.order.model;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Positive;

/** Inbound order placed by a client (or the Gateway). */
public record OrderRequest(
        @NotBlank(message = "sku must not be blank") String sku,
        @Positive(message = "quantity must be > 0") int quantity) {}
