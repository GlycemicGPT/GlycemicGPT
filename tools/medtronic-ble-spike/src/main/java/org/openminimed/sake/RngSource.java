/*
 * Vendored from OpenMinimed JavaSake (https://github.com/OpenMinimed/JavaSake)
 * at commit 00c08ae -- verbatim except for this header (verified byte-identical).
 *
 * Copyright (C) OpenMinimed contributors: palmarci (Pal Marci), drfubar,
 * Morten Fyhn Amundsen, Stenium. Original medtronic-bt-decrypt PoC by @planiitis.
 * Android/JVM port maintained by jlengelbrecht.
 *
 * This file is part of GlycemicGPT and is redistributed under the GNU General
 * Public License v3.0, the license under which OpenMinimed makes it available
 * and under which GlycemicGPT itself is released. Used with the author's
 * permission. See tools/medtronic-ble-spike/LICENSE and README.md.
 *
 * Only this attribution header was added; the file is otherwise byte-identical to
 * the pinned upstream commit (applies to vendored main sources and tests alike).
 * Re-vendor from upstream rather than editing here if it drifts.
 */

package org.openminimed.sake;

/**
 * Source of random bytes used to populate handshake fields the server / client are expected to
 * choose freshly per session.
 *
 * <p>Production implementations should be backed by {@link java.security.SecureRandom}; see {@link
 * SecureRandomRngSource}. Tests can substitute a deterministic source to drive a server or client
 * against a captured packet trace.
 */
public interface RngSource {

    /**
     * @param n the number of bytes to return. Must be non-negative.
     * @return a freshly allocated array of {@code n} random bytes.
     */
    byte[] nextBytes(int n);
}
