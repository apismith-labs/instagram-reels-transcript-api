package com.apismith.instagram.transcriptapi;

import java.io.IOException;
import java.time.Duration;
import java.util.Map;

/** A single-shot transport. Implementations must never redirect or replay POST requests. */
public interface Transport {
    TransportResponse send(String method, String path, Object body, Map<String, String> query, Duration timeout)
            throws IOException, InterruptedException;
    /** Custom transports must explicitly opt in to the no-redirect/no-replay contract. */
    default boolean guaranteesSingleShotPost() { return false; }
}
