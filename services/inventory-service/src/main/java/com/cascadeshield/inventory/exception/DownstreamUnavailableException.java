package com.cascadeshield.inventory.exception;

public class DownstreamUnavailableException extends RuntimeException {
    public DownstreamUnavailableException(String msg, Throwable cause) {
        super(msg, cause);
    }
}
