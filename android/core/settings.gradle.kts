// Pure Kotlin (no Android SDK needed): API client, check flow, link parsing, wording.
// Builds on its own (`gradle -p core test`) and as an included build of the app.
pluginManagement {
    repositories {
        gradlePluginPortal()
        mavenCentral()
    }
}
dependencyResolutionManagement {
    repositories { mavenCentral() }
    versionCatalogs { create("libs") { from(files("../gradle/libs.versions.toml")) } }
}
rootProject.name = "core"
