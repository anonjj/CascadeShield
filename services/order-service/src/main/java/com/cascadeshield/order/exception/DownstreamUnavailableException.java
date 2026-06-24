package com.cascadeshield.order.exception;

/**
 * Thrown when the inventory hop fails with a true infrastructure fault:
 * 5xx, read-timeout, or connection-refused. This is the ONLY exception
 * that inventoryServiceCB should count toward the failure rate.
 *
 * A 4xx business rejection (InventoryRejectedException) is explicitly
 * listed in ignore-exceptions on inventoryServiceCB so it never trips
 * the breaker — keeping business rejections out of blast-radius numbers.
 */
public class DownstreamUnavailableException extends RuntimeException {
    public DownstreamUnavailableException(String msg, Throwable cause) {
        super(msg, cause);
    }
}
