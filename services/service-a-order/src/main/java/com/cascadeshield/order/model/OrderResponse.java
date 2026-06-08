package com.cascadeshield.order.model;

/** Result returned to the caller once inventory has been reserved. */
public record OrderResponse(String orderId, String sku, int quantity, String status) {}
