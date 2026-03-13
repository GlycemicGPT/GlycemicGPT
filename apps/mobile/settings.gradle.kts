pluginManagement {
    repositories {
        google {
            content {
                includeGroupByRegex("com\\.android.*")
                includeGroupByRegex("com\\.google.*")
                includeGroupByRegex("androidx.*")
            }
        }
        mavenCentral()
        gradlePluginPortal()
    }
}

dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories {
        google()
        mavenCentral()
        maven {
            url = uri("https://jitpack.io")
            content {
                includeGroup("com.github.jeziellago")
                includeModule("com.github.xgouchet", "AXML")
            }
        }
    }
}

rootProject.name = "GlycemicGPT"
include(":app")
include(":wear-device")
include(":pump-driver-api")
project(":pump-driver-api").projectDir = file("../../plugins/pump-driver-api")
include(":tandem-pump-driver")
project(":tandem-pump-driver").projectDir = file("../../plugins/shipped/tandem")
