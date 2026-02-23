package com.glycemicgpt.mobile.domain.pump

/** Format a ByteArray as a space-separated lowercase hex string (e.g., "0a 1b 2c"). */
fun ByteArray.toSpacedHex(): String =
    joinToString(" ") { "%02x".format(it.toInt() and 0xFF) }
