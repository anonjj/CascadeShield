package com.cascadeshield.notification.exception;

public class DownstreamUnavailableException extends RuntimeException {
    public DownstreamUnavailableException(String msg, Throwable cause) {
        super(msg, cause);
    }
}
