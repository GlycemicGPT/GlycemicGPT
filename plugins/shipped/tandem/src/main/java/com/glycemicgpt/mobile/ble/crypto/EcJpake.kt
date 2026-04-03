package com.glycemicgpt.mobile.ble.crypto

import org.bouncycastle.jce.ECNamedCurveTable
import org.bouncycastle.jce.spec.ECParameterSpec
import org.bouncycastle.math.ec.ECPoint
import org.bouncycastle.util.BigIntegers
import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream
import java.io.InputStream
import java.io.OutputStream
import java.math.BigInteger
import java.security.MessageDigest
import java.security.SecureRandom

/**
 * EC-JPAKE protocol implementation based on the Thread specification.
 * Ported from io.particle.crypto.EcJpake (Apache 2.0 licensed).
 *
 * Reference: pumpX2 (MIT licensed) by jwoglom.
 */
class EcJpake(
    private val role: Role,
    secret: ByteArray,
    private val rand: SecureRandom = SecureRandom(),
) {
    enum class Role { CLIENT, SERVER }

    private class KeyPair(val priv: BigInteger, val pub: ECPoint)

    private val ec: ECParameterSpec = ECNamedCurveTable.getParameterSpec(CURVE_NAME)
        ?: throw UnsupportedOperationException("Unsupported curve: $CURVE_NAME")
    private val hash: MessageDigest = MessageDigest.getInstance(HASH_NAME)

    private val myId: ByteArray = if (role == Role.CLIENT) CLIENT_ID else SERVER_ID
    private val peerId: ByteArray = if (role == Role.CLIENT) SERVER_ID else CLIENT_ID
    private val s: BigInteger = BigInteger(1, secret)

    private var xm1: BigInteger? = null
    private var Xm1: ECPoint? = null
    private var xm2: BigInteger? = null
    private var Xm2: ECPoint? = null
    private var Xp1: ECPoint? = null
    private var Xp2: ECPoint? = null
    private var Xp: ECPoint? = null

    private var hasPeerRound1 = false
    private var hasPeerRound2 = false
    private var myRound1: ByteArray? = null
    private var myRound2: ByteArray? = null
    private var _derivedSecret: ByteArray? = null

    /** Generate the message for round 1 of the protocol. */
    fun getRound1(): ByteArray {
        if (myRound1 == null) {
            val out = ByteArrayOutputStream()
            val kp1 = genKeyPair(ec.g)
            xm1 = kp1.priv
            Xm1 = kp1.pub
            writePoint(out, Xm1!!)
            writeZkp(out, ec.g, kp1.priv, kp1.pub, myId)

            val kp2 = genKeyPair(ec.g)
            xm2 = kp2.priv
            Xm2 = kp2.pub
            writePoint(out, Xm2!!)
            writeZkp(out, ec.g, kp2.priv, kp2.pub, myId)

            myRound1 = out.toByteArray()
        }
        return myRound1!!
    }

    /** Read the peer's round 1 message. */
    fun readRound1(data: ByteArray): Int {
        check(!hasPeerRound1) { "Invalid protocol state" }
        val input = ByteArrayInputStream(data)
        Xp1 = readPoint(input)
        readZkp(input, ec.g, Xp1!!, peerId)
        Xp2 = readPoint(input)
        readZkp(input, ec.g, Xp2!!, peerId)
        hasPeerRound1 = true
        return data.size - input.available()
    }

    /** Generate the message for round 2 of the protocol. */
    fun getRound2(): ByteArray {
        if (myRound2 == null) {
            check(hasPeerRound1 && myRound1 != null) { "Invalid protocol state" }
            val out = ByteArrayOutputStream()
            val G = Xp1!!.add(Xp2).add(Xm1)
            val xm = mulSecret(xm2!!, s, negate = false)
            val Xm = G.multiply(xm)
            if (role == Role.SERVER) {
                writeCurveId(out)
            }
            writePoint(out, Xm)
            writeZkp(out, G, xm, Xm, myId)
            myRound2 = out.toByteArray()
        }
        return myRound2!!
    }

    /** Read the peer's round 2 message. */
    fun readRound2(data: ByteArray): Int {
        check(hasPeerRound1 && myRound1 != null && !hasPeerRound2) { "Invalid protocol state" }
        val input = ByteArrayInputStream(data)
        if (role == Role.CLIENT) {
            readCurveId(input)
        }
        val G = Xm1!!.add(Xm2).add(Xp1)
        Xp = readPoint(input)
        readZkp(input, G, Xp!!, peerId)
        hasPeerRound2 = true
        return data.size - input.available()
    }

    /** Derive the shared secret after both rounds are complete. */
    fun deriveSecret(): ByteArray {
        if (_derivedSecret == null) {
            check(hasPeerRound2) { "Invalid protocol state" }
            val xm2s = mulSecret(xm2!!, s, negate = true)
            val K = Xp!!.add(Xp2!!.multiply(xm2s)).multiply(xm2!!)
            _derivedSecret = hash.digest(
                BigIntegers.asUnsignedByteArray(K.normalize().xCoord.toBigInteger()),
            )
        }
        return _derivedSecret!!
    }

    // -- ZKP (Zero Knowledge Proof) -------------------------------------------

    private fun readZkp(input: InputStream, G: ECPoint, X: ECPoint, id: ByteArray) {
        val V = readPoint(input)
        val r = readNum(input)
        val h = zkpHash(G, V, X, id)
        val VV = G.multiply(r).add(X.multiply(h.mod(ec.n)))
        if (!VV.equals(V)) {
            throw RuntimeException("ZKP validation failed")
        }
    }

    private fun writeZkp(out: OutputStream, G: ECPoint, x: BigInteger, X: ECPoint, id: ByteArray) {
        val kp = genKeyPair(G)
        val v = kp.priv
        val V = kp.pub
        val h = zkpHash(G, V, X, id)
        val r = v.subtract(x.multiply(h)).mod(ec.n)
        writePoint(out, V)
        writeNum(out, r)
    }

    private fun zkpHash(G: ECPoint, V: ECPoint, X: ECPoint, id: ByteArray): BigInteger {
        val out = ByteArrayOutputStream()
        writeZkpHashPoint(out, G)
        writeZkpHashPoint(out, V)
        writeZkpHashPoint(out, X)
        writeUint32Be(out, id.size.toLong())
        out.write(id)
        val digest = hash.digest(out.toByteArray())
        return BigInteger(1, digest).mod(ec.n)
    }

    private fun writeZkpHashPoint(out: OutputStream, point: ECPoint) {
        val encoded = point.getEncoded(ENCODED_COMPRESSED)
        writeUint32Be(out, encoded.size.toLong())
        out.write(encoded)
    }

    // -- Secret multiplication ------------------------------------------------

    private fun mulSecret(X: BigInteger, S: BigInteger, negate: Boolean): BigInteger {
        val b = BigInteger(1, randBytes(16))
        val bN = b.multiply(ec.n).add(S)
        var R = X.multiply(bN)
        if (negate) R = R.negate()
        return R.mod(ec.n)
    }

    // -- Point / BigInteger serialization -------------------------------------

    private fun readPoint(input: InputStream): ECPoint {
        val len = readUint8(input)
        val encoded = readBytes(input, len)
        return ec.curve.decodePoint(encoded)
    }

    private fun writePoint(out: OutputStream, point: ECPoint) {
        val encoded = point.getEncoded(ENCODED_COMPRESSED)
        check(encoded.size <= 255) { "Encoded ECPoint too long" }
        writeUint8(out, encoded.size)
        out.write(encoded)
    }

    private fun readNum(input: InputStream): BigInteger {
        val len = readUint8(input)
        val encoded = readBytes(input, len)
        return BigInteger(1, encoded)
    }

    private fun writeNum(out: OutputStream, value: BigInteger) {
        // Use fixed-length encoding (32 bytes for P-256 scalars) to ensure
        // round 1 is always exactly 330 bytes and round 2 is always 165 bytes.
        // Without this, BigIntegers.asUnsignedByteArray strips leading zeros,
        // causing rare (~1.6%) ArrayIndexOutOfBoundsException on split offsets.
        val encoded = BigIntegers.asUnsignedByteArray(SCALAR_LEN, value)
        writeUint8(out, encoded.size)
        out.write(encoded)
    }

    // -- Curve ID serialization -----------------------------------------------

    private fun readCurveId(input: InputStream) {
        val type = readUint8(input)
        check(type == 3) { "Invalid ECCurveType: $type" } // named_curve
        val id = readUint16Be(input)
        check(id == CURVE_ID) { "Unexpected curve ID: $id" }
    }

    private fun writeCurveId(out: OutputStream) {
        writeUint8(out, 3) // ECCurveType.named_curve
        writeUint16Be(out, CURVE_ID)
    }

    // -- Key pair generation --------------------------------------------------

    private fun genKeyPair(G: ECPoint): KeyPair {
        val priv = BigIntegers.createRandomInRange(BigInteger.ONE, ec.n.subtract(BigInteger.ONE), rand)
        val pub = G.multiply(priv)
        return KeyPair(priv, pub)
    }

    private fun randBytes(count: Int): ByteArray {
        val b = ByteArray(count)
        rand.nextBytes(b)
        return b
    }

    // -- Stream helpers -------------------------------------------------------

    companion object {
        private const val CURVE_NAME = "P-256"
        private const val CURVE_ID = 23 // RFC 4492
        private const val HASH_NAME = "SHA-256"
        private val CLIENT_ID = "client".toByteArray()
        private val SERVER_ID = "server".toByteArray()
        private const val ENCODED_COMPRESSED = false
        /** Fixed scalar length for P-256 (order n is 256 bits = 32 bytes). */
        private const val SCALAR_LEN = 32

        // No global JCE provider manipulation needed. ECNamedCurveTable and
        // EC point arithmetic use the BouncyCastle jar directly (not through
        // the JCE provider framework), so adding/removing the BC provider
        // is unnecessary and would risk disrupting Tink/EncryptedSharedPreferences.

        private fun readUint8(input: InputStream): Int {
            val b = input.read()
            if (b < 0) throw RuntimeException("Unexpected end of stream")
            return b
        }

        private fun writeUint8(out: OutputStream, value: Int) {
            out.write(value)
        }

        private fun readUint16Be(input: InputStream): Int {
            val b = readBytes(input, 2)
            return ((b[0].toInt() and 0xFF) shl 8) or (b[1].toInt() and 0xFF)
        }

        private fun writeUint16Be(out: OutputStream, value: Int) {
            out.write((value ushr 8) and 0xFF)
            out.write(value and 0xFF)
        }

        private fun writeUint32Be(out: OutputStream, value: Long) {
            out.write(((value ushr 24) and 0xFF).toInt())
            out.write(((value ushr 16) and 0xFF).toInt())
            out.write(((value ushr 8) and 0xFF).toInt())
            out.write((value and 0xFF).toInt())
        }

        private fun readBytes(input: InputStream, len: Int): ByteArray {
            val b = ByteArray(len)
            var offs = 0
            while (offs < len) {
                val r = input.read(b, offs, len - offs)
                if (r < 0) throw RuntimeException("Unexpected end of stream")
                offs += r
            }
            return b
        }
    }
}
