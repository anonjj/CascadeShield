package com.cascadeshield.order.exception;

/** Raised when the A -> B call to Service B fails (timeout, 5xx, connection). */
public class InventoryUnavailableException extends RuntimeException {
    public InventoryUnavailableException(String sku, Throwable cause) {
        super("Inventory service unavailable while reserving SKU " + sku, cause);
    }
}
