/*
 * AC1: the medfloat32 / uint32 / sign-extend additions to MedtronicCodec the IDD and history records
 * rely on, checked against values decoded from the published upstream test vectors.
 */
package com.glycemicgpt.mobile.ble.read

import org.junit.Assert.assertEquals
import org.junit.Test

class MedtronicCodecMedFloat32Test {

    @Test
    fun `decodeMedFloat32 decodes the reservoir vector to IU`() {
        // From pump_status.py example 5596e80d28fb010300: reservoir bytes e8 0d 28 fb (LE) -> medfloat32
        // = mantissa 0x280de8 (2,625,000) x 10^(exp 0xfb = -5) = 26.25 IU.
        val raw = MedtronicCodec.readULongLe(hex("e80d28fb"), 0, 4)
        assertEquals(26.25, MedtronicCodec.decodeMedFloat32(raw), 1e-9)
    }

    @Test
    fun `decodeMedFloat32 decodes the IOB vector to IU`() {
        // From iob.py example fc0300c05c15fa: IOB f32 bytes c0 5c 15 fa (LE)
        // = mantissa 0x155cc0 (1,400,000) x 10^(exp 0xfa = -6) = 1.4 IU.
        val raw = MedtronicCodec.readULongLe(hex("c05c15fa"), 0, 4)
        assertEquals(1.4, MedtronicCodec.decodeMedFloat32(raw), 1e-9)
    }

    @Test
    fun `decodeMedFloat32 decodes a zero rate as zero`() {
        assertEquals(0.0, MedtronicCodec.decodeMedFloat32(0L), 0.0)
    }

    @Test
    fun `readULongLe reads a full unsigned 32-bit value without sign loss`() {
        assertEquals(0xFFFFFFFFL, MedtronicCodec.readULongLe(hex("ffffffff"), 0, 4))
        assertEquals(0x0014D6L, MedtronicCodec.readULongLe(hex("d6140000"), 0, 4))
    }

    @Test
    fun `signExtend turns a negative i16 into a negative Int`() {
        assertEquals(-1, MedtronicCodec.signExtend(0xFFFF, 16))
        assertEquals(-2, MedtronicCodec.signExtend(0xFFFE, 16))
        assertEquals(5, MedtronicCodec.signExtend(0x0005, 16))
    }

    @Test
    fun `signExtend on a full 32-bit width is the identity`() {
        // 1 shl 32 would wrap (Kotlin masks the shift to low 5 bits); a full-width Int needs no extension.
        assertEquals(-1, MedtronicCodec.signExtend(-1, 32))
        assertEquals(Int.MIN_VALUE, MedtronicCodec.signExtend(Int.MIN_VALUE, 32))
        assertEquals(42, MedtronicCodec.signExtend(42, 32))
    }
}
