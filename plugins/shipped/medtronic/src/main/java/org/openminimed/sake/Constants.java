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

import java.util.Collections;
import java.util.List;

/**
 * Pre-baked key databases used by SAKE peers.
 *
 * <p>These are the three databases shipped with the reference Python implementation in {@code
 * pysake/constants.py}. The hex strings are reproduced verbatim and parsed at class-init time.
 *
 * <p>The byte sequences here are <em>shared</em> SAKE protocol constants extracted from pump
 * firmware: a real 780-series pump contains the same values internally and uses them to
 * authenticate any phone-side application it pairs with. They are not session secrets and they are
 * not unique per device, so embedding them in source is correct (and necessary; the protocol is not
 * negotiable without them).
 */
public final class Constants {

    /** Glucose sensor (G4 family) key database. Display-side. */
    public static final KeyDatabase KEYDB_G4_CGM =
            parse(
                    "5fe5928308010230f0b50df613f2e429c8c5e8713854add1a69b837235a3e974"
                            + "304d8055ccb397838b90823c73236d6a83dcc9db3a2a939ff16145ca4169ef93"
                            + "a7fa39b20962b05e57413bff8b3d61fce0dfef2c43b326");

    /** Insulin pump database recovered from real pump firmware. Mobile-app-side. */
    public static final KeyDatabase KEYDB_PUMP_EXTRACTED =
            parse(
                    "f75995e70401011bc1bf7cbf36fa1e2367d795ff09211903da6afbe986b650f1"
                            + "4179c0e6852e0ce393781078ffc6f51919e2eaefbde69b8eca21e41ab59b881a"
                            + "0bea0286ea91dc7582a86a714e1737f558f0d66dc1895c");

    /** Insulin pump database with hard-coded test keys. Mobile-app-side. */
    public static final KeyDatabase KEYDB_PUMP_HARDCODED =
            parse(
                    "c2cdfdd1040101fce36ed66ef21def3b0763975494b239038ebe8606f79a9bf0"
                            + "0d9f11b6db04c7c0434787cbf00d5476289c22288e2105ae40e01391837f9476"
                            + "fa5003895c5a1afe35662a2a6211826af016eebe30e4ba");

    /** Databases available for production handshakes. */
    public static final List<KeyDatabase> AVAILABLE_KEYS =
            Collections.unmodifiableList(
                    java.util.Arrays.asList(
                            KEYDB_G4_CGM, KEYDB_PUMP_EXTRACTED, KEYDB_PUMP_HARDCODED));

    private Constants() {}

    private static KeyDatabase parse(String hex) {
        return KeyDatabase.fromBytes(decode(hex));
    }

    private static byte[] decode(String hex) {
        if ((hex.length() & 1) != 0) {
            throw new IllegalArgumentException("Hex string has odd length");
        }
        byte[] out = new byte[hex.length() / 2];
        for (int i = 0; i < out.length; i++) {
            int high = Character.digit(hex.charAt(2 * i), 16);
            int low = Character.digit(hex.charAt(2 * i + 1), 16);
            if (high < 0 || low < 0) {
                throw new IllegalArgumentException("Invalid hex character");
            }
            out[i] = (byte) ((high << 4) | low);
        }
        return out;
    }
}
