/*
 * AC3 + AC5: end-to-end CGM read (feature-flag-driven E2E-CRC, RACP last-record, decrypt, parse to a
 * mg/dL CgmReading with a mapped trend arrow) and the SafetyLimits rejection of an out-of-range SG.
 */
package com.glycemicgpt.mobile.ble.read

import com.glycemicgpt.mobile.ble.protocol.MedtronicProtocol
import com.glycemicgpt.mobile.domain.model.CgmTrend
import com.glycemicgpt.mobile.domain.pump.SafetyLimits
import java.time.Instant
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class CgmReaderTest {

    private val feature = MedtronicProtocol.CGM_FEATURE_UUID
    private val measurement = MedtronicProtocol.CGM_MEASUREMENT_UUID
    private val racp = MedtronicProtocol.RACP_UUID
    private val fixedNow = Instant.ofEpochSecond(1_700_000_000)

    /** Append the little-endian E2E-CRC computed over [dataNoCrc] (whose size byte already includes it). */
    private fun withCrc(dataNoCrc: ByteArray): ByteArray {
        val crc = MedtronicCodec.e2eCrc(dataNoCrc, dataNoCrc.size)
        return dataNoCrc + byteArrayOf((crc and 0xFF).toByte(), ((crc shr 8) and 0xFF).toByte())
    }

    private fun reader(link: FakeGattLink, two: TwoSidedSession, limits: SafetyLimits = SafetyLimits()) =
        CgmReader(link, two.server, limits) { fixedNow }

    @Test
    fun `reads the latest SG in mg dL with a mapped trend when E2E-CRC is enabled`() {
        val two = TwoSidedSession()
        val link = FakeGattLink()
        link.reads[feature] = hex("009001591404") // E2E_CRC enabled
        link.onWrite = { characteristic, _ ->
            if (characteristic == racp) {
                emit(measurement, two.pumpEncrypt(hex("0ec3f900f40b000074e00a00e0f1")))
                emit(racp, MedtronicSessionReader.RACP_REPORT_SUCCESS)
            }
        }

        var result: Result<com.glycemicgpt.mobile.domain.model.CgmReading>? = null
        reader(link, two).readLatest { result = it }

        val reading = result!!.getOrThrow()
        assertEquals(249, reading.glucoseMgDl)
        assertEquals(CgmTrend.FORTY_FIVE_UP, reading.trendArrow)
        assertEquals(fixedNow, reading.timestamp)
    }

    @Test
    fun `reads a measurement without a CRC when the feature flag is off`() {
        val two = TwoSidedSession()
        val link = FakeGattLink()
        link.reads[feature] = hex("910000" + "14" + "ffff") // E2E unsupported
        link.onWrite = { characteristic, _ ->
            if (characteristic == racp) {
                emit(measurement, two.pumpEncrypt(hex("0cc3f900f40b000074e00a00")))
                emit(racp, MedtronicSessionReader.RACP_REPORT_SUCCESS)
            }
        }

        var result: Result<com.glycemicgpt.mobile.domain.model.CgmReading>? = null
        reader(link, two).readLatest { result = it }

        assertEquals(249, result!!.getOrThrow().glucoseMgDl)
    }

    @Test
    fun `rejects an out-of-range SG rather than clamping it`() {
        val two = TwoSidedSession()
        val link = FakeGattLink()
        link.reads[feature] = hex("009001591404")
        // Glucose 600 mg/dL (0x0258), no optional fields, with a valid E2E-CRC.
        val record = withCrc(byteArrayOf(0x08, 0x00, 0x58, 0x02, 0x00, 0x00))
        link.onWrite = { characteristic, _ ->
            if (characteristic == racp) {
                emit(measurement, two.pumpEncrypt(record))
                emit(racp, MedtronicSessionReader.RACP_REPORT_SUCCESS)
            }
        }

        var result: Result<com.glycemicgpt.mobile.domain.model.CgmReading>? = null
        reader(link, two).readLatest { result = it }

        assertTrue(result!!.isFailure)
        assertTrue(result!!.exceptionOrNull() is MedtronicReadException)
    }

    @Test
    fun `rejects a non-finite SFLOAT glucose sentinel`() {
        val two = TwoSidedSession()
        val link = FakeGattLink()
        link.reads[feature] = hex("009001591404")
        // Glucose mantissa 0x07FF (NaN sentinel), no optional fields, valid E2E-CRC.
        val record = withCrc(byteArrayOf(0x08, 0x00, 0xFF.toByte(), 0x07, 0x00, 0x00))
        link.onWrite = { characteristic, _ ->
            if (characteristic == racp) {
                emit(measurement, two.pumpEncrypt(record))
                emit(racp, MedtronicSessionReader.RACP_REPORT_SUCCESS)
            }
        }

        var result: Result<com.glycemicgpt.mobile.domain.model.CgmReading>? = null
        reader(link, two).readLatest { result = it }

        assertTrue(result!!.isFailure)
        assertTrue(result!!.exceptionOrNull() is MedtronicReadException)
    }

    @Test
    fun `feature read failure surfaces without issuing an RACP request`() {
        val two = TwoSidedSession()
        val link = FakeGattLink()
        link.reads[feature] = hex("0090") // wrong length

        var result: Result<com.glycemicgpt.mobile.domain.model.CgmReading>? = null
        reader(link, two).readLatest { result = it }

        assertTrue(result!!.isFailure)
        assertEquals(0, link.writes.size)
    }

    @Test
    fun `trend rate maps onto the CgmTrend arrows`() {
        assertEquals(CgmTrend.UNKNOWN, CgmReader.trendArrowFor(null))
        assertEquals(CgmTrend.UNKNOWN, CgmReader.trendArrowFor(Double.NaN))
        assertEquals(CgmTrend.UNKNOWN, CgmReader.trendArrowFor(Double.POSITIVE_INFINITY))
        assertEquals(CgmTrend.FLAT, CgmReader.trendArrowFor(0.5))
        assertEquals(CgmTrend.FLAT, CgmReader.trendArrowFor(-0.5))
        assertEquals(CgmTrend.FORTY_FIVE_UP, CgmReader.trendArrowFor(1.5))
        assertEquals(CgmTrend.SINGLE_UP, CgmReader.trendArrowFor(2.5))
        assertEquals(CgmTrend.DOUBLE_UP, CgmReader.trendArrowFor(3.5))
        assertEquals(CgmTrend.FORTY_FIVE_DOWN, CgmReader.trendArrowFor(-1.5))
        assertEquals(CgmTrend.SINGLE_DOWN, CgmReader.trendArrowFor(-2.5))
        assertEquals(CgmTrend.DOUBLE_DOWN, CgmReader.trendArrowFor(-3.5))
    }
}
