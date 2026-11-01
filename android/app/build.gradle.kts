plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.android)
    alias(libs.plugins.kotlin.compose)
}

fun setting(name: String, fallback: String): String =
    (findProperty(name) as String?)?.takeIf { it.isNotBlank() } ?: fallback

android {
    namespace = "org.reelcheck.app"
    compileSdk = 36

    defaultConfig {
        applicationId = "org.reelcheck.app"
        minSdk = 26
        targetSdk = 36
        versionCode = (findProperty("versionCode") as String?)?.toIntOrNull() ?: 1
        versionName = "0.1.0"
        // AdMob ids: Google's test ids unless -PadmobAppId / -PadmobRewardedId are given (gradle.properties).
        manifestPlaceholders["admobAppId"] = setting("admobAppId", "ca-app-pub-3940256099942544~3347511713")
        buildConfigField("String", "ADMOB_REWARDED_ID",
            "\"${setting("admobRewardedId", "ca-app-pub-3940256099942544/5224354917")}\"")
        buildConfigField("String", "SITE_URL", "\"${setting("reelSiteUrl", "https://example.org")}\"")
    }

    signingConfigs {
        // Release signing from ~/.gradle/gradle.properties (never commit a keystore or its passwords).
        val store = findProperty("releaseStoreFile") as String?
        if (store != null) {
            create("release") {
                storeFile = file(store)
                storePassword = findProperty("releaseStorePassword") as String?
                keyAlias = findProperty("releaseKeyAlias") as String?
                keyPassword = findProperty("releaseKeyPassword") as String?
            }
        }
    }

    buildTypes {
        debug {
            applicationIdSuffix = ".debug"
            // 10.0.2.2 is the computer running the emulator: `uvicorn app.main:app --port 8000` there.
            buildConfigField("String", "API_URL", "\"${setting("reelApiUrl", "http://10.0.2.2:8000")}\"")
            manifestPlaceholders["cleartext"] = "true"
        }
        release {
            isMinifyEnabled = true
            isShrinkResources = true
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
            buildConfigField("String", "API_URL", "\"${setting("reelApiUrl", "https://api.example.org")}\"")
            manifestPlaceholders["cleartext"] = "false"
            signingConfig = signingConfigs.findByName("release")
        }
    }

    buildFeatures {
        compose = true
        buildConfig = true
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    lint {
        abortOnError = true
        checkReleaseBuilds = false
        // The specialUse foreground service and usage access are declared for Play review (docs/android.md).
        disable += setOf("ProtectedPermissions")
    }
}

kotlin { compilerOptions { jvmTarget.set(org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17) } }

dependencies {
    implementation("org.reelcheck:core")
    implementation(libs.coroutines.android)
    implementation(libs.androidx.core.ktx)
    implementation(libs.androidx.activity.compose)
    implementation(libs.androidx.lifecycle.runtime)
    implementation(libs.androidx.lifecycle.viewmodel.compose)
    implementation(libs.androidx.lifecycle.service)
    implementation(platform(libs.compose.bom))
    implementation(libs.compose.ui)
    implementation(libs.compose.material3)
    implementation(libs.compose.ui.tooling.preview)
    debugImplementation(libs.compose.ui.tooling)
    implementation(libs.play.services.ads)
    testImplementation(libs.junit)
}
