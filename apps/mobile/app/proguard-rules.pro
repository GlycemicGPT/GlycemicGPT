# GlycemicGPT Android App ProGuard Rules

# Keep BLE protocol classes (needed for runtime reflection in message parsing)
-keep class com.glycemicgpt.mobile.ble.** { *; }

# Keep Moshi-annotated JSON model classes
-keep @com.squareup.moshi.JsonClass class * { *; }
-keepclassmembers @com.squareup.moshi.JsonClass class * {
    <init>(...);
}

# Keep Room entities
-keep class * extends androidx.room.RoomDatabase
-keep @androidx.room.Entity class *

# Tink (used by EncryptedSharedPreferences)
-dontwarn com.google.errorprone.annotations.**

# OkHttp
-dontwarn okhttp3.internal.platform.**
-dontwarn org.conscrypt.**
-dontwarn org.openjsse.**

# BouncyCastle (used for EC-JPAKE authentication)
-keep class org.bouncycastle.** { *; }
-dontwarn org.bouncycastle.**

# Retrofit
-keepattributes Signature
-keepattributes *Annotation*

# Coroutines
-keepnames class kotlinx.coroutines.internal.MainDispatcherFactory {}
-keepnames class kotlinx.coroutines.CoroutineExceptionHandler {}

# Compose Markdown (JitPack library uses reflection for text span handling)
-keep class dev.jeziellago.compose.markdowntext.** { *; }

# Plugin API interfaces and domain models (needed for capability reflection)
-keep class com.glycemicgpt.mobile.domain.plugin.** { *; }
-keep class com.glycemicgpt.mobile.domain.pump.** { *; }
-keep class com.glycemicgpt.mobile.domain.model.** { *; }

# Strip debug logs in release builds
-assumenosideeffects class timber.log.Timber {
    public static void d(...);
    public static void v(...);
}
