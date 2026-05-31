package com.glycemicgpt.medtronicspike;

import java.util.ArrayDeque;
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
        // Snapshot each entry so later mutation of the caller's arrays can't change RNG output
        // and silently break trace parity.
        this.queue = new ArrayDeque<>(values.length);
        for (byte[] value : values) {
            this.queue.addLast(value.clone());
        }
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
