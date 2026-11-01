pluginManagement {
    repositories {
        google()
        mavenCentral()
        gradlePluginPortal()
    }
}
dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories {
        google()
        mavenCentral()
    }
}
rootProject.name = "reel-checker-android"
include(":app")
// Plain Kotlin logic (API client, check flow), testable without the Android SDK: `./gradlew -p core test`
includeBuild("core")
