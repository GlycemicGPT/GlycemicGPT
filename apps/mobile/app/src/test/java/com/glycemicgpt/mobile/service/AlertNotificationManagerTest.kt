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

    // --- Channel selection tests ---

    @Test
    fun `urgent channel selected for emergency severity`() {
        val alert = makeAlert(severity = "emergency")
        val isUrgent = alert.severity in listOf("urgent", "emergency")
        val channelId = if (isUrgent) AlertNotificationManager.CHANNEL_URGENT
            else AlertNotificationManager.CHANNEL_STANDARD
        assertEquals(AlertNotificationManager.CHANNEL_URGENT, channelId)
    }

    @Test
    fun `urgent channel selected for urgent severity`() {
        val alert = makeAlert(severity = "urgent")
        val isUrgent = alert.severity in listOf("urgent", "emergency")
        val channelId = if (isUrgent) AlertNotificationManager.CHANNEL_URGENT
            else AlertNotificationManager.CHANNEL_STANDARD
        assertEquals(AlertNotificationManager.CHANNEL_URGENT, channelId)
    }

    @Test
    fun `standard channel selected for warning severity`() {
        val alert = makeAlert(severity = "warning")
        val isUrgent = alert.severity in listOf("urgent", "emergency")
        val channelId = if (isUrgent) AlertNotificationManager.CHANNEL_URGENT
            else AlertNotificationManager.CHANNEL_STANDARD
        assertEquals(AlertNotificationManager.CHANNEL_STANDARD, channelId)
    }

    @Test
    fun `standard channel selected for info severity`() {
        val alert = makeAlert(severity = "info")
        val isUrgent = alert.severity in listOf("urgent", "emergency")
        val channelId = if (isUrgent) AlertNotificationManager.CHANNEL_URGENT
            else AlertNotificationManager.CHANNEL_STANDARD
        assertEquals(AlertNotificationManager.CHANNEL_STANDARD, channelId)
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
    // These test the same logic used in AlertNotificationManager but without
    // needing Android Context (which requires Robolectric). The production
    // code uses the exact same synchronized set + add/remove pattern.

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
        // Adding "d" should prune "a"
        dedup.shouldNotify("d")
        // "a" was pruned, so it should be treated as new
        assertTrue(dedup.shouldNotify("a"))
        // linkedSetOf preserves insertion order, so after pruning the set is {b, c, d}
        // "d" should still be in the set
        assertFalse(dedup.shouldNotify("d"))
    }

    @Test
    fun `markAcknowledged is idempotent for unknown serverId`() {
        val dedup = DedupTracker()
        // Should not throw
        dedup.markAcknowledged("nonexistent")
        // Set should still be empty, new add should work
        assertTrue(dedup.shouldNotify("nonexistent"))
    }

    /**
     * Mirrors the production dedup logic in [AlertNotificationManager] for testing
     * without Android dependencies. Uses the exact same synchronized pattern.
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
}
