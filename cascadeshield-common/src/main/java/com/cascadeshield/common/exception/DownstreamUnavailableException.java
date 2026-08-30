package com.cascadeshield.common.exception;

/**
 * Thrown when a downstream call fails with a true infrastructure fault: 5xx,
 * read-timeout, or connection-refused. This is the exception the caller's circuit
 * breaker SHOULD count toward its failure rate.
 *
 * A 4xx business rejection (DownstreamRejectedException) is explicitly listed in
 * ignore-exceptions on every CB instance so it never trips the breaker -- keeping
 * business rejections out of blast-radius numbers.
 */
public class DownstreamUnavailableException extends RuntimeException {
    public DownstreamUnavailableException(String msg, Throwable cause) {
        super(msg, cause);
    }
}
