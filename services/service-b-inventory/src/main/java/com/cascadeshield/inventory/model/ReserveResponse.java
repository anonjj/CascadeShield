package com.cascadeshield.inventory.model;

/** Result of a reservation: what was reserved and what remains. */
public record ReserveResponse(String sku, int reserved, int remaining) {}
