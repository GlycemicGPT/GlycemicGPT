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

        val appVersionName = "0.3.3" // x-release-please-version
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

    buildTypes {
        debug {
            isDebuggable = true
            applicationIdSuffix = ".debug"
            versionNameSuffix = "-debug"
            buildConfigField("String", "UPDATE_CHANNEL", "\"dev\"")
            val devBuildNumber = (project.findProperty("devBuildNumber") as? String)?.toIntOrNull() ?: 0
            buildConfigField("int", "DEV_BUILD_NUMBER", devBuildNumber.toString())
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
}

ksp {
    arg("room.schemaLocation", "$projectDir/schemas")
}

dependencies {
    // Pump driver modules
    implementation(project(":pump-driver-api"))
    implementation(project(":tandem-pump-driver"))

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
}
