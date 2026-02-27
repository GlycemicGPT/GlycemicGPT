package com.glycemicgpt.mobile.di

import android.content.Context
import androidx.room.Room
import androidx.room.migration.Migration
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey
import androidx.sqlite.db.SupportSQLiteDatabase
import com.glycemicgpt.mobile.data.local.AppDatabase
import com.glycemicgpt.mobile.data.local.dao.AlertDao
import com.glycemicgpt.mobile.data.local.dao.PumpDao
import com.glycemicgpt.mobile.data.local.dao.RawHistoryLogDao
import com.glycemicgpt.mobile.data.local.dao.SyncDao
import dagger.Module
import dagger.Provides
import dagger.hilt.InstallIn
import dagger.hilt.android.qualifiers.ApplicationContext
import dagger.hilt.components.SingletonComponent
import net.zetetic.database.sqlcipher.SupportOpenHelperFactory
import timber.log.Timber
import java.security.SecureRandom
import javax.inject.Singleton

@Module
@InstallIn(SingletonComponent::class)
object DatabaseModule {

    private const val PASSPHRASE_PREFS = "db_passphrase_prefs"
    private const val PASSPHRASE_KEY = "db_passphrase"
    private const val PASSPHRASE_LENGTH = 32

    /** Migration 6->7: make cgm_readings.timestampMs index unique for dedup. */
    private val MIGRATION_6_7 = object : Migration(6, 7) {
        override fun migrate(db: SupportSQLiteDatabase) {
            db.execSQL(
                """DELETE FROM cgm_readings WHERE id NOT IN (
                    SELECT MAX(id) FROM cgm_readings GROUP BY timestampMs
                )""",
            )
            db.execSQL("DROP INDEX IF EXISTS index_cgm_readings_timestampMs")
            db.execSQL(
                "CREATE UNIQUE INDEX IF NOT EXISTS index_cgm_readings_timestampMs ON cgm_readings(timestampMs)",
            )
        }
    }

    /** Migration 7->8: make basal_readings.timestampMs index unique for dedup. */
    private val MIGRATION_7_8 = object : Migration(7, 8) {
        override fun migrate(db: SupportSQLiteDatabase) {
            db.execSQL(
                """DELETE FROM basal_readings WHERE id NOT IN (
                    SELECT MAX(id) FROM basal_readings GROUP BY timestampMs
                )""",
            )
            db.execSQL("DROP INDEX IF EXISTS index_basal_readings_timestampMs")
            db.execSQL(
                "CREATE UNIQUE INDEX IF NOT EXISTS index_basal_readings_timestampMs ON basal_readings(timestampMs)",
            )
        }
    }

    /**
     * Retrieve or generate the database passphrase from EncryptedSharedPreferences.
     *
     * The passphrase is generated once using SecureRandom and stored encrypted
     * via Android Keystore (AES-256-GCM). This ensures the DB is encrypted at
     * rest and the key is hardware-backed where possible.
     */
    private fun getOrCreatePassphrase(context: Context): ByteArray {
        val masterKey = MasterKey.Builder(context)
            .setKeyScheme(MasterKey.KeyScheme.AES256_GCM)
            .build()
        val prefs = EncryptedSharedPreferences.create(
            context,
            PASSPHRASE_PREFS,
            masterKey,
            EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
            EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM,
        )

        val existing = prefs.getString(PASSPHRASE_KEY, null)
        if (existing != null) {
            return existing.toByteArray(Charsets.UTF_8)
        }

        // Generate a new random passphrase
        val random = SecureRandom()
        val bytes = ByteArray(PASSPHRASE_LENGTH)
        random.nextBytes(bytes)
        // Encode as hex for safe storage and SQLCipher compatibility
        val passphrase = bytes.joinToString("") { "%02x".format(it) }

        val saved = prefs.edit().putString(PASSPHRASE_KEY, passphrase).commit()
        check(saved) { "Failed to persist SQLCipher passphrase" }
        Timber.i("Generated new database encryption passphrase")

        return passphrase.toByteArray(Charsets.UTF_8)
    }

    @Provides
    @Singleton
    fun provideDatabase(@ApplicationContext context: Context): AppDatabase {
        // Load SQLCipher native library
        System.loadLibrary("sqlcipher")

        val passphrase = getOrCreatePassphrase(context)
        val factory = SupportOpenHelperFactory(passphrase)

        // One-time migration: delete old unencrypted database (data re-syncs from backend)
        val migrationPrefs = context.getSharedPreferences("db_migration", Context.MODE_PRIVATE)
        if (!migrationPrefs.getBoolean("sqlcipher_migrated", false)) {
            val oldDbFile = context.getDatabasePath("glycemicgpt.db")
            var migrationReadyToMark = true
            if (oldDbFile.exists()) {
                Timber.w("Deleting unencrypted database for migration to SQLCipher")
                val deleted = context.deleteDatabase("glycemicgpt.db")
                if (!deleted) {
                    migrationReadyToMark = false
                    Timber.e("Failed to delete legacy unencrypted database; will retry next launch")
                }
            }
            if (migrationReadyToMark) {
                val marked = migrationPrefs.edit().putBoolean("sqlcipher_migrated", true).commit()
                check(marked) { "Failed to persist SQLCipher migration flag" }
            }
        }

        return Room.databaseBuilder(context, AppDatabase::class.java, "glycemicgpt_encrypted.db")
            .openHelperFactory(factory)
            .addMigrations(MIGRATION_6_7, MIGRATION_7_8)
            .fallbackToDestructiveMigration()
            .build()
    }

    @Provides
    fun providePumpDao(db: AppDatabase): PumpDao = db.pumpDao()

    @Provides
    fun provideSyncDao(db: AppDatabase): SyncDao = db.syncDao()

    @Provides
    fun provideRawHistoryLogDao(db: AppDatabase): RawHistoryLogDao = db.rawHistoryLogDao()

    @Provides
    fun provideAlertDao(db: AppDatabase): AlertDao = db.alertDao()
}
