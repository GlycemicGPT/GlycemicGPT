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
 * Base class for {@link SakeServer} and {@link SakeClient}: tracks the handshake stage.
 *
 * <p>Stage progression for a server: 0 → 1 → 3 → 5 → 6.
 *
 * <p>Stage progression for a client: 0 → 2 → 4 → 6.
 */
public abstract class Peer {

    private int stage = 0;

    public final int getStage() {
        return stage;
    }

    protected final void incrementStage() {
        stage++;
    }
}
