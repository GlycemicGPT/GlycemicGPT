/**
 * Example runtime plugin for GlycemicGPT.
 *
 * This is a standalone Gradle project (NOT a submodule of the main app).
 * It demonstrates how to build a plugin JAR that can be sideloaded at runtime.
 *
 * Prerequisites:
 * - The pump-driver-api AAR or JAR must be available. Build it from the main
 *   project: `./gradlew :pump-driver-api:assembleRelease`
 * - Copy the AAR to this project's libs/ directory.
 *
 * Build steps:
 * 1. Compile: `./gradlew jar`
 * 2. Convert to DEX: `d8 --output dex-out/ build/libs/example-plugin.jar`
 * 3. Repackage DEX + manifest into the final plugin JAR:
 *    `cp build/libs/example-plugin.jar example-plugin.jar`
 *    `jar uf example-plugin.jar -C dex-out classes.dex`
 * 4. Install on device: copy example-plugin.jar to the app's plugins directory
 *    via adb or the app's "Add Plugin" button.
 *
 * See docs/plugin-architecture.md for full documentation.
 */
plugins {
    kotlin("jvm") version "2.0.21"
}

kotlin {
    compilerOptions {
        jvmTarget.set(org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17)
    }
}

java {
    sourceCompatibility = JavaVersion.VERSION_17
    targetCompatibility = JavaVersion.VERSION_17
}

repositories {
    mavenCentral()
    google()
}

dependencies {
    // Standalone: extract classes.jar from the pump-driver-api AAR and place in libs/:
    compileOnly(files("libs/pump-driver-api.jar"))

    // Alternatively, when building within the monorepo for testing:
    // compileOnly(project(":pump-driver-api"))

    compileOnly("org.jetbrains.kotlinx:kotlinx-coroutines-core:1.9.0")
}

tasks.jar {
    archiveBaseName.set("example-plugin")
    // src/main/resources/ is already included by processResources -- no extra from() needed.
    // The META-INF/plugin.json manifest is picked up automatically.
}
