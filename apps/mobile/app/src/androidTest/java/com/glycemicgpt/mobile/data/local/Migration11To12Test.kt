package com.glycemicgpt.mobile.data.local

import androidx.room.testing.MigrationTestHelper
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.glycemicgpt.mobile.di.DatabaseModule
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

/**
 * Verifies the Room 11 -> 12 migration (Story 43.8) that adds a `source` column to
 * `cgm_readings` and `basal_readings`. Guards two things at once:
 *
 *  1. `runMigrationsAndValidate` re-creates the v11 schema from the exported `11.json`, applies the
 *     real [DatabaseModule.ALL_MIGRATIONS], and asserts the result matches the exported `12.json` --
 *     so a wrong `ALTER TABLE` would fail here, not silently ship.
 *  2. Existing rows written at v11 survive the upgrade and the new column defaults to "" -- the
 *     contract the BLE writers rely on (they leave `source` empty).
 *
 * Instrumented (needs real SQLite): run with `./gradlew :app:connectedDebugAndroidTest`.
 */
@RunWith(AndroidJUnit4::class)
class Migration11To12Test {

    @get:Rule
    val helper = MigrationTestHelper(
        InstrumentationRegistry.getInstrumentation(),
        AppDatabase::class.java,
    )

    @Test
    fun migrate11To12_addsSourceColumn_andPreservesExistingRows() {
        // v11: cgm_readings and basal_readings have no `source` column yet.
        helper.createDatabase(TEST_DB, 11).use { db ->
            db.execSQL(
                "INSERT INTO cgm_readings (glucoseMgDl, trendArrow, timestampMs) " +
                    "VALUES (120, 'FLAT', 1000)",
            )
            db.execSQL(
                "INSERT INTO basal_readings (rate, isAutomated, activityMode, timestampMs) " +
                    "VALUES (0.75, 1, 'NONE', 2000)",
            )
        }

        val db = helper.runMigrationsAndValidate(TEST_DB, 12, true, *DatabaseModule.ALL_MIGRATIONS)

        db.query("SELECT glucoseMgDl, source FROM cgm_readings").use { cursor ->
            assertTrue("cgm row should survive the migration", cursor.moveToFirst())
            assertEquals(120, cursor.getInt(0))
            assertEquals("", cursor.getString(1))
        }
        db.query("SELECT rate, source FROM basal_readings").use { cursor ->
            assertTrue("basal row should survive the migration", cursor.moveToFirst())
            assertEquals(0.75f, cursor.getFloat(0), 0.0001f)
            assertEquals("", cursor.getString(1))
        }
    }

    private companion object {
        const val TEST_DB = "migration-11-12-test"
    }
}
