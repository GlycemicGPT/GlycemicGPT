package com.glycemicgpt.mobile.data.remote

import okhttp3.HttpUrl.Companion.toHttpUrlOrNull

/**
 * Single source of truth for whether a server base URL is allowed as a transport target.
 *
 * The release build permits cleartext at the platform layer (`network_security_config`
 * `cleartextTrafficPermitted="true"`) so a self-hoster can reach a LAN box over `http://`.
 * Because network-security-config matches exact hosts and cannot express CIDR ranges, the
 * "private-only" rule lives here instead: this object is the *sole* guard that keeps a
 * public host from being reached over plaintext.
 *
 * Policy:
 * - `https` -> always allowed.
 * - `http`  -> allowed only when [isDebug] (dev convenience, unchanged) OR the user has
 *   opted in ([allowInsecureLanHttp]) AND the host is a private/LAN literal ([isPrivateHost]).
 * - anything else -> rejected.
 *
 * [isPrivateHost] classifies the URL host as a **literal IP** (or the `.local` mDNS suffix) and
 * **never performs a DNS lookup** -- resolving a name to decide "is it private" would invite
 * DNS-rebinding (a public name pointing at a private IP, or vice-versa) and block the caller's
 * thread. Everything here is pure and side-effect-free so it is exhaustively unit-testable on the
 * JVM (including the `isDebug == false` release path, which `BuildConfig.DEBUG` cannot express in a
 * `testDebug` run).
 */
object UrlSecurityPolicy {

    /**
     * Shared rejection message for a URL that fails [isAllowed]. Names the LAN exception so the
     * three call sites (onboarding test, settings save, login) stay consistent.
     */
    const val INVALID_URL_MESSAGE =
        "Invalid server URL. Use https://, or enable insecure LAN HTTP to reach a " +
            "private/LAN address over http://."

    /** True if [url] is an acceptable transport target under the policy described above. */
    fun isAllowed(url: String, isDebug: Boolean, allowInsecureLanHttp: Boolean): Boolean {
        val parsed = url.toHttpUrlOrNull() ?: return false
        return when (parsed.scheme) {
            "https" -> true
            "http" -> isDebug || (allowInsecureLanHttp && isPrivateHost(parsed.host))
            else -> false
        }
    }

    /**
     * True when [url] would be rejected today but *would* be accepted if insecure LAN HTTP were
     * enabled -- i.e. it is `http://` to a private host. Lets the UI offer a one-tap opt-in instead
     * of a dead end. In a debug build this is false (debug already permits the URL).
     */
    fun isBlockedPendingLanOptIn(url: String, isDebug: Boolean): Boolean {
        if (isDebug) return false
        val parsed = url.toHttpUrlOrNull() ?: return false
        return parsed.scheme == "http" && isPrivateHost(parsed.host)
    }

    /**
     * True when [url] would actually be sent as cleartext -- the scheme is `http` AND [isAllowed]
     * permits it. Drives the insecure-mode indicator so it reflects real cleartext traffic rather
     * than a bare `http://` prefix (a public `http://` URL the request layer rejects must not light
     * the banner).
     */
    fun isActiveInsecureHttp(url: String, isDebug: Boolean, allowInsecureLanHttp: Boolean): Boolean {
        val parsed = url.toHttpUrlOrNull() ?: return false
        return parsed.scheme == "http" && isAllowed(url, isDebug, allowInsecureLanHttp)
    }

    /**
     * Classify [host] (an OkHttp-canonicalized URL host: no brackets, no port, lowercased) as a
     * private/LAN destination. Accepts, by literal-IP inspection only:
     * - loopback `127.0.0.0/8`, `::1`
     * - RFC1918 `10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`
     * - CGNAT `100.64.0.0/10`
     * - link-local `169.254.0.0/16`, `fe80::/10`
     * - IPv6 ULA `fc00::/7`
     * - hostnames ending in `.local` (mDNS)
     *
     * Rejects everything else. Non-canonical IPv4 encodings (octal `012.0.0.1`, hex `0x0a000001`,
     * bare-decimal `2130706433`) do not parse as a literal IPv4 here and are rejected; a
     * userinfo-spoofed authority like `10.0.0.1@evil.com` never reaches this function as a private
     * host because OkHttp resolves its host to `evil.com`.
     */
    fun isPrivateHost(host: String): Boolean {
        if (host.isEmpty()) return false
        // Defensive: strip IPv6 brackets and a single trailing FQDN dot in case a raw host is
        // passed (OkHttp already removes both, but callers/tests may not).
        var h = host
        if (h.startsWith("[") && h.endsWith("]")) h = h.substring(1, h.length - 1)
        if (h.endsWith(".")) h = h.dropLast(1)
        if (h.isEmpty()) return false

        // mDNS names (RFC 6762). This is the ONE deliberate name-based exception to the
        // literal-IP rule: a `.local` name is resolved at connect time, not by us, so unlike an IP
        // literal we cannot prove the connect target is private. The residual risk is bounded and
        // accepted: (a) `.local` resolution is multicast on the local link, so an attacker able to
        // answer it is already on the LAN the user explicitly opted into (and could MITM a
        // private-IP connection just the same); (b) Android does not fall back to unicast DNS for
        // `.local` by default, and search-domain appending does not apply to a name already ending
        // in `.local`. Require a label before `.local` so a bare `.local` is rejected.
        if (h.length > LOCAL_SUFFIX.length && h.endsWith(LOCAL_SUFFIX, ignoreCase = true)) {
            return true
        }

        parseStrictIpv4(h)?.let { return isPrivateIpv4(it[0], it[1]) }

        if (h.contains(':')) {
            parseIpv6ToBytes(h)?.let { return isPrivateIpv6(it) }
        }
        return false
    }

    private const val LOCAL_SUFFIX = ".local"

    // ---- IPv4 -------------------------------------------------------------------------------

    /**
     * Parse a strict canonical dotted-decimal IPv4 (four base-10 octets, no leading zeros, each
     * 0..255) into its octets, or null if [host] is not exactly that form. The strictness is
     * deliberate: it rejects octal/hex/short/overflow encodings so only an unambiguous literal
     * counts as an IP -- matching the address OkHttp will actually connect to.
     */
    private fun parseStrictIpv4(host: String): IntArray? {
        val parts = host.split('.')
        if (parts.size != 4) return null
        val octets = IntArray(4)
        for (i in 0 until 4) {
            val part = parts[i]
            if (part.isEmpty() || part.length > 3) return null
            if (!part.all { it in '0'..'9' }) return null
            if (part.length > 1 && part[0] == '0') return null // reject octal-looking leading zero
            val value = part.toInt()
            if (value > 255) return null
            octets[i] = value
        }
        return octets
    }

    /** Classify an IPv4 by its first two octets against the accepted private/LAN ranges. */
    private fun isPrivateIpv4(a: Int, b: Int): Boolean = when {
        a == 127 -> true // loopback 127.0.0.0/8
        a == 10 -> true // RFC1918 10.0.0.0/8
        a == 172 && b in 16..31 -> true // RFC1918 172.16.0.0/12
        a == 192 && b == 168 -> true // RFC1918 192.168.0.0/16
        a == 100 && b in 64..127 -> true // CGNAT 100.64.0.0/10
        a == 169 && b == 254 -> true // link-local 169.254.0.0/16
        else -> false
    }

    // ---- IPv6 -------------------------------------------------------------------------------

    private fun isPrivateIpv6(bytes: ByteArray): Boolean {
        // IPv4-mapped (::ffff:a.b.c.d) -> classify the embedded IPv4 so a public v4 tunnelled
        // through a v6 literal is still rejected.
        if (isIpv4Mapped(bytes)) {
            return isPrivateIpv4(bytes[12].u(), bytes[13].u())
        }
        if (isLoopbackV6(bytes)) return true // ::1
        val b0 = bytes[0].u()
        val b1 = bytes[1].u()
        if (b0 == 0xFE && (b1 and 0xC0) == 0x80) return true // link-local fe80::/10
        if ((b0 and 0xFE) == 0xFC) return true // unique-local fc00::/7
        return false
    }

    private fun isIpv4Mapped(b: ByteArray): Boolean {
        for (i in 0 until 10) if (b[i].u() != 0) return false
        return b[10].u() == 0xFF && b[11].u() == 0xFF
    }

    private fun isLoopbackV6(b: ByteArray): Boolean {
        for (i in 0 until 15) if (b[i].u() != 0) return false
        return b[15].u() == 1
    }

    /**
     * Parse a bracket-less IPv6 literal (optionally with an embedded IPv4 tail or a `%zone`
     * suffix) into 16 bytes, or null if it is not a valid IPv6 literal. Pure string parsing --
     * never resolves, so it cannot block or be tricked into a DNS lookup.
     */
    private fun parseIpv6ToBytes(input: String): ByteArray? {
        val s = input.substringBefore('%') // drop a zone id (fe80::1%eth0)
        if (s.length < 2) return null

        // Split off a trailing embedded IPv4 (::ffff:1.2.3.4) if present.
        var head = s
        var tail: IntArray? = null
        if (s.contains('.')) {
            val lastColon = s.lastIndexOf(':')
            if (lastColon < 0) return null
            tail = parseStrictIpv4(s.substring(lastColon + 1)) ?: return null
            head = s.substring(0, lastColon)
        }

        val leftGroups = ArrayList<Int>()
        val rightGroups = ArrayList<Int>()
        val doubleColon = head.indexOf("::")
        if (doubleColon >= 0) {
            if (head.indexOf("::", doubleColon + 1) >= 0) return null // more than one "::"
            val left = head.substring(0, doubleColon)
            val right = head.substring(doubleColon + 2)
            if (left.startsWith(":") || right.endsWith(":")) return null
            if (!parseHextets(left, leftGroups)) return null
            if (!parseHextets(right, rightGroups)) return null
        } else {
            if (!parseHextets(head, leftGroups)) return null
        }

        val tailGroups = if (tail != null) 2 else 0
        val present = leftGroups.size + rightGroups.size + tailGroups
        if (doubleColon >= 0) {
            if (present > 7) return null // "::" must stand for at least one zero group
        } else {
            if (present != 8) return null
        }

        val groups = IntArray(8)
        var i = 0
        for (g in leftGroups) groups[i++] = g
        if (doubleColon >= 0) repeat(8 - present) { groups[i++] = 0 }
        for (g in rightGroups) groups[i++] = g
        if (tail != null) {
            groups[6] = (tail[0] shl 8) or tail[1]
            groups[7] = (tail[2] shl 8) or tail[3]
        }

        val out = ByteArray(16)
        for (j in 0 until 8) {
            out[j * 2] = ((groups[j] ushr 8) and 0xFF).toByte()
            out[j * 2 + 1] = (groups[j] and 0xFF).toByte()
        }
        return out
    }

    /** Parse a colon-separated run of 1-4 hex digit hextets into [out]; empty run is a no-op. */
    private fun parseHextets(part: String, out: MutableList<Int>): Boolean {
        if (part.isEmpty()) return true
        for (group in part.split(':')) {
            if (group.isEmpty() || group.length > 4) return false
            // Reject non-hex (e.g. a leading '+'/'-'), which toIntOrNull(16) would otherwise accept.
            if (!group.all { it in '0'..'9' || it in 'a'..'f' || it in 'A'..'F' }) return false
            val value = group.toIntOrNull(16) ?: return false
            out.add(value)
        }
        return true
    }

    /** Unsigned byte value (0..255). */
    private fun Byte.u(): Int = this.toInt() and 0xFF
}
