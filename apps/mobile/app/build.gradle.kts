plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.android)
    alias(libs.plugins.kotlin.compose)
    alias(libs.plugins.hilt.android)
    alias(libs.plugins.ksp)
}

android {
    namespace = "com.glycemicgpt.mobile"
    compileSdk = 35

    defaultConfig {
        applicationId = "com.glycemicgpt.mobile"
        minSdk = 30
        targetSdk = 35

        val appVersionName = "0.11.0" // x-release-please-version
        val parts = appVersionName.split(".")
        val major = parts.getOrElse(0) { "0" }.toInt()
        val minor = parts.getOrElse(1) { "0" }.toInt()
        val patch = parts.getOrElse(2) { "0" }.toInt()

        versionCode = major * 1_000_000 + minor * 10_000 + patch
        versionName = appVersionName

        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
    }

    signingConfigs {
        // Shared debug keystore for consistent signatures across CI and local
        // builds.  When the env var is absent (local dev), Gradle falls back to
        // the default ~/.android/debug.keystore automatically.
        val debugKsFile = System.getenv("DEBUG_KEYSTORE_FILE")?.takeIf { it.isNotBlank() }
        if (debugKsFile != null) {
            getByName("debug") {
                storeFile = file(debugKsFile)
                storePassword = requireNotNull(System.getenv("DEBUG_KEYSTORE_PASSWORD")) {
                    "DEBUG_KEYSTORE_PASSWORD must be set when DEBUG_KEYSTORE_FILE is provided"
                }
                keyAlias = requireNotNull(System.getenv("DEBUG_KEY_ALIAS")) {
                    "DEBUG_KEY_ALIAS must be set when DEBUG_KEYSTORE_FILE is provided"
                }
                keyPassword = requireNotNull(System.getenv("DEBUG_KEY_PASSWORD")) {
                    "DEBUG_KEY_PASSWORD must be set when DEBUG_KEYSTORE_FILE is provided"
                }
            }
        }

        create("release") {
            val ksFile = System.getenv("RELEASE_KEYSTORE_FILE")
            if (ksFile != null) {
                storeFile = file(ksFile)
                storePassword = System.getenv("RELEASE_KEYSTORE_PASSWORD")
                keyAlias = System.getenv("RELEASE_KEY_ALIAS")
                keyPassword = System.getenv("RELEASE_KEY_PASSWORD")
            }
        }
    }

    // Medtronic read-only BLE driver kill switch. Default ON (the driver ships BETA, flag-gated);
    // build with MEDTRONIC_DRIVER_ENABLED=false to make the plugin invisible/inert (not selectable,
    // no pairing, no polling) without a code change -- the mobile analogue of the backend's
    // MEDTRONIC_CONNECT_ENABLED operator kill switch. Anything other than "false" keeps it enabled.
    val medtronicDriverEnabled = System.getenv("MEDTRONIC_DRIVER_ENABLED")?.lowercase() != "false"

    buildTypes {
        debug {
            isDebuggable = true
            applicationIdSuffix = ".debug"
            versionNameSuffix = "-debug"
            buildConfigField("String", "UPDATE_CHANNEL", "\"dev\"")
            buildConfigField("boolean", "MEDTRONIC_DRIVER_ENABLED", medtronicDriverEnabled.toString())
            val devBuildNumber = (project.findProperty("devBuildNumber") as? String)?.toIntOrNull() ?: 0
            buildConfigField("int", "DEV_BUILD_NUMBER", devBuildNumber.toString())

            // Sentry DSN is compiled in ONLY when a developer explicitly provides it at build time
            // (env SENTRY_DSN or -PsentryDsn), e.g. `op run -- ./gradlew assembleDebug` for local
            // testing. It is empty otherwise -> Sentry stays disabled. CI does NOT provide it, so
            // the published debug `dev-latest` APK ships with an empty DSN even though it is
            // downloadable. A DSN baked into any distributed client APK is extractable; keeping it
            // opt-in and local-only is the guarantee. See SentryInitializer.
            // A blank env var is treated as absent (so an exported-but-empty SENTRY_DSN= still
            // falls back to the -PsentryDsn property rather than forcing it empty).
            val sentryDsn = (System.getenv("SENTRY_DSN")?.takeIf { it.isNotBlank() }
                ?: (project.findProperty("sentryDsn") as? String)).orEmpty().trim()
            // Hard guard: never let a DSN ride along in a CI-produced (publishable) artifact.
            if (sentryDsn.isNotEmpty() && System.getenv("CI") == "true") {
                throw GradleException(
                    "SENTRY_DSN must not be set for CI builds: the debug APK is published as a " +
                        "downloadable artifact and the DSN would be extractable from it.",
                )
            }
            val sentryEnv = (System.getenv("SENTRY_ENVIRONMENT")?.takeIf { it.isNotBlank() }
                ?: (project.findProperty("sentryEnvironment") as? String))
                .orEmpty().trim().ifEmpty { "development" }
            // Escape backslash/quote so an unusual value can't break the generated Java literal.
            fun toJavaStringLiteral(value: String) =
                "\"" + value.replace("\\", "\\\\").replace("\"", "\\\"") + "\""
            buildConfigField("String", "SENTRY_DSN", toJavaStringLiteral(sentryDsn))
            buildConfigField("String", "SENTRY_ENVIRONMENT", toJavaStringLiteral(sentryEnv))
        }
        release {
            isMinifyEnabled = true
            isShrinkResources = true
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro"
            )
            val ksFile = System.getenv("RELEASE_KEYSTORE_FILE")
            signingConfig = if (ksFile != null) {
                signingConfigs.getByName("release")
            } else {
                signingConfigs.getByName("debug")
            }
            buildConfigField("String", "UPDATE_CHANNEL", "\"stable\"")
            buildConfigField("int", "DEV_BUILD_NUMBER", "0")
            buildConfigField("boolean", "MEDTRONIC_DRIVER_ENABLED", medtronicDriverEnabled.toString())

            // Never embed a Sentry DSN in a distributed/downloadable APK (it is client-extractable).
            buildConfigField("String", "SENTRY_DSN", "\"\"")
            buildConfigField("String", "SENTRY_ENVIRONMENT", "\"production\"")
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = "17"
    }

    buildFeatures {
        compose = true
        buildConfig = true
    }

    packaging {
        resources {
            excludes += "/META-INF/{AL2.0,LGPL2.1}"
            excludes += "/META-INF/versions/9/OSGI-INF/MANIFEST.MF"
        }
    }

    testOptions {
        unitTests.all {
            // Default Android test JVM heap (512MB) is too small for our
            // mockk-based tests; relaxed mocks of large interfaces and
            // coroutine-aware tests accumulate enough heap pressure to OOM.
            it.maxHeapSize = "2g"
        }
    }

    // Expose the exported Room schemas to instrumented tests so MigrationTestHelper
    // can build historical schema versions for migration tests.
    sourceSets.getByName("androidTest").assets.srcDirs(files("$projectDir/schemas"))
}

ksp {
    arg("room.schemaLocation", "$projectDir/schemas")
}

dependencies {
    // Pump driver modules
    implementation(project(":pump-driver-api"))
    implementation(project(":tandem-pump-driver"))
    implementation(project(":medtronic-pump-driver"))

    // AndroidX Core
    implementation(libs.androidx.core.ktx)
    implementation(libs.androidx.lifecycle.runtime)
    implementation(libs.androidx.lifecycle.viewmodel.compose)
    implementation(libs.androidx.activity.compose)

    // Compose
    implementation(platform(libs.compose.bom))
    implementation(libs.compose.ui)
    implementation(libs.compose.ui.graphics)
    implementation(libs.compose.ui.tooling.preview)
    implementation(libs.compose.material3)
    implementation(libs.compose.material.icons)
    debugImplementation(libs.compose.ui.tooling)
    debugImplementation(libs.compose.ui.test.manifest)

    // Navigation
    implementation(libs.navigation.compose)

    // Hilt DI
    implementation(libs.hilt.android)
    ksp(libs.hilt.compiler)
    implementation(libs.hilt.navigation.compose)

    // Room (local database)
    implementation(libs.room.runtime)
    implementation(libs.room.ktx)
    ksp(libs.room.compiler)

    // DataStore (encrypted settings)
    implementation(libs.datastore.preferences)

    // Networking
    implementation(libs.okhttp)
    implementation(libs.okhttp.logging)
    implementation(libs.okhttp.sse)
    implementation(libs.retrofit)
    implementation(libs.retrofit.moshi)
    implementation(libs.moshi)
    ksp(libs.moshi.codegen)

    // Markdown rendering
    implementation(libs.compose.markdown)

    // Security
    implementation(libs.security.crypto)

    // Database encryption (SQLCipher)
    implementation(libs.sqlcipher)
    implementation(libs.sqlite)

    // Background work
    implementation(libs.work.runtime)
    implementation(libs.hilt.work)
    ksp(libs.hilt.work.compiler)

    // Logging
    implementation(libs.timber)

    // Crash/error reporting. The DSN is injected only into debug builds (see buildTypes); it is
    // never embedded in a distributed/release APK, where it would be client-extractable.
    implementation(libs.sentry.android)
    implementation(libs.sentry.android.timber)

    // Wearable Data Layer (phone-to-watch sync)
    implementation(libs.play.services.wearable)
    implementation(libs.coroutines.play.services)

    // Coroutines
    implementation(libs.coroutines.core)
    implementation(libs.coroutines.android)

    // Unit tests
    testImplementation(libs.junit)
    testImplementation(libs.mockk)
    testImplementation(libs.mockwebserver)
    testImplementation(libs.coroutines.test)
    testImplementation(libs.turbine)
    testImplementation("org.json:json:20240303")

    // Android tests
    androidTestImplementation(libs.junit.ext)
    androidTestImplementation(libs.espresso)
    androidTestImplementation(platform(libs.compose.bom))
    androidTestImplementation(libs.compose.ui.test)
    androidTestImplementation(libs.room.testing)
}
