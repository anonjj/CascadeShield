package com.cascadeshield.order.model;

/** Payload Service A sends to Service B's POST /inventory/reserve. */
public record ReserveRequest(String sku, int quantity) {}
