package com.cascadeshield.order.model;

/** Payload Service B returns from POST /inventory/reserve. */
public record ReserveResponse(String sku, int reserved, int remaining) {}
