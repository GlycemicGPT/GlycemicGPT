package com.glycemicgpt.mobile.data.remote

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Exhaustive coverage for the Story 57.1 transport policy. These are pure functions, so the
 * release path (`isDebug == false`) is testable directly here even though a `testDebug` run
 * compiles `BuildConfig.DEBUG == true`.
 */
class UrlSecurityPolicyTest {

    // ---- isPrivateHost: accepted ranges -----------------------------------------------------

    @Test
    fun `isPrivateHost accepts loopback IPv4`() {
        assertTrue(UrlSecurityPolicy.isPrivateHost("127.0.0.1"))
        assertTrue(UrlSecurityPolicy.isPrivateHost("127.1.2.3"))
        assertTrue(UrlSecurityPolicy.isPrivateHost("127.255.255.255"))
    }

    @Test
    fun `isPrivateHost accepts RFC1918 ranges`() {
        assertTrue(UrlSecurityPolicy.isPrivateHost("10.0.0.1"))
        assertTrue(UrlSecurityPolicy.isPrivateHost("10.255.255.255"))
        assertTrue(UrlSecurityPolicy.isPrivateHost("192.168.0.1"))
        assertTrue(UrlSecurityPolicy.isPrivateHost("192.168.255.255"))
        assertTrue(UrlSecurityPolicy.isPrivateHost("10.20.66.40"))
    }

    @Test
    fun `isPrivateHost accepts 172_16 through 172_31 and rejects the boundaries`() {
        assertTrue(UrlSecurityPolicy.isPrivateHost("172.16.0.1"))
        assertTrue(UrlSecurityPolicy.isPrivateHost("172.31.255.255"))
        assertTrue(UrlSecurityPolicy.isPrivateHost("172.20.1.1"))
        // Just outside 172.16.0.0/12.
        assertFalse(UrlSecurityPolicy.isPrivateHost("172.15.255.255"))
        assertFalse(UrlSecurityPolicy.isPrivateHost("172.32.0.0"))
    }

    @Test
    fun `isPrivateHost accepts CGNAT 100_64_0_0 slash 10 and rejects the boundaries`() {
        assertTrue(UrlSecurityPolicy.isPrivateHost("100.64.0.1"))
        assertTrue(UrlSecurityPolicy.isPrivateHost("100.127.255.255"))
        assertFalse(UrlSecurityPolicy.isPrivateHost("100.63.255.255"))
        assertFalse(UrlSecurityPolicy.isPrivateHost("100.128.0.0"))
    }

    @Test
    fun `isPrivateHost accepts link-local 169_254 and rejects the boundaries`() {
        assertTrue(UrlSecurityPolicy.isPrivateHost("169.254.0.1"))
        assertTrue(UrlSecurityPolicy.isPrivateHost("169.254.255.255"))
        assertFalse(UrlSecurityPolicy.isPrivateHost("169.253.0.1"))
        assertFalse(UrlSecurityPolicy.isPrivateHost("169.255.0.1"))
    }

    @Test
    fun `isPrivateHost accepts private IPv6`() {
        assertTrue(UrlSecurityPolicy.isPrivateHost("::1")) // loopback
        assertTrue(UrlSecurityPolicy.isPrivateHost("fe80::1")) // link-local
        assertTrue(UrlSecurityPolicy.isPrivateHost("fe80::a00:27ff:fe12:3456"))
        assertTrue(UrlSecurityPolicy.isPrivateHost("fc00::1")) // ULA
        assertTrue(UrlSecurityPolicy.isPrivateHost("fd12:3456:789a:1::1")) // ULA (fd = fc00::/7)
    }

    @Test
    fun `isPrivateHost classifies IPv4-mapped IPv6 by the embedded address`() {
        assertTrue(UrlSecurityPolicy.isPrivateHost("::ffff:10.0.0.1"))
        assertTrue(UrlSecurityPolicy.isPrivateHost("::ffff:192.168.1.1"))
        assertFalse(UrlSecurityPolicy.isPrivateHost("::ffff:8.8.8.8"))
    }

    @Test
    fun `isPrivateHost accepts dotlocal hostnames case-insensitively`() {
        assertTrue(UrlSecurityPolicy.isPrivateHost("nas.local"))
        assertTrue(UrlSecurityPolicy.isPrivateHost("My-Server.LOCAL"))
        assertTrue(UrlSecurityPolicy.isPrivateHost("glycemicgpt.local"))
        // Trailing FQDN dot is tolerated.
        assertTrue(UrlSecurityPolicy.isPrivateHost("nas.local."))
    }

    // ---- isPrivateHost: rejected ------------------------------------------------------------

    @Test
    fun `isPrivateHost rejects public IPv4`() {
        assertFalse(UrlSecurityPolicy.isPrivateHost("8.8.8.8"))
        assertFalse(UrlSecurityPolicy.isPrivateHost("1.1.1.1"))
        assertFalse(UrlSecurityPolicy.isPrivateHost("11.0.0.1"))
        assertFalse(UrlSecurityPolicy.isPrivateHost("192.169.0.1"))
        assertFalse(UrlSecurityPolicy.isPrivateHost("0.0.0.0"))
    }

    @Test
    fun `isPrivateHost rejects public and reserved IPv6`() {
        assertFalse(UrlSecurityPolicy.isPrivateHost("2001:db8::1"))
        assertFalse(UrlSecurityPolicy.isPrivateHost("2606:4700:4700::1111"))
        assertFalse(UrlSecurityPolicy.isPrivateHost("fe00::1")) // not fe80::/10
        assertFalse(UrlSecurityPolicy.isPrivateHost("fec0::1")) // deprecated site-local, not fc00::/7
    }

    @Test
    fun `isPrivateHost rejects malformed IPv6 literals`() {
        assertFalse(UrlSecurityPolicy.isPrivateHost("fe80:::1")) // triple colon
        assertFalse(UrlSecurityPolicy.isPrivateHost("fc00::1::2")) // two "::"
        assertFalse(UrlSecurityPolicy.isPrivateHost("gggg::1")) // non-hex hextet
        assertFalse(UrlSecurityPolicy.isPrivateHost("-100::")) // sign-prefixed hextet
        assertFalse(UrlSecurityPolicy.isPrivateHost("fc00::+1")) // sign-prefixed hextet
        assertFalse(UrlSecurityPolicy.isPrivateHost("12345::1")) // hextet too long
    }

    @Test
    fun `isPrivateHost rejects hostnames that are not dotlocal`() {
        assertFalse(UrlSecurityPolicy.isPrivateHost("example.com"))
        assertFalse(UrlSecurityPolicy.isPrivateHost("localhost")) // a name, not a literal IP
        assertFalse(UrlSecurityPolicy.isPrivateHost("local")) // no label before .local
        assertFalse(UrlSecurityPolicy.isPrivateHost(".local"))
        assertFalse(UrlSecurityPolicy.isPrivateHost("notlocal"))
        assertFalse(UrlSecurityPolicy.isPrivateHost("evil.local.attacker.com"))
        assertFalse(UrlSecurityPolicy.isPrivateHost(""))
    }

    @Test
    fun `isPrivateHost rejects non-canonical IPv4 encodings (spoofing)`() {
        assertFalse(UrlSecurityPolicy.isPrivateHost("0x0a000001")) // hex 10.0.0.1
        assertFalse(UrlSecurityPolicy.isPrivateHost("012.0.0.1")) // octal-looking leading zero
        assertFalse(UrlSecurityPolicy.isPrivateHost("2130706433")) // decimal 127.0.0.1
        assertFalse(UrlSecurityPolicy.isPrivateHost("10.0.0.256")) // octet overflow
        assertFalse(UrlSecurityPolicy.isPrivateHost("10.0.0")) // too few octets
        assertFalse(UrlSecurityPolicy.isPrivateHost("10.0.0.1.5")) // too many octets
        assertFalse(UrlSecurityPolicy.isPrivateHost("10.0.0.-1")) // signs are not digits
        assertFalse(UrlSecurityPolicy.isPrivateHost("10.0.0.1@evil.com")) // authority, not a host
    }

    // ---- isAllowed: https always allowed ----------------------------------------------------

    @Test
    fun `isAllowed always accepts https regardless of debug or toggle or host`() {
        for (debug in listOf(true, false)) {
            for (allow in listOf(true, false)) {
                assertTrue(UrlSecurityPolicy.isAllowed("https://example.com", debug, allow))
                assertTrue(UrlSecurityPolicy.isAllowed("https://8.8.8.8", debug, allow))
                assertTrue(UrlSecurityPolicy.isAllowed("https://10.0.0.1", debug, allow))
            }
        }
    }

    // ---- isAllowed: http public is always rejected in release -------------------------------

    @Test
    fun `isAllowed rejects http to a public host in release even with the toggle on`() {
        assertFalse(UrlSecurityPolicy.isAllowed("http://example.com", isDebug = false, allowInsecureLanHttp = true))
        assertFalse(UrlSecurityPolicy.isAllowed("http://8.8.8.8", isDebug = false, allowInsecureLanHttp = true))
        assertFalse(UrlSecurityPolicy.isAllowed("http://1.1.1.1:8080", isDebug = false, allowInsecureLanHttp = true))
    }

    // ---- isAllowed: http private gated by the toggle in release -----------------------------

    @Test
    fun `isAllowed accepts http to a private host in release only when the toggle is on`() {
        assertFalse(UrlSecurityPolicy.isAllowed("http://10.20.66.40:3000", isDebug = false, allowInsecureLanHttp = false))
        assertTrue(UrlSecurityPolicy.isAllowed("http://10.20.66.40:3000", isDebug = false, allowInsecureLanHttp = true))
        assertTrue(UrlSecurityPolicy.isAllowed("http://192.168.1.5", isDebug = false, allowInsecureLanHttp = true))
        assertTrue(UrlSecurityPolicy.isAllowed("http://127.0.0.1:8000", isDebug = false, allowInsecureLanHttp = true))
        assertTrue(UrlSecurityPolicy.isAllowed("http://nas.local", isDebug = false, allowInsecureLanHttp = true))
    }

    // ---- isAllowed: debug permits any http (unchanged) --------------------------------------

    @Test
    fun `isAllowed permits any http in a debug build regardless of the toggle`() {
        assertTrue(UrlSecurityPolicy.isAllowed("http://example.com", isDebug = true, allowInsecureLanHttp = false))
        assertTrue(UrlSecurityPolicy.isAllowed("http://8.8.8.8", isDebug = true, allowInsecureLanHttp = false))
        assertTrue(UrlSecurityPolicy.isAllowed("http://10.0.0.1", isDebug = true, allowInsecureLanHttp = false))
    }

    // ---- isAllowed: OkHttp-level spoofing / parsing -----------------------------------------

    @Test
    fun `isAllowed rejects a userinfo-spoofed authority (host resolves to the public part)`() {
        // OkHttp parses "10.0.0.1" as userinfo and "evil.com" as the host.
        assertFalse(
            UrlSecurityPolicy.isAllowed("http://10.0.0.1@evil.com", isDebug = false, allowInsecureLanHttp = true),
        )
    }

    @Test
    fun `isAllowed accepts a bracketed private IPv6 and rejects a bracketed public IPv6`() {
        assertTrue(UrlSecurityPolicy.isAllowed("http://[::1]:3000", isDebug = false, allowInsecureLanHttp = true))
        assertTrue(UrlSecurityPolicy.isAllowed("http://[fe80::1]", isDebug = false, allowInsecureLanHttp = true))
        assertFalse(UrlSecurityPolicy.isAllowed("http://[2001:db8::1]", isDebug = false, allowInsecureLanHttp = true))
    }

    @Test
    fun `isAllowed rejects malformed URLs and non-http schemes`() {
        assertFalse(UrlSecurityPolicy.isAllowed("not-a-url", isDebug = true, allowInsecureLanHttp = true))
        assertFalse(UrlSecurityPolicy.isAllowed("", isDebug = true, allowInsecureLanHttp = true))
        assertFalse(UrlSecurityPolicy.isAllowed("ftp://10.0.0.1", isDebug = true, allowInsecureLanHttp = true))
    }

    // ---- isBlockedPendingLanOptIn -----------------------------------------------------------

    @Test
    fun `isBlockedPendingLanOptIn is true only for release http to a private host`() {
        assertTrue(UrlSecurityPolicy.isBlockedPendingLanOptIn("http://10.20.66.40:3000", isDebug = false))
        assertTrue(UrlSecurityPolicy.isBlockedPendingLanOptIn("http://nas.local", isDebug = false))
        // Public http -> enabling the toggle would not help.
        assertFalse(UrlSecurityPolicy.isBlockedPendingLanOptIn("http://example.com", isDebug = false))
        // https already works.
        assertFalse(UrlSecurityPolicy.isBlockedPendingLanOptIn("https://10.0.0.1", isDebug = false))
        // Debug already permits it, so no opt-in prompt.
        assertFalse(UrlSecurityPolicy.isBlockedPendingLanOptIn("http://10.0.0.1", isDebug = true))
    }

    @Test
    fun `INVALID_URL_MESSAGE names the LAN exception`() {
        assertTrue(UrlSecurityPolicy.INVALID_URL_MESSAGE.contains("https://"))
        assertTrue(UrlSecurityPolicy.INVALID_URL_MESSAGE.contains("http://"))
    }
}
