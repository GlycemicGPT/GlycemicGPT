// Medtronic read-only BLE de-risk spike -- offline SAKE harness.
//
// Self-contained JVM project that vendors OpenMinimed JavaSake (GPL-3.0, used with
// permission -- see LICENSE / README.md) and drives the SAKE handshake + SeqCrypt
// round-trip against OpenMinimed's captured 780G pairing vectors. No pump required.
//
// This is a throwaway spike harness, NOT the production :medtronic-pump-driver module.

plugins {
    application
}

group = "com.glycemicgpt.medtronicspike"
version = "0.1.0-spike"

java {
    // Match JavaSake's source level so the vendored sources compile unchanged.
    sourceCompatibility = JavaVersion.VERSION_11
    targetCompatibility = JavaVersion.VERSION_11
}

repositories {
    mavenCentral()
}

dependencies {
    // JavaSake's only third-party runtime dependency: AES-CMAC (the JDK has no CMAC).
    implementation("org.bouncycastle:bcprov-jdk18on:1.79")

    testImplementation("org.junit.jupiter:junit-jupiter-api:5.11.3")
    testRuntimeOnly("org.junit.jupiter:junit-jupiter-engine:5.11.3")
    testRuntimeOnly("org.junit.platform:junit-platform-launcher:1.11.3")
}

application {
    // `./gradlew run` prints the human-readable handshake + cipher report.
    mainClass.set("com.glycemicgpt.medtronicspike.SakeSpikeHarness")
}

tasks.test {
    useJUnitPlatform()
    testLogging {
        events("passed", "skipped", "failed")
    }
}
