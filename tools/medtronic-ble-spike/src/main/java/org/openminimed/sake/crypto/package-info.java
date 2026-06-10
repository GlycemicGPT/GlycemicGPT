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

/**
 * Thin AES primitive wrappers used by the SAKE handshake.
 *
 * <p>AES-ECB and AES-CTR are served by the JDK's JCE provider. AES-CMAC is implemented via
 * BouncyCastle as the JDK does not ship it.
 *
 * <p>AES-ECB is intentionally limited to single sixteen-byte operations on freshly random or
 * uniquely-derived inputs (the permit-block decrypt step and the session-key derivation step). It
 * is never used to encrypt multi-block or structured plaintext, where ECB's deterministic block
 * mapping would leak structure.
 */
package org.openminimed.sake.crypto;
