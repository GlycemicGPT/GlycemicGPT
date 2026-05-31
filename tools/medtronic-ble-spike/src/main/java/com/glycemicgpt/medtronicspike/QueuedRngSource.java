package com.glycemicgpt.medtronicspike;

import java.util.ArrayDeque;
import java.util.Arrays;
import java.util.Deque;
import org.openminimed.sake.RngSource;

/**
 * Deterministic {@link RngSource} that replays pre-queued byte arrays in order.
 *
 * <p>Used to drive a {@code SakeServer} through a captured packet trace by replaying the exact
 * random fields the original phone chose, so the harness re-emits the captured bytes. Shared by the
 * runnable harness and the spike tests.
 */
final class QueuedRngSource implements RngSource {

    private final Deque<byte[]> queue;

    QueuedRngSource(byte[]... values) {
        this.queue = new ArrayDeque<>(Arrays.asList(values));
    }

    @Override
    public byte[] nextBytes(int n) {
        byte[] next = queue.pollFirst();
        if (next == null || next.length != n) {
            throw new IllegalStateException(
                    "QueuedRngSource exhausted or size mismatch (asked for " + n + ")");
        }
        return next.clone();
    }
}
