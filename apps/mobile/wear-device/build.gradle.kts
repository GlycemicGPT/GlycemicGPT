plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.android)
    alias(libs.plugins.kotlin.compose)
    alias(libs.plugins.hilt.android)
    alias(libs.plugins.ksp)
}

android {
    namespace = "com.glycemicgpt.weardevice"
    compileSdk = 35

    defaultConfig {
        // Must match the phone app's applicationId for Wearable Data Layer routing.
        // The namespace (com.glycemicgpt.weardevice) remains separate for R class isolation.
        applicationId = "com.glycemicgpt.mobile"
        minSdk = 35
        targetSdk = 35

        val appVersionName = "0.5.0" // x-release-please-version
        val parts = appVersionName.split(".")
        val major = parts.getOrElse(0) { "0" }.toInt()
        val minor = parts.getOrElse(1) { "0" }.toInt()
        val patch = parts.getOrElse(2) { "0" }.toInt()

        versionCode = major * 1_000_000 + minor * 10_000 + patch
        versionName = appVersionName

        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
    }

    signingConfigs {
        val debugKsFile = System.getenv("DEBUG_KEYSTORE_FILE")?.takeIf { it.isNotBlank() }
        if (debugKsFile != null) {
            getByName("debug") {
                storeFile = file(debugKsFile)
                storePassword = requireNotNull(
                    System.getenv("DEBUG_KEYSTORE_PASSWORD")?.takeIf { it.isNotBlank() },
                ) {
                    "DEBUG_KEYSTORE_PASSWORD must be set when DEBUG_KEYSTORE_FILE is provided"
                }
                keyAlias = requireNotNull(
                    System.getenv("DEBUG_KEY_ALIAS")?.takeIf { it.isNotBlank() },
                ) {
                    "DEBUG_KEY_ALIAS must be set when DEBUG_KEYSTORE_FILE is provided"
                }
                keyPassword = requireNotNull(
                    System.getenv("DEBUG_KEY_PASSWORD")?.takeIf { it.isNotBlank() },
                ) {
                    "DEBUG_KEY_PASSWORD must be set when DEBUG_KEYSTORE_FILE is provided"
                }
            }
        }

        create("release") {
            val ksFile = System.getenv("RELEASE_KEYSTORE_FILE")?.takeIf { it.isNotBlank() }
            if (ksFile != null) {
                storeFile = file(ksFile)
                storePassword = requireNotNull(
                    System.getenv("RELEASE_KEYSTORE_PASSWORD")?.takeIf { it.isNotBlank() },
                ) {
                    "RELEASE_KEYSTORE_PASSWORD must be set when RELEASE_KEYSTORE_FILE is provided"
                }
                keyAlias = requireNotNull(
                    System.getenv("RELEASE_KEY_ALIAS")?.takeIf { it.isNotBlank() },
                ) {
                    "RELEASE_KEY_ALIAS must be set when RELEASE_KEYSTORE_FILE is provided"
                }
                keyPassword = requireNotNull(
                    System.getenv("RELEASE_KEY_PASSWORD")?.takeIf { it.isNotBlank() },
                ) {
                    "RELEASE_KEY_PASSWORD must be set when RELEASE_KEYSTORE_FILE is provided"
                }
            }
        }
    }

    buildTypes {
        debug {
            isDebuggable = true
            applicationIdSuffix = ".debug"
            versionNameSuffix = "-debug"
            buildConfigField("String", "UPDATE_CHANNEL", "\"dev\"")
            buildConfigField(
                "int",
                "DEV_BUILD_NUMBER",
                project.findProperty("devBuildNumber")?.toString() ?: "0",
            )
        }
        release {
            buildConfigField("String", "UPDATE_CHANNEL", "\"stable\"")
            buildConfigField("int", "DEV_BUILD_NUMBER", "0")
            isMinifyEnabled = true
            isShrinkResources = true
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro",
            )
            val ksFile = System.getenv("RELEASE_KEYSTORE_FILE")?.takeIf { it.isNotBlank() }
            signingConfig = if (ksFile != null) {
                signingConfigs.getByName("release")
            } else {
                signingConfigs.getByName("debug")
            }
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
        buildConfig = true
        compose = true
    }

    packaging {
        resources {
            excludes += "/META-INF/{AL2.0,LGPL2.1}"
        }
    }
}

dependencies {
    // Wear OS Complications
    implementation(libs.wear.complications.data.source.ktx)

    // Watch Face Push API (Wear OS 6+)
    implementation(libs.wear.watchface.push)
    implementation(libs.wear.watchface.validator)

    // Wearable Data Layer
    implementation(libs.play.services.wearable)

    // AndroidX
    implementation(libs.androidx.core.ktx)
    implementation(libs.androidx.activity.compose)

    // Wear Compose UI
    implementation(libs.wear.compose.material)
    implementation(libs.wear.compose.foundation)

    // Compose (platform BOM for UI primitives)
    implementation(platform(libs.compose.bom))
    implementation(libs.compose.ui)
    implementation(libs.compose.ui.graphics)
    implementation(libs.compose.foundation)

    // Hilt DI
    implementation(libs.hilt.android)
    ksp(libs.hilt.compiler)

    // Coroutines
    implementation(libs.coroutines.core)
    implementation(libs.coroutines.android)
    implementation(libs.coroutines.play.services)

    // Logging
    implementation(libs.timber)

    // Unit tests
    testImplementation(libs.junit)
    testImplementation(libs.mockk)
    testImplementation(libs.coroutines.test)
    testImplementation(libs.turbine)
}
