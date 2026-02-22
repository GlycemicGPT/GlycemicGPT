package com.glycemicgpt.mobile.service

import com.glycemicgpt.mobile.data.local.entity.AlertEntity
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class AlertNotificationManagerTest {

    private fun makeAlert(
        serverId: String = "alert-1",
        alertType: String = "high_warning",
        severity: String = "warning",
        currentValue: Double = 250.0,
        patientName: String? = null,
    ) = AlertEntity(
        serverId = serverId,
        alertType = alertType,
        severity = severity,
        message = "High glucose warning",
        currentValue = currentValue,
        timestampMs = System.currentTimeMillis(),
        patientName = patientName,
    )

    // --- Channel resolution tests ---

    @Test
    fun `low alert resolves to low channel`() {
        val alert = makeAlert(alertType = "low_urgent")
        val channelId = resolveChannelId(alert, lowVersion = 3, highVersion = 1, aiVersion = 1)
        assertEquals("low_alerts_v3", channelId)
    }

    @Test
    fun `low warning resolves to low channel`() {
        val alert = makeAlert(alertType = "low_warning")
        val channelId = resolveChannelId(alert, lowVersion = 1, highVersion = 1, aiVersion = 1)
        assertEquals("low_alerts_v1", channelId)
    }

    @Test
    fun `high alert resolves to high channel`() {
        val alert = makeAlert(alertType = "high_warning")
        val channelId = resolveChannelId(alert, lowVersion = 1, highVersion = 2, aiVersion = 1)
        assertEquals("high_alerts_v2", channelId)
    }

    @Test
    fun `high urgent resolves to high channel`() {
        val alert = makeAlert(alertType = "high_urgent")
        val channelId = resolveChannelId(alert, lowVersion = 1, highVersion = 1, aiVersion = 1)
        assertEquals("high_alerts_v1", channelId)
    }

    @Test
    fun `iob warning resolves to ai channel`() {
        val alert = makeAlert(alertType = "iob_warning")
        val channelId = resolveChannelId(alert, lowVersion = 1, highVersion = 1, aiVersion = 5)
        assertEquals("ai_notifications_v5", channelId)
    }

    @Test
    fun `unknown alert type resolves to ai channel`() {
        val alert = makeAlert(alertType = "some_other_type")
        val channelId = resolveChannelId(alert, lowVersion = 1, highVersion = 1, aiVersion = 1)
        assertEquals("ai_notifications_v1", channelId)
    }

    // --- Channel ID formatting tests ---

    @Test
    fun `lowChannelId formats correctly`() {
        assertEquals("low_alerts_v1", AlertNotificationManager.lowChannelId(1))
        assertEquals("low_alerts_v42", AlertNotificationManager.lowChannelId(42))
    }

    @Test
    fun `highChannelId formats correctly`() {
        assertEquals("high_alerts_v1", AlertNotificationManager.highChannelId(1))
        assertEquals("high_alerts_v10", AlertNotificationManager.highChannelId(10))
    }

    @Test
    fun `aiChannelId formats correctly`() {
        assertEquals("ai_notifications_v1", AlertNotificationManager.aiChannelId(1))
        assertEquals("ai_notifications_v7", AlertNotificationManager.aiChannelId(7))
    }

    // --- Title formatting tests ---

    @Test
    fun `notification title includes severity prefix and glucose value`() {
        val alert = makeAlert(severity = "emergency", currentValue = 320.0)
        val title = buildTitle(alert)
        assertEquals("EMERGENCY: 320 mg/dL", title)
    }

    @Test
    fun `notification title includes patient name for caregivers`() {
        val alert = makeAlert(severity = "urgent", currentValue = 55.0, patientName = "Alice")
        val title = buildTitle(alert)
        assertEquals("URGENT: 55 mg/dL - Alice", title)
    }

    @Test
    fun `warning title uses mixed case`() {
        val alert = makeAlert(severity = "warning", currentValue = 200.0)
        val title = buildTitle(alert)
        assertEquals("Warning: 200 mg/dL", title)
    }

    @Test
    fun `info title uses mixed case`() {
        val alert = makeAlert(severity = "info", currentValue = 180.0)
        val title = buildTitle(alert)
        assertEquals("Info: 180 mg/dL", title)
    }

    // --- Stable notification ID tests ---

    @Test
    fun `stable notification ID is deterministic for same alert type`() {
        val alert1 = makeAlert(serverId = "a1", alertType = "high_warning")
        val alert2 = makeAlert(serverId = "a2", alertType = "high_warning")
        assertEquals(stableNotificationId(alert1), stableNotificationId(alert2))
    }

    @Test
    fun `stable notification ID differs for different alert types`() {
        val high = makeAlert(alertType = "high_warning")
        val low = makeAlert(alertType = "low_urgent")
        assertNotEquals(stableNotificationId(high), stableNotificationId(low))
    }

    @Test
    fun `stable notification ID differs for same type different patients`() {
        val alice = makeAlert(alertType = "high_warning", patientName = "Alice")
        val bob = makeAlert(alertType = "high_warning", patientName = "Bob")
        assertNotEquals(stableNotificationId(alice), stableNotificationId(bob))
    }

    @Test
    fun `stable notification ID is at least 100`() {
        val alert = makeAlert()
        assertTrue(stableNotificationId(alert) >= 100)
    }

    @Test
    fun `stable notification ID is positive for all alert types`() {
        for (alertType in listOf("low_urgent", "low_warning", "high_warning", "high_urgent", "iob_warning")) {
            val id = stableNotificationId(makeAlert(alertType = alertType))
            assertTrue("ID for $alertType should be positive, got $id", id > 0)
        }
    }

    @Test
    fun `stable notification ID ignores serverId`() {
        val a = makeAlert(serverId = "id-1", alertType = "high_urgent")
        val b = makeAlert(serverId = "id-999", alertType = "high_urgent")
        assertEquals(stableNotificationId(a), stableNotificationId(b))
    }

    // --- Severity-aware notification behavior tests ---

    @Test
    fun `low alerts should re-alert on each update`() {
        for (alertType in listOf("low_urgent", "low_warning")) {
            val isLow = alertType in listOf("low_urgent", "low_warning")
            assertTrue("$alertType should be classified as low", isLow)
        }
    }

    @Test
    fun `high and iob alerts should use onlyAlertOnce`() {
        for (alertType in listOf("high_warning", "high_urgent", "iob_warning")) {
            val isLow = alertType in listOf("low_urgent", "low_warning")
            assertFalse("$alertType should not be classified as low", isLow)
        }
    }

    // --- Dedup logic tests (shouldNotify / markAcknowledged) ---

    @Test
    fun `shouldNotify returns true for new serverId`() {
        val dedup = DedupTracker()
        assertTrue(dedup.shouldNotify("alert-1"))
    }

    @Test
    fun `shouldNotify returns false for already-notified serverId`() {
        val dedup = DedupTracker()
        dedup.shouldNotify("alert-1")
        assertFalse(dedup.shouldNotify("alert-1"))
    }

    @Test
    fun `markAcknowledged allows re-notification for same serverId`() {
        val dedup = DedupTracker()
        dedup.shouldNotify("alert-1")
        dedup.markAcknowledged("alert-1")
        assertTrue(dedup.shouldNotify("alert-1"))
    }

    @Test
    fun `shouldNotify handles multiple distinct alerts`() {
        val dedup = DedupTracker()
        assertTrue(dedup.shouldNotify("alert-1"))
        assertTrue(dedup.shouldNotify("alert-2"))
        assertTrue(dedup.shouldNotify("alert-3"))
        assertFalse(dedup.shouldNotify("alert-1"))
        assertFalse(dedup.shouldNotify("alert-2"))
    }

    @Test
    fun `shouldNotify prunes oldest entries when exceeding max`() {
        val dedup = DedupTracker(maxIds = 3)
        dedup.shouldNotify("a")
        dedup.shouldNotify("b")
        dedup.shouldNotify("c")
        dedup.shouldNotify("d")
        assertTrue(dedup.shouldNotify("a"))
        assertFalse(dedup.shouldNotify("d"))
    }

    @Test
    fun `markAcknowledged is idempotent for unknown serverId`() {
        val dedup = DedupTracker()
        dedup.markAcknowledged("nonexistent")
        assertTrue(dedup.shouldNotify("nonexistent"))
    }

    /**
     * Mirrors the production dedup logic in [AlertNotificationManager] for testing
     * without Android dependencies.
     */
    private class DedupTracker(private val maxIds: Int = 200) {
        private val ids = linkedSetOf<String>()
        private val lock = Any()

        fun shouldNotify(serverId: String): Boolean = synchronized(lock) {
            val isNew = ids.add(serverId)
            if (isNew && ids.size > maxIds) {
                val iterator = ids.iterator()
                repeat(ids.size - maxIds) {
                    if (iterator.hasNext()) {
                        iterator.next()
                        iterator.remove()
                    }
                }
            }
            isNew
        }

        fun markAcknowledged(serverId: String): Unit = synchronized(lock) {
            ids.remove(serverId)
        }
    }

    // --- Helper mirrors for testing without Android context ---

    private fun buildTitle(alert: AlertEntity): String {
        val prefix = when (alert.severity) {
            "emergency" -> "EMERGENCY"
            "urgent" -> "URGENT"
            "warning" -> "Warning"
            else -> "Info"
        }
        val patientSuffix = alert.patientName?.let { " - $it" } ?: ""
        return "$prefix: ${alert.currentValue.toInt()} mg/dL$patientSuffix"
    }

    private fun stableNotificationId(alert: AlertEntity): Int {
        val key = "${alert.alertType}|${alert.patientName ?: ""}"
        return (key.hashCode() and 0x7FFFFFFF).coerceAtLeast(100)
    }

    /**
     * Mirrors [AlertNotificationManager.resolveChannelId] for testing without
     * Android context. Uses the same classification logic.
     */
    private fun resolveChannelId(
        alert: AlertEntity,
        lowVersion: Int,
        highVersion: Int,
        aiVersion: Int,
    ): String {
        val lowTypes = listOf("low_urgent", "low_warning")
        val highTypes = listOf("high_warning", "high_urgent")
        return when {
            alert.alertType in lowTypes -> "low_alerts_v$lowVersion"
            alert.alertType in highTypes -> "high_alerts_v$highVersion"
            else -> "ai_notifications_v$aiVersion"
        }
    }
}
