package com.cascadeshield.inventory.exception;

/** Thrown when a requested SKU does not exist in the catalogue. */
public class SkuNotFoundException extends RuntimeException {
    public SkuNotFoundException(String sku) {
        super("Unknown SKU: " + sku);
    }
}
